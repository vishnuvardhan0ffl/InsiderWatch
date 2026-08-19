"""
collectors/kalshi.py

Collector for the Kalshi Trade API v2 public trades endpoint. No
authentication is required for public market data. The schema carries no
buyer, seller, user or account field of any kind (WS4 §4) — this
collector is market-level only by design, feeding abnormal-volume
detection and cross-platform validation against Polymarket, not
trader-level analysis.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterator, Optional

import requests

BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
CACHE_DIR = Path("data/raw/kalshi")

MIN_INTERVAL_S = 0.2  # polite default; documented limits describe authenticated tiers only


def _get(params: dict, retries: int = 5) -> dict:
    url = f"{BASE_URL}/markets/trades"
    backoff = 1.0
    for attempt in range(retries):
        time.sleep(MIN_INTERVAL_S)
        r = requests.get(url, params=params, timeout=20)
        if r.status_code == 429 or r.status_code >= 500:
            if attempt == retries - 1:
                r.raise_for_status()
            time.sleep(backoff)
            backoff *= 2
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Exhausted retries for /markets/trades {params}")


def fetch_trades(
    ticker: Optional[str] = None,
    min_ts: Optional[int] = None,
    max_ts: Optional[int] = None,
    cache: bool = True,
) -> Iterator[dict]:
    """Yield all trades matching the filters, walking cursor pagination."""
    cursor = None
    page_num = 0
    while True:
        params = {"limit": 1000}
        if ticker:
            params["ticker"] = ticker
        if min_ts:
            params["min_ts"] = min_ts
        if max_ts:
            params["max_ts"] = max_ts
        if cursor:
            params["cursor"] = cursor

        cache_path = None
        body = None
        if cache:
            key = f"{ticker or 'all'}_{min_ts or 0}_{max_ts or 0}_{page_num}"
            cache_path = CACHE_DIR / f"{key}.json"
            if cache_path.exists():
                body = json.loads(cache_path.read_text())

        if body is None:
            body = _get(params)
            if cache:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(body))

        trades = body.get("trades", [])
        yield from trades

        cursor = body.get("cursor")
        page_num += 1
        if not cursor or not trades:
            break
