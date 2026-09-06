"""
collectors/polymarket.py

Polymarket Data API collector.

Features
--------
1. Trade collection from /trades.
2. Time-window pagination.
3. Automatic window splitting when the 10,000 offset cap is reached.
4. Explicit takerOnly handling.
5. Duplicate removal.
6. JSON caching.
7. Rate limiting and retry handling.
8. Metadata recording.
"""

from __future__ import annotations

import hashlib
import json
import time

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

import requests


# ============================================================
# Configuration
# ============================================================

BASE_URL = "https://data-api.polymarket.com"

CACHE_DIR = Path("data/raw/polymarket/cache")

MIN_INTERVAL_S = 0.3

_last_call = 0.0


# API offset limits
TRADES_OFFSET_CAP = 10_000
ACTIVITY_OFFSET_CAP = 5_000


# Number of rows requested per API call
PAGE_LIMIT = 500


# Start with seven-day windows.
# High-volume windows are automatically split if required.
DEFAULT_WINDOW_S = 7 * 86400


# ============================================================
# Rate limiting
# ============================================================

def _throttle():
    """
    Keep requests comfortably below the API rate limit.
    """

    global _last_call

    elapsed = time.monotonic() - _last_call

    if elapsed < MIN_INTERVAL_S:
        time.sleep(MIN_INTERVAL_S - elapsed)

    _last_call = time.monotonic()


# ============================================================
# Cache
# ============================================================

def _cache_key(endpoint: str, params: dict) -> Path:
    """
    Generate a deterministic cache filename from the endpoint
    and request parameters.
    """

    raw = json.dumps(
        {
            "endpoint": endpoint,
            "params": params
        },
        sort_keys=True
    )

    digest = hashlib.sha256(
        raw.encode()
    ).hexdigest()[:24]

    return (
        CACHE_DIR
        / endpoint.strip("/")
        / f"{digest}.json"
    )


# ============================================================
# HTTP request helper
# ============================================================

def _get(
    endpoint: str,
    params: dict,
    use_cache: bool = True,
    retries: int = 5
):
    """
    Perform a GET request with:

    - caching
    - throttling
    - retry handling
    - exponential backoff
    """

    cache_path = _cache_key(
        endpoint,
        params
    )

    # --------------------------------------------------------
    # Return cached request if available
    # --------------------------------------------------------

    if use_cache and cache_path.exists():

        return json.loads(
            cache_path.read_text(
                encoding="utf-8"
            )
        )

    url = f"{BASE_URL}{endpoint}"

    backoff = 1.0

    # --------------------------------------------------------
    # API request
    # --------------------------------------------------------

    for attempt in range(retries):

        _throttle()

        try:

            response = requests.get(
                url,
                params=params,
                timeout=20
            )

        except requests.RequestException:

            if attempt == retries - 1:
                raise

            time.sleep(backoff)

            backoff *= 2

            continue

        # ----------------------------------------------------
        # Retry rate-limit and server errors
        # ----------------------------------------------------

        if (
            response.status_code == 429
            or response.status_code >= 500
        ):

            if attempt == retries - 1:

                response.raise_for_status()

            time.sleep(backoff)

            backoff *= 2

            continue

        response.raise_for_status()

        body = response.json()

        # ----------------------------------------------------
        # Save successful response to cache
        # ----------------------------------------------------

        if use_cache:

            cache_path.parent.mkdir(
                parents=True,
                exist_ok=True
            )

            cache_path.write_text(
                json.dumps(body),
                encoding="utf-8"
            )

        return body

    raise RuntimeError(
        f"Exhausted retries for "
        f"{endpoint} {params}"
    )


# ============================================================
# Trade query
# ============================================================

@dataclass
class TradeQuery:

    user: Optional[str] = None

    market: Optional[str] = None

    # None means the caller did not make an explicit choice.
    taker_only: Optional[bool] = None

    start: Optional[int] = None

    end: Optional[int] = None


# ============================================================
# Query validation
# ============================================================

def _validate_trade_query(
    query: TradeQuery
):

    if query.start is None:
        raise ValueError(
            "TradeQuery.start is required."
        )

    if query.end is None:
        raise ValueError(
            "TradeQuery.end is required."
        )

    if query.start > query.end:
        raise ValueError(
            "TradeQuery.start must be <= TradeQuery.end."
        )

    # Historical time-window collection must be scoped.
    if not query.market and not query.user:

        raise ValueError(
            "A market or user must be supplied "
            "for historical trade collection."
        )

    # Never silently rely on the API default.
    if query.taker_only is None:

        raise ValueError(
            "taker_only must be explicitly set "
            "to True or False."
        )

    if not isinstance(
        query.taker_only,
        bool
    ):

        raise TypeError(
            "taker_only must be True or False."
        )


# ============================================================
# Duplicate key
# ============================================================

def _trade_key(
    row: dict
) -> str:
    """
    Use the complete API record as the duplicate key.

    This is safer than relying only on transactionHash because
    one blockchain transaction may potentially contain more than
    one trade-related record.
    """

    return json.dumps(
        row,
        sort_keys=True,
        separators=(",", ":"),
        default=str
    )


# ============================================================
# Fetch a single time window
# ============================================================

def _fetch_trade_window(
    query: TradeQuery,
    start: int,
    end: int,
    request_log: list
) -> list:
    """
    Collect all trades in one start/end window.

    If the API offset budget reaches 10,000 before the window
    finishes, split the window into two smaller windows and
    collect both recursively.

    This prevents records beyond the offset cap from being
    silently lost.
    """

    offset = 0

    rows = []

    while True:

        params = {
            "limit": PAGE_LIMIT,
            "offset": offset,
            "start": start,
            "end": end,
            "takerOnly":
                "true"
                if query.taker_only
                else "false"
        }

        if query.market:
            params["market"] = query.market

        if query.user:
            params["user"] = query.user

        # ----------------------------------------------------
        # API request
        # ----------------------------------------------------

        page = _get(
            "/trades",
            params
        )

        if not isinstance(page, list):

            raise RuntimeError(
                "Polymarket /trades did not "
                "return a JSON list."
            )

        # ----------------------------------------------------
        # Record request for metadata/debugging
        # ----------------------------------------------------

        request_log.append({
            "type": "request",
            "start": start,
            "end": end,
            "offset": offset,
            "limit": PAGE_LIMIT,
            "records_received": len(page)
        })

        print(
            f"Window {start} -> {end} | "
            f"offset={offset} | "
            f"records={len(page)}"
        )

        # ----------------------------------------------------
        # Empty page = finished
        # ----------------------------------------------------

        if not page:

            return rows

        rows.extend(page)

        # ----------------------------------------------------
        # Partial page = finished
        # ----------------------------------------------------

        if len(page) < PAGE_LIMIT:

            return rows

        next_offset = (
            offset + len(page)
        )

        # ----------------------------------------------------
        # Offset ceiling reached
        # ----------------------------------------------------

        if next_offset >= TRADES_OFFSET_CAP:

            # If start == end we cannot split time further.
            if start >= end:

                raise RuntimeError(
                    "More than 10,000 trades exist "
                    f"inside timestamp {start}. "
                    "Time-window pagination cannot "
                    "split this interval further."
                )

            midpoint = (
                start + end
            ) // 2

            if midpoint < start:

                raise RuntimeError(
                    "Could not split trade window."
                )

            request_log.append({
                "type": "split",
                "original_start": start,
                "original_end": end,
                "left_start": start,
                "left_end": midpoint,
                "right_start": midpoint + 1,
                "right_end": end
            })

            print()
            print(
                "Offset limit reached."
            )

            print(
                f"Splitting window:"
            )

            print(
                f"LEFT  : {start} -> {midpoint}"
            )

            print(
                f"RIGHT : {midpoint + 1} -> {end}"
            )

            print()

            # ------------------------------------------------
            # IMPORTANT
            #
            # Discard the incomplete original window and
            # recollect using two complete smaller windows.
            # ------------------------------------------------

            left_rows = _fetch_trade_window(
                query=query,
                start=start,
                end=midpoint,
                request_log=request_log
            )

            right_rows = _fetch_trade_window(
                query=query,
                start=midpoint + 1,
                end=end,
                request_log=request_log
            )

            return (
                left_rows
                + right_rows
            )

        # ----------------------------------------------------
        # Continue ordinary offset pagination
        # ----------------------------------------------------

        offset = next_offset


# ============================================================
# Main trade collection function
# ============================================================

def collect_trades(
    query: TradeQuery,
    window_s: int = DEFAULT_WINDOW_S
):
    """
    Collect complete trade history for a market or wallet.

    Returns
    -------
    trades : list
        Deduplicated trades.

    metadata : dict
        Collection settings and pagination evidence.
    """

    _validate_trade_query(
        query
    )

    if window_s <= 0:

        raise ValueError(
            "window_s must be greater than zero."
        )

    request_log = []

    raw_rows = []

    window_start = query.start

    # ========================================================
    # Walk time windows
    # ========================================================

    while window_start <= query.end:

        window_end = min(
            window_start
            + window_s
            - 1,

            query.end
        )

        print()
        print("=" * 70)

        print(
            f"Collecting window "
            f"{window_start} -> {window_end}"
        )

        print("=" * 70)

        rows = _fetch_trade_window(
            query=query,
            start=window_start,
            end=window_end,
            request_log=request_log
        )

        raw_rows.extend(
            rows
        )

        window_start = (
            window_end + 1
        )

    # ========================================================
    # Exact duplicate removal
    # ========================================================

    seen = set()

    trades = []

    duplicate_count = 0

    for row in raw_rows:

        key = _trade_key(
            row
        )

        if key in seen:

            duplicate_count += 1

            continue

        seen.add(
            key
        )

        trades.append(
            row
        )

    # ========================================================
    # Metadata
    # ========================================================

    split_count = sum(
        1
        for item in request_log
        if item.get("type") == "split"
    )

    request_count = sum(
        1
        for item in request_log
        if item.get("type") == "request"
    )

    metadata = {

        "source":
            "Polymarket Data API",

        "endpoint":
            "/trades",

        "market":
            query.market,

        "user":
            query.user,

        # Acceptance criterion:
        # explicitly record takerOnly.
        "takerOnly":
            query.taker_only,

        "start":
            query.start,

        "end":
            query.end,

        "pagination_method":
            "time-window + offset + recursive window splitting",

        "initial_window_seconds":
            window_s,

        "page_limit":
            PAGE_LIMIT,

        "offset_cap":
            TRADES_OFFSET_CAP,

        "request_count":
            request_count,

        "window_split_count":
            split_count,

        "raw_records_received":
            len(raw_rows),

        "duplicates_removed":
            duplicate_count,

        "final_trade_count":
            len(trades),

        "duplicate_detection_pass":
            duplicate_count == 0,

        "request_log":
            request_log
    }

    return (
        trades,
        metadata
    )


# ============================================================
# Generator compatibility
# ============================================================

def fetch_trades(
    query: TradeQuery,
    window_s: int = DEFAULT_WINDOW_S
) -> Iterator[dict]:
    """
    Compatibility wrapper for callers that expect an iterator.
    """

    trades, _ = collect_trades(
        query=query,
        window_s=window_s
    )

    yield from trades


# ============================================================
# Save trade collection
# ============================================================

def save_trade_collection(
    trades: list,
    metadata: dict,
    output_dir="data/raw/polymarket",
    name="trades"
):
    """
    Save raw trades and collection metadata.
    """

    output_dir = Path(
        output_dir
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    trades_path = (
        output_dir
        / f"{name}.json"
    )

    metadata_path = (
        output_dir
        / f"{name}_metadata.json"
    )

    trades_path.write_text(
        json.dumps(
            trades,
            indent=2,
            default=str
        ),
        encoding="utf-8"
    )

    metadata_path.write_text(
        json.dumps(
            metadata,
            indent=2,
            default=str
        ),
        encoding="utf-8"
    )

    print()
    print(
        f"Trades saved to: {trades_path}"
    )

    print(
        f"Metadata saved to: {metadata_path}"
    )

    return (
        trades_path,
        metadata_path
    )


# ============================================================
# Activity collector
# ============================================================

def fetch_activity(
    user: str,
    start: int = 1,
    exclude_deposits_withdrawals: bool = False
) -> Iterator[dict]:

    offset = 0

    while True:

        params = {
            "user": user,
            "limit": PAGE_LIMIT,
            "offset": offset,
            "start": start,
            "excludeDepositsWithdrawals":
                str(
                    exclude_deposits_withdrawals
                ).lower()
        }

        page = _get(
            "/activity",
            params
        )

        if not page:
            break

        yield from page

        offset += len(page)

        if (
            len(page) < PAGE_LIMIT
            or offset >= ACTIVITY_OFFSET_CAP
        ):
            break


# ============================================================
# Closed positions collector
# ============================================================

def fetch_closed_positions(
    user: str
) -> Iterator[dict]:

    offset = 0

    while True:

        params = {
            "user": user,
            "limit": PAGE_LIMIT,
            "offset": offset
        }

        page = _get(
            "/closed-positions",
            params
        )

        if not page:
            break

        yield from page

        offset += len(page)

        if len(page) < PAGE_LIMIT:
            break