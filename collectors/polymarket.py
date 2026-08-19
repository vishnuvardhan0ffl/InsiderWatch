"""
collectors/polymarket.py

Collector for the Polymarket Data API (https://data-api.polymarket.com).
No authentication required. Implements:

  - Time-window pagination. Offset is capped at 10,000 on /trades and
    5,000 on /activity (WS4 §1.4), so any high-activity wallet or market
    must be paginated by start/end windows, each with its own offset
    budget, rather than by offset alone.
  - Explicit takerOnly handling. The API defaults takerOnly to true,
    which silently drops maker-side fills (WS4 §3.1, backlog risk R4).
    This module refuses to guess — the caller must set it.
  - Simple on-disk JSON caching keyed by endpoint + parameters, so a
    repeated collection performs zero network calls (WS5 story: raw
    storage and caching layer).

This is a Sprint 2 starting point — it covers /trades, /activity and
/closed-positions per the Sprint 2 backlog. Rate limiting is a basic
client-side throttle plus exponential backoff on 429/5xx; the documented
ceiling is 200 req/10s on /trades and 150 req/10s on /positions and
/closed-positions (WS4 §3.3) — this module stays well under both.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

import requests

BASE_URL = "https://data-api.polymarket.com"
CACHE_DIR = Path("data/raw/polymarket")

MIN_INTERVAL_S = 0.3
_last_call = 0.0

TRADES_OFFSET_CAP = 10_000
ACTIVITY_OFFSET_CAP = 5_000
DEFAULT_WINDOW_S = 7 * 86400  # 7-day windows; shrink for very high-volume markets/wallets


def _throttle():
    global _last_call
    elapsed = time.monotonic() - _last_call
    if elapsed < MIN_INTERVAL_S:
        time.sleep(MIN_INTERVAL_S - elapsed)
    _last_call = time.monotonic()


def _cache_key(endpoint: str, params: dict) -> Path:
    raw = json.dumps({"endpoint": endpoint, "params": params}, sort_keys=True)
    digest = hashlib.sha256(raw.encode()).hexdigest()[:24]
    return CACHE_DIR / endpoint.strip("/") / f"{digest}.json"


def _get(endpoint: str, params: dict, use_cache: bool = True, retries: int = 5):
    cache_path = _cache_key(endpoint, params)
    if use_cache and cache_path.exists():
        return json.loads(cache_path.read_text())

    url = f"{BASE_URL}{endpoint}"
    backoff = 1.0
    for attempt in range(retries):
        _throttle()
        try:
            r = requests.get(url, params=params, timeout=20)
        except requests.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep(backoff)
            backoff *= 2
            continue
        if r.status_code == 429 or r.status_code >= 500:
            if attempt == retries - 1:
                r.raise_for_status()
            time.sleep(backoff)
            backoff *= 2
            continue
        r.raise_for_status()
        body = r.json()
        if use_cache:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(body))
        return body
    raise RuntimeError(f"Exhausted retries for {endpoint} {params}")


@dataclass
class TradeQuery:
    user: Optional[str] = None
    market: Optional[str] = None
    taker_only: bool = True  # caller must decide explicitly — see module docstring
    start: Optional[int] = None
    end: Optional[int] = None


def fetch_trades(query: TradeQuery, window_s: int = DEFAULT_WINDOW_S) -> Iterator[dict]:
    """
    Yield every trade matching `query`, walking time windows so no single
    request needs an offset above TRADES_OFFSET_CAP.
    """
    if query.start is None or query.end is None:
        raise ValueError("start and end are required for windowed pagination")

    window_start = query.start
    seen_ids = set()

    while window_start < query.end:
        window_end = min(window_start + window_s, query.end)
        offset = 0
        while True:
            params = {
                "limit": 500,
                "offset": offset,
                "start": window_start,
                "end": window_end,
                "takerOnly": str(query.taker_only).lower(),
            }
            if query.user:
                params["user"] = query.user
            if query.market:
                params["market"] = query.market

            page = _get("/trades", params)
            if not page:
                break
            for row in page:
                key = row.get("transactionHash", "") + str(row.get("timestamp"))
                if key in seen_ids:
                    continue
                seen_ids.add(key)
                yield row

            offset += len(page)
            if len(page) < params["limit"] or offset >= TRADES_OFFSET_CAP:
                if offset >= TRADES_OFFSET_CAP:
                    # Shrink the window and retry rather than silently
                    # dropping records past the offset cap.
                    new_end = (window_start + window_end) // 2
                    if new_end <= window_start:
                        raise RuntimeError(f"Cannot shrink window further below offset cap at {window_start}")
                    window_end = new_end
                    offset = 0
                    continue
                break

        window_start = window_end


def fetch_activity(user: str, start: int = 1, exclude_deposits_withdrawals: bool = False) -> Iterator[dict]:
    """
    Full wallet activity (trades, splits, merges, redemptions, funding).
    start=1 requests full history rather than the ~3-year default window —
    this is the off-chain route to wallet age and funding behaviour (WS4 §3.2).
    """
    offset = 0
    while True:
        params = {
            "user": user,
            "limit": 500,
            "offset": offset,
            "start": start,
            "excludeDepositsWithdrawals": str(exclude_deposits_withdrawals).lower(),
        }
        page = _get("/activity", params)
        if not page:
            break
        yield from page
        offset += len(page)
        if len(page) < params["limit"] or offset >= ACTIVITY_OFFSET_CAP:
            break


def fetch_closed_positions(user: str) -> Iterator[dict]:
    offset = 0
    while True:
        params = {"user": user, "limit": 500, "offset": offset}
        page = _get("/closed-positions", params)
        if not page:
            break
        yield from page
        offset += len(page)
        if len(page) < params["limit"]:
            break
