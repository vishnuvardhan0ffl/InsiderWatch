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
6. Raw response caching (collectors/cache.py).
7. Rate limiting and retry handling (collectors/session.py).
8. Metadata recording.
"""

from __future__ import annotations

import json

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

from collectors.cache import CachedClient, ResponseCache
from collectors.session import ThrottledRetryingSession


# ============================================================
# Configuration
# ============================================================

BASE_URL = "https://data-api.polymarket.com"

# Minimum gap between requests, handed to the session. Well under the
# documented ceiling of 200 req/10s on /trades (WS4 section 3.3); caching,
# not throttling, is what keeps our request count low.
MIN_INTERVAL_S = 0.3


# API offset limits
TRADES_OFFSET_CAP = 10_000
ACTIVITY_OFFSET_CAP = 5_000


# Number of rows requested per API call
PAGE_LIMIT = 500


# Start with seven-day windows.
# High-volume windows are automatically split if required.
DEFAULT_WINDOW_S = 7 * 86400


# ============================================================
# Transport and storage
# ============================================================
#
# Both used to live in this file: a _throttle() on a module global, a
# _cache_key() that hashed the parameters, and a _get() that wrote the
# *parsed* body back out with json.dumps.
#
# That cache could not be cited as evidence. It stored a re-serialised copy
# rather than the bytes the API sent, and recorded nothing about when the
# request was made, so "the API returned this on that date" had nothing
# behind it. Raw storage with a retrieval timestamp is the whole point of
# the WS5 caching story.
#
# Storage now lives in collectors/cache.py and transport in
# collectors/session.py. _get keeps its name, its signature and its
# behaviour, so every caller below and every existing test is untouched -
# only the internals changed. What is new is what lands on disk: the exact
# response bytes, a metadata file recording the URL, parameters, retrieval
# time and a SHA-256 of the body, and a line in data/raw/index.jsonl.
#
# See docs/caching_layer.md.

DEFAULT_RETRIES = 5

_default_client: Optional[CachedClient] = None


def default_client() -> CachedClient:
    """
    The client _get uses. Built on first use rather than at import, so
    importing this module never opens a session or touches the cache
    directory.

    The cache location comes from ResponseCache: data/raw by default,
    overridable with INSIDERWATCH_CACHE_DIR.
    """

    global _default_client

    if _default_client is None:

        _default_client = CachedClient(
            BASE_URL,
            cache=ResponseCache(),
            session=ThrottledRetryingSession(
                retries=DEFAULT_RETRIES,
                min_interval_s=MIN_INTERVAL_S
            ),
        )

    return _default_client


def set_default_client(
    client: Optional[CachedClient]
) -> Optional[CachedClient]:
    """
    Point the module at a different client, or pass None to reset it.

    Used by the CLI to select a cache directory or offline mode, and by
    tests to substitute a fake session.
    """

    global _default_client

    _default_client = client

    return _default_client


def _client_for(retries: int) -> CachedClient:
    """
    The shared client, unless a caller asked for a different retry budget -
    in which case a one-off client with the same cache directory.
    """

    if retries == DEFAULT_RETRIES:
        return default_client()

    return CachedClient(
        BASE_URL,
        cache=ResponseCache(),
        session=ThrottledRetryingSession(
            retries=retries,
            min_interval_s=MIN_INTERVAL_S
        ),
    )


def _get(
    endpoint: str,
    params: dict,
    use_cache: bool = True,
    retries: int = DEFAULT_RETRIES
):
    """
    Perform a GET request with:

    - raw caching, keyed by endpoint and parameters
    - throttling
    - retry handling
    - exponential backoff

    use_cache=False forces a fresh request. The response is still written
    to the cache: the caller's intent is "re-fetch", not "do not record",
    and a gap in the raw store is a gap in the run's evidence trail.

    Only successful responses are stored. A cached 429 or 500 page would be
    replayed forever as though it were data.

    Raises UnscopedRequestError on a /trades or /activity call carrying no
    user, market or eventId. Such a call ignores start and end and returns
    current trades with no error (WS4 test 8), which would fill a
    time-windowed collection with today's data while looking healthy.
    """

    return _client_for(retries).get_json(
        endpoint,
        params,
        refresh=not use_cache
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
# Activity, positions and closed positions
# ============================================================
#
# These live in collectors/polymarket_activity.py.
#
# There used to be a fetch_activity() and a fetch_closed_positions() here.
# Both paged by offset alone and stopped dead at the API's 5,000 cap, with
# no time windowing and no warning - so on any active wallet they returned
# a partial history and a first-activity timestamp that was wrong and
# looked entirely plausible. Wallet age is a headline feature, so that was
# not a small bug.
#
# The replacements walk time windows the same way collect_trades does, and
# come with derive_first_activity_timestamp, derive_funding_events and
# derive_realised_pnl on top:
#
#     from collectors.polymarket_activity import (
#         ActivityQuery, collect_activity, collect_wallet_profile,
#         fetch_positions, fetch_closed_positions,
#     )
#
# They import _get from this module, so they share this file's cache and
# throttle. Do not reintroduce an offset-only version here.
