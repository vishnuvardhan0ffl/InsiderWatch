#!/usr/bin/env python3
"""
verify_cache.py — acceptance demonstration for the raw storage and caching layer
PG-S2-55: Someone Always Knows

The unit tests in tests/test_cache.py prove the caching layer's behaviour
against a fake session, offline and deterministically. This script proves the
same three acceptance criteria against the live Polymarket API, and writes a
dated JSON evidence file the way verify_apis.py does. Run it from a machine
with normal (unblocked) internet access.

Usage:
    python verify_cache.py                      # market read from config/seeds.json
    python verify_cache.py --market <condition_id>
    python verify_cache.py --out data/external/cache_check_2026-09-07.json
    python verify_cache.py --keep                # leave the probe cache on disk

Checks, one per acceptance criterion plus the two guards:

    1. Re-running an identical collection performs zero network calls
    2. Raw responses retained unmodified, with a retrieval timestamp
       2a  the bytes on disk are the bytes the API sent
       2b  the recorded SHA-256 matches the file
       2c  retrieved_at is present, UTC, and the parameters used are recorded
    3. Cache location is configurable
       3a  an explicit path is honoured
       3b  INSIDERWATCH_CACHE_DIR is honoured
       3c  two caches in two places stay separate
    4. Offline replay returns the collected data and never reaches the network
    5. An unscoped /trades call is refused before anything is sent (WS4 test 8)

This writes into a throwaway cache directory under the system temp folder, not
into data/raw/, so running it can never disturb a frozen dataset.
"""
import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from collectors.cache import (          # noqa: E402
    CachedClient,
    CacheMiss,
    ResponseCache,
    UnscopedRequestError,
    resolve_cache_dir,
)
from collectors.polymarket import BASE_URL  # noqa: E402
from collectors.session import ThrottledRetryingSession  # noqa: E402

try:
    from config.dns_override import install_dns_override
    install_dns_override()
except Exception:
    pass

DEFAULT_SEEDS = Path("config/seeds.json")


def log(msg):
    print(msg, flush=True)


def record(results, check, name, result, detail):
    results.append({"check": check, "name": name, "result": result, "detail": detail})
    log(f"  [{result}] {check}. {name} — {detail}")


def load_market(seeds_path, cli_market):
    """CLI --market wins, otherwise the first seed market."""
    if cli_market:
        return cli_market
    path = Path(seeds_path) if seeds_path else DEFAULT_SEEDS
    if not path.exists():
        sys.exit(f"No market given and {path} not found. Pass --market <condition_id>.")
    doc = json.loads(path.read_text())
    markets = doc.get("markets", []) if isinstance(doc, dict) else list(doc)
    if not markets:
        sys.exit(f"No markets in {path}. Pass --market <condition_id>.")
    return markets[0]["condition_id"]


def main():
    parser = argparse.ArgumentParser(
        description="Acceptance demonstration for the caching layer (PG-S2-55)")
    parser.add_argument("--market", default=None,
                        help="Polymarket condition ID (default: first market in config/seeds.json)")
    parser.add_argument("--seeds", default=None, help="Seed markets JSON")
    parser.add_argument("--out", default=None,
                        help="Output JSON path (default: data/external/cache_check_<date>.json)")
    parser.add_argument("--keep", action="store_true",
                        help="Leave the probe cache directory on disk for inspection")
    args = parser.parse_args()

    market = load_market(args.seeds, args.market)
    params = {"market": market, "takerOnly": False, "limit": 5}
    probe_dir = Path(tempfile.mkdtemp(prefix="insiderwatch_cache_check_"))
    results = []

    log("=" * 70)
    log("CACHING LAYER ACCEPTANCE CHECK — PG-S2-55")
    log(f"Run started: {datetime.now(timezone.utc).isoformat()}")
    log(f"Market: {market}")
    log(f"Probe cache: {probe_dir}")
    log("=" * 70)

    try:
        client = CachedClient(BASE_URL,
                              cache=ResponseCache(probe_dir / "first"),
                              session=ThrottledRetryingSession())

        # --- Criterion 1 --------------------------------------------------
        first = client.get("/trades", params)
        calls_after_first = client.network_calls
        second = client.get("/trades", params)

        record(results, "1", "Identical re-run performs zero network calls",
               "PASS" if client.network_calls == calls_after_first == 1 else "FAIL",
               f"network calls: {calls_after_first} then {client.network_calls}; "
               f"second served from cache = {second.from_cache}; "
               f"{len(first.json())} rows returned")

        # --- Criterion 2 --------------------------------------------------
        body_path, meta_path = client.cache.paths_for("/trades", params)
        on_disk = body_path.read_bytes()
        meta = json.loads(meta_path.read_text())

        record(results, "2a", "Bytes on disk are the bytes the API sent",
               "PASS" if on_disk == first.body else "FAIL",
               f"{len(on_disk)} bytes at {body_path.name}; identical to response body "
               f"= {on_disk == first.body}")

        digest = hashlib.sha256(on_disk).hexdigest()
        record(results, "2b", "Recorded SHA-256 matches the stored file",
               "PASS" if meta["body_sha256"] == digest else "FAIL",
               f"meta {meta['body_sha256'][:16]}... vs file {digest[:16]}...")

        timestamp_ok = (meta.get("retrieved_at", "").endswith("+00:00")
                        and ["takerOnly", "false"] in meta.get("params", []))
        record(results, "2c", "Retrieval timestamp and parameters recorded",
               "PASS" if timestamp_ok else "FAIL",
               f"retrieved_at={meta.get('retrieved_at')}; params={meta.get('params')}")

        # --- Criterion 3 --------------------------------------------------
        explicit = resolve_cache_dir(probe_dir / "explicit")
        record(results, "3a", "Explicit cache path honoured",
               "PASS" if explicit == probe_dir / "explicit" else "FAIL",
               f"resolved to {explicit}")

        import os
        os.environ["INSIDERWATCH_CACHE_DIR"] = str(probe_dir / "from_env")
        from_env = resolve_cache_dir()
        os.environ.pop("INSIDERWATCH_CACHE_DIR")
        record(results, "3b", "INSIDERWATCH_CACHE_DIR honoured",
               "PASS" if from_env == probe_dir / "from_env" else "FAIL",
               f"resolved to {from_env}")

        elsewhere = ResponseCache(probe_dir / "second")
        record(results, "3c", "Two caches in two places stay separate",
               "PASS" if elsewhere.read("/trades", params) is None else "FAIL",
               "a second cache directory does not see the first one's entries")

        # --- Criterion 4: offline replay -----------------------------------
        offline = CachedClient(BASE_URL, cache=ResponseCache(probe_dir / "first"),
                               offline=True)          # no session at all
        replayed = offline.get_json("/trades", params)
        try:
            offline.get_json("/trades", {"market": market, "takerOnly": True, "limit": 5})
            miss_raised = False
        except CacheMiss:
            miss_raised = True
        record(results, "4", "Offline replay returns the data and never goes online",
               "PASS" if replayed == first.json() and miss_raised else "FAIL",
               f"replayed {len(replayed)} rows identical to collection = "
               f"{replayed == first.json()}; uncollected request raised CacheMiss = {miss_raised}")

        # --- Criterion 5: the scope guard ----------------------------------
        guard = CachedClient(BASE_URL, cache=ResponseCache(probe_dir / "guard"),
                             session=ThrottledRetryingSession())
        try:
            guard.get("/trades", {"start": 1, "end": 2, "limit": 5})
            refused = False
        except UnscopedRequestError:
            refused = True
        record(results, "5", "Unscoped /trades call refused before anything is sent",
               "PASS" if refused and guard.network_calls == 0 else "FAIL",
               f"UnscopedRequestError raised = {refused}; "
               f"network calls made = {guard.network_calls} (WS4 test 8)")

        index_lines = (probe_dir / "first" / "index.jsonl").read_text().strip().splitlines()
        log(f"\nindex.jsonl holds {len(index_lines)} record(s) for this run.")

    finally:
        if args.keep:
            log(f"\nProbe cache kept at {probe_dir}")
        else:
            shutil.rmtree(probe_dir, ignore_errors=True)

    out_path = Path(args.out) if args.out else Path(
        f"data/external/cache_check_{datetime.now(timezone.utc).date().isoformat()}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fails = [r for r in results if r["result"] == "FAIL"]
    evidence = {
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "story": "WS5 — Implement the raw storage and caching layer",
        "market_tested": market,
        "request_tested": {"endpoint": "/trades", "params": {k: str(v) for k, v in params.items()}},
        "headline_question": "Does the caching layer meet its three acceptance criteria against the live API?",
        "headline_answer": "YES" if not fails else "NO",
        "results": results,
    }
    out_path.write_text(json.dumps(evidence, indent=2, default=str))

    log("=" * 70)
    log(f"Done. {len(results)} checks run, {len(fails)} FAIL. Evidence written to {out_path}")
    log("=" * 70)
    return 0 if not fails else 2


if __name__ == "__main__":
    sys.exit(main())
