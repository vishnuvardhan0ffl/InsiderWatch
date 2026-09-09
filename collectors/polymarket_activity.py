"""
collectors/polymarket_activity.py

Polymarket Data API — activity, positions and closed-positions
collectors (SCRUM-45).

Companion to collectors/polymarket.py, which owns the trade
collector, the HTTP layer, the cache and the throttle. This
module reuses all of them rather than duplicating them.

Features
--------
1. Activity collection from /activity with full history.
2. Time-window pagination with recursive splitting at the
   5,000 offset cap.
3. Window-honoured verification (guards the start/end scope
   trap confirmed by feasibility test 8).
4. Position and closed-position collection.
5. Duplicate removal and collection metadata.
6. Derivations: first-activity timestamp, funding events,
   realised PnL per closed position.

Grounding
---------
Field names below are taken from
data/external/feasibility_check_2026-08-20.json:

  * /activity        test 2, types TRADE and REDEEM only
  * /closed-positions test 3, realizedPnl confirmed
  * scope trap        test 8

DEPOSIT and WITHDRAWAL row shapes were NOT observed in that
run. See derive_funding_events for the consequences.
"""

from __future__ import annotations

import json

from dataclasses import dataclass
from typing import Iterator, Optional

from .polymarket import (
    _get,
    PAGE_LIMIT,
    ACTIVITY_OFFSET_CAP,
    DEFAULT_WINDOW_S,
)


# ============================================================
# Constants
# ============================================================

# Activity types that represent movement of collateral in or
# out of the account, as opposed to market participation.
FUNDING_TYPES = frozenset({
    "DEPOSIT",
    "WITHDRAWAL",
})


# Every activity type documented in WS4 3.2 and
# docs/data_dictionary.md. Anything outside this set is
# surfaced in metadata so a genuinely new type is noticed
# rather than silently absorbed.
#
# The last four were missing from an earlier version of this
# set, which made a normal wallet report three "unexpected"
# types on its first live run. A whitelist that cries wolf
# gets ignored, so it has to match the documentation exactly.
KNOWN_ACTIVITY_TYPES = frozenset({
    "TRADE",
    "SPLIT",
    "MERGE",
    "REDEEM",
    "REWARD",
    "CONVERSION",
    "DEPOSIT",
    "WITHDRAWAL",
    "YIELD",
    "MAKER_REBATE",
    "TAKER_REBATE",
    "REFERRAL_REWARD",
})


# ============================================================
# Activity query
# ============================================================

@dataclass
class ActivityQuery:

    user: str

    # Epoch seconds. Default 1 retrieves full history rather
    # than the default ~3 year window.
    start: int = 1

    # None means "up to now"; resolved before windowing.
    end: Optional[int] = None

    # Must be False to receive DEPOSIT and WITHDRAWAL rows.
    # The API default is True even when type= asks for them.
    exclude_deposits_withdrawals: bool = False


def _validate_activity_query(
    query: ActivityQuery
):

    if not query.user:

        # Feasibility test 8: without user= or market= the API
        # ignores start/end and returns current data with a
        # 200. An unscoped activity call is never valid.
        raise ValueError(
            "ActivityQuery.user is required. Unscoped calls "
            "silently ignore start/end (feasibility test 8)."
        )

    if query.start is None:

        raise ValueError(
            "ActivityQuery.start is required."
        )

    if query.end is None:

        raise ValueError(
            "ActivityQuery.end must be resolved before "
            "collection."
        )

    if query.start > query.end:

        raise ValueError(
            "ActivityQuery.start must be <= "
            "ActivityQuery.end."
        )


# ============================================================
# Duplicate key
# ============================================================

def _activity_key(
    row: dict
) -> str:
    """
    Use the complete API record as the duplicate key.

    Activity rows carry no unique identifier. transactionHash
    is not sufficient: one transaction can produce several
    activity records, and the feasibility sample shows
    multiple rows sharing a timestamp.
    """

    return json.dumps(
        row,
        sort_keys=True,
        separators=(",", ":"),
        default=str
    )


# ============================================================
# Window verification
# ============================================================

def _verify_window(
    page: list,
    start: int,
    end: int
):
    """
    Confirm the API actually honoured start/end.

    Feasibility test 8 proved that start/end are silently
    dropped on unscoped calls, returning current data with a
    200 status. Activity calls are always user-scoped so the
    trap should not fire here, but a silent window failure
    would corrupt every derived wallet-age figure, so it is
    checked rather than assumed.
    """

    for row in page:

        ts = row.get("timestamp")

        if ts is None:

            raise RuntimeError(
                "Activity record has no timestamp; cannot "
                "verify window compliance."
            )

        if ts < start or ts > end:

            raise RuntimeError(
                f"Activity record timestamp {ts} falls "
                f"outside requested window {start} -> {end}. "
                "The API appears to have ignored start/end "
                "(see feasibility test 8)."
            )


# ============================================================
# Fetch a single activity window
# ============================================================

def _fetch_activity_window(
    query: ActivityQuery,
    start: int,
    end: int,
    request_log: list
) -> list:
    """
    Collect all activity in one start/end window.

    If the offset budget reaches 5,000 before the window
    finishes, discard the partial window and recollect as two
    smaller windows. This mirrors the trade collector and
    prevents records beyond the cap being silently lost.

    Sorted ascending so that the oldest record — the one the
    first-activity derivation depends on — arrives on page
    one rather than beyond the cap.
    """

    offset = 0

    rows = []

    while True:

        params = {
            "user": query.user,
            "limit": PAGE_LIMIT,
            "offset": offset,
            "start": start,
            "end": end,
            "sortBy": "TIMESTAMP",
            "sortDirection": "ASC",
            "excludeDepositsWithdrawals":
                "true"
                if query.exclude_deposits_withdrawals
                else "false"
        }

        page = _get(
            "/activity",
            params
        )

        if not isinstance(page, list):

            raise RuntimeError(
                "Polymarket /activity did not return a "
                "JSON list."
            )

        _verify_window(
            page,
            start,
            end
        )

        request_log.append({
            "type": "request",
            "start": start,
            "end": end,
            "offset": offset,
            "limit": PAGE_LIMIT,
            "records_received": len(page)
        })

        if not page:

            return rows

        rows.extend(page)

        if len(page) < PAGE_LIMIT:

            return rows

        next_offset = (
            offset + len(page)
        )

        # ----------------------------------------------------
        # Offset ceiling reached
        # ----------------------------------------------------

        if next_offset >= ACTIVITY_OFFSET_CAP:

            if start >= end:

                raise RuntimeError(
                    "More than 5,000 activity records exist "
                    f"inside timestamp {start}. Time-window "
                    "pagination cannot split this interval "
                    "further."
                )

            midpoint = (
                start + end
            ) // 2

            request_log.append({
                "type": "split",
                "original_start": start,
                "original_end": end,
                "left_start": start,
                "left_end": midpoint,
                "right_start": midpoint + 1,
                "right_end": end
            })

            # ------------------------------------------------
            # Discard the incomplete window and recollect
            # using two complete smaller windows.
            # ------------------------------------------------

            left_rows = _fetch_activity_window(
                query=query,
                start=start,
                end=midpoint,
                request_log=request_log
            )

            right_rows = _fetch_activity_window(
                query=query,
                start=midpoint + 1,
                end=end,
                request_log=request_log
            )

            return (
                left_rows
                + right_rows
            )

        offset = next_offset


# ============================================================
# Main activity collection function
# ============================================================

def collect_activity(
    query: ActivityQuery,
    window_s: Optional[int] = None
):
    """
    Collect complete activity history for a wallet.

    window_s
        Size of the first time window. Leave it as None, which means "one
        window covering the whole range" and lets the offset-cap split find
        the right size by itself.

        Do NOT set this to a small fixed value when start=1. The wallet-age
        query asks for all of history, and history starts at the Unix epoch,
        so 7-day windows means walking 1970 to today one week at a time. On
        the first live run that cost 2,969 requests for a single wallet, of
        which 2,945 returned nothing and 2,934 were spent on empty weeks
        before the wallet existed. Starting wide and splitting only when the
        5,000-record cap is actually hit collects the same 7,374 records in
        a few dozen requests.

    Returns
    -------
    activity : list
        Deduplicated activity records, ascending by timestamp.

    metadata : dict
        Collection settings and pagination evidence.
    """

    if window_s is None:
        # One window. _fetch_activity_window halves it whenever the offset
        # cap is reached, so the split is driven by how much data is there
        # rather than by a guess made up front.
        window_s = max(1, query.end - query.start + 1)

    _validate_activity_query(
        query
    )

    if window_s <= 0:

        raise ValueError(
            "window_s must be greater than zero."
        )

    request_log = []

    raw_rows = []

    window_start = query.start

    while window_start <= query.end:

        window_end = min(
            window_start
            + window_s
            - 1,

            query.end
        )

        rows = _fetch_activity_window(
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

    activity = []

    duplicate_count = 0

    for row in raw_rows:

        key = _activity_key(
            row
        )

        if key in seen:

            duplicate_count += 1

            continue

        seen.add(
            key
        )

        activity.append(
            row
        )

    activity.sort(
        key=lambda r: r.get("timestamp", 0)
    )

    # ========================================================
    # Metadata
    # ========================================================

    types_observed = sorted({
        row.get("type")
        for row in activity
        if row.get("type")
    })

    unexpected_types = sorted(
        set(types_observed)
        - KNOWN_ACTIVITY_TYPES
    )

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
            "/activity",

        "user":
            query.user,

        "excludeDepositsWithdrawals":
            query.exclude_deposits_withdrawals,

        "start":
            query.start,

        "end":
            query.end,

        "sortDirection":
            "ASC",

        "pagination_method":
            "time-window + offset + recursive window "
            "splitting",

        "initial_window_seconds":
            window_s,

        "page_limit":
            PAGE_LIMIT,

        "offset_cap":
            ACTIVITY_OFFSET_CAP,

        "request_count":
            request_count,

        "window_split_count":
            split_count,

        "raw_records_received":
            len(raw_rows),

        "duplicates_removed":
            duplicate_count,

        "final_activity_count":
            len(activity),

        "types_observed":
            types_observed,

        "unexpected_types":
            unexpected_types,

        "funding_types_observed":
            sorted(
                set(types_observed)
                & FUNDING_TYPES
            ),

        "request_log":
            request_log
    }

    return (
        activity,
        metadata
    )


# ============================================================
# Positions collector
# ============================================================

def fetch_positions(
    user: str
) -> Iterator[dict]:
    """
    Collect current open positions for a wallet.

    Offset behaviour for this endpoint has not been observed
    at depth. The cap guard below raises rather than
    truncating if the trade-collector ceiling is reached.
    """

    offset = 0

    while True:

        params = {
            "user": user,
            "limit": PAGE_LIMIT,
            "offset": offset
        }

        page = _get(
            "/positions",
            params
        )

        if not isinstance(page, list):

            raise RuntimeError(
                "Polymarket /positions did not return a "
                "JSON list."
            )

        if not page:
            return

        yield from page

        offset += len(page)

        if offset >= ACTIVITY_OFFSET_CAP:

            raise RuntimeError(
                f"/positions reached offset {offset} without "
                "exhausting results. This endpoint has no "
                "time-window parameters, so pagination "
                "cannot be split. Investigate before "
                "trusting this wallet's position set."
            )


# ============================================================
# Closed positions collector
# ============================================================

def fetch_closed_positions(
    user: str
) -> Iterator[dict]:
    """
    Collect closed positions for a wallet.

    Same cap caveat as fetch_positions.
    """

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

        if not isinstance(page, list):

            raise RuntimeError(
                "Polymarket /closed-positions did not "
                "return a JSON list."
            )

        if not page:
            return

        yield from page

        offset += len(page)

        if offset >= ACTIVITY_OFFSET_CAP:

            raise RuntimeError(
                f"/closed-positions reached offset {offset} "
                "without exhausting results. This endpoint "
                "has no time-window parameters, so "
                "pagination cannot be split."
            )


# ============================================================
# Derivation: first activity timestamp
# ============================================================

def derive_first_activity_timestamp(
    activity: list
) -> Optional[int]:
    """
    Earliest observed activity timestamp for the wallet.

    Only meaningful when the activity list came from a
    complete collection started at epoch 1. A truncated
    collection yields a first-activity figure that is wrong
    in the direction of making the wallet look younger, which
    is precisely the error that matters for this project.
    """

    timestamps = [
        row["timestamp"]
        for row in activity
        if row.get("timestamp") is not None
    ]

    if not timestamps:
        return None

    return min(timestamps)


# ============================================================
# Derivation: funding events
# ============================================================

def derive_funding_events(
    activity: list
) -> dict:
    """
    Extract DEPOSIT and WITHDRAWAL records.

    Amount field confirmed live on 2026-09-08 against wallet
    0xd99f3bec8e060ada0aef0c4057695dd5bc22fcdc: funding rows
    carry identical values in size and usdcSize. usdcSize is
    used, consistent with TRADE rows where the two differ
    (size is outcome tokens, usdcSize is collateral).
    """

    events = []

    missing_amount = 0

    for row in activity:

        if row.get("type") not in FUNDING_TYPES:
            continue

        amount = row.get("usdcSize")

        if amount is None:
            missing_amount += 1

        events.append({
            "timestamp":
                row.get("timestamp"),

            "type":
                row.get("type"),

            "amount":
                amount,

            "transactionHash":
                row.get("transactionHash"),

            "proxyWallet":
                row.get("proxyWallet"),

            "raw":
                row
        })

    events.sort(
        key=lambda e: e.get("timestamp") or 0
    )

    deposits = [
        e["amount"]
        for e in events
        if e["type"] == "DEPOSIT"
        and e["amount"] is not None
    ]

    withdrawals = [
        e["amount"]
        for e in events
        if e["type"] == "WITHDRAWAL"
        and e["amount"] is not None
    ]

    return {

        "events":
            events,

        "event_count":
            len(events),

        "deposit_count":
            len(deposits),

        "withdrawal_count":
            len(withdrawals),

        "total_deposited":
            sum(deposits),

        "total_withdrawn":
            sum(withdrawals),

        "records_without_amount_field":
            missing_amount,

        "field_mapping_confirmed":
            missing_amount == 0
    }


# ============================================================
# Derivation: realised PnL per closed position
# ============================================================

def derive_realised_pnl(
    closed_positions: list
) -> dict:
    """
    Realised PnL per closed position.

    realizedPnl, avgPrice, totalBought and curPrice are all
    confirmed present on /closed-positions by feasibility
    test 3.
    """

    positions = []

    missing_pnl = 0

    for row in closed_positions:

        pnl = row.get("realizedPnl")

        if pnl is None:
            missing_pnl += 1

        positions.append({
            "conditionId":
                row.get("conditionId"),

            "asset":
                row.get("asset"),

            "title":
                row.get("title"),

            "slug":
                row.get("slug"),

            "outcome":
                row.get("outcome"),

            "outcomeIndex":
                row.get("outcomeIndex"),

            "avgPrice":
                row.get("avgPrice"),

            "totalBought":
                row.get("totalBought"),

            "curPrice":
                row.get("curPrice"),

            "realizedPnl":
                pnl,

            "endDate":
                row.get("endDate"),

            "timestamp":
                row.get("timestamp")
        })

    positions.sort(
        key=lambda p: p.get("timestamp") or 0
    )

    realised = [
        p["realizedPnl"]
        for p in positions
        if p["realizedPnl"] is not None
    ]

    return {

        "positions":
            positions,

        "position_count":
            len(positions),

        "positions_missing_pnl":
            missing_pnl,

        "total_realised_pnl":
            sum(realised) if realised else 0.0,

        "winning_positions":
            sum(1 for v in realised if v > 0),

        "losing_positions":
            sum(1 for v in realised if v < 0)
    }


# ============================================================
# Wallet profile
# ============================================================

def collect_wallet_profile(
    user: str,
    start: int = 1,
    end: Optional[int] = None,
    window_s: int = DEFAULT_WINDOW_S
) -> dict:
    """
    Single entry point covering the SCRUM-45 acceptance
    criteria for one wallet.

    Returns first-activity timestamp, funding event list and
    realised PnL per closed position, plus the collection
    metadata that evidences complete pagination.
    """

    import time as _time

    if end is None:
        end = int(_time.time())

    query = ActivityQuery(
        user=user,
        start=start,
        end=end,
        exclude_deposits_withdrawals=False
    )

    activity, activity_metadata = collect_activity(
        query=query,
        window_s=window_s
    )

    positions = list(
        fetch_positions(user)
    )

    closed_positions = list(
        fetch_closed_positions(user)
    )

    return {

        "user":
            user,

        "first_activity_timestamp":
            derive_first_activity_timestamp(activity),

        "funding":
            derive_funding_events(activity),

        "realised_pnl":
            derive_realised_pnl(closed_positions),

        "open_position_count":
            len(positions),

        "activity":
            activity,

        "positions":
            positions,

        "closed_positions":
            closed_positions,

        "activity_metadata":
            activity_metadata
    }
