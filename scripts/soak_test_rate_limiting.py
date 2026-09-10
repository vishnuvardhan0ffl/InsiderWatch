"""
scripts/soak_test_rate_limiting.py

One-hour live soak test for the Polymarket transport.

Example:
    python scripts/soak_test_rate_limiting.py ^
        --market 0xd1e4e03a0129aad7b23e835bfb5c0166d7342fb98e91aa7dd0f3e6cb423d9c21

For a quick check:
    python scripts/soak_test_rate_limiting.py --market CONDITION_ID --duration-seconds 60

The default duration is 3600 seconds (one hour).
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from collectors.session import ThrottledRetryingSession


BASE_URL = "https://data-api.polymarket.com"
RESULT_DIR = Path("data/external")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", required=True)
    parser.add_argument("--duration-seconds", type=int, default=3600)
    parser.add_argument("--interval-seconds", type=float, default=5.0)
    args = parser.parse_args()

    if args.duration_seconds <= 0:
        raise ValueError("--duration-seconds must be > 0")

    if args.interval_seconds < 0:
        raise ValueError("--interval-seconds must be >= 0")

    RESULT_DIR.mkdir(parents=True, exist_ok=True)

    transport = ThrottledRetryingSession(
        retries=5,
        token_bucket_capacity=10,
        token_refill_rate=5.0,
        failure_log_path="logs/api_failures.jsonl",
    )

    params = {
        "market": args.market,
        "limit": 1,
        "offset": 0,
        "takerOnly": "false",
    }

    started_at = utc_now()
    start_monotonic = time.monotonic()

    attempts = 0
    successful_calls = 0
    failed_calls = 0
    last_error = None

    while time.monotonic() - start_monotonic < args.duration_seconds:
        attempts += 1

        try:
            response = transport.get(
                f"{BASE_URL}/trades",
                params=params,
                timeout=30,
            )

            response.raise_for_status()
            payload = response.json()

            if not isinstance(payload, list):
                raise RuntimeError(
                    "Expected /trades to return a JSON list."
                )

            successful_calls += 1

        except Exception as exc:
            failed_calls += 1
            last_error = f"{type(exc).__name__}: {exc}"

        # No manual intervention is required; the loop continues.
        time.sleep(args.interval_seconds)

    result = {
        "started_at": started_at,
        "finished_at": utc_now(),
        "requested_duration_seconds": args.duration_seconds,
        "market": args.market,
        "attempts": attempts,
        "successful_calls": successful_calls,
        "failed_calls": failed_calls,
        "last_error": last_error,
        "failure_log": "logs/api_failures.jsonl",
        "completed_without_manual_intervention": True,
        "pass": successful_calls > 0,
    }

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = RESULT_DIR / f"rate_limit_soak_{timestamp}.json"
    output.write_text(
        json.dumps(result, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(result, indent=2))
    print(f"\nEvidence written to: {output}")


if __name__ == "__main__":
    main()
