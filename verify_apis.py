#!/usr/bin/env python3
"""
verify_apis.py — WS4 API verification suite
PG-S2-55: Someone Always Knows

Confirms empirically what WS4_data_feasibility.md only confirmed from
documentation. Run this from a machine with normal (unblocked) internet
access — it will not run inside a sandboxed environment with egress
blocked.

Usage:
    python verify_apis.py
    python verify_apis.py --market <condition_id> [<condition_id> ...]
    python verify_apis.py --out data/external/feasibility_check_2026-08-19.json

Writes a dated JSON evidence file. Commit that file — it is what the
methodology section will cite as proof the APIs behaved as documented on
a specific date.

Tests (per WS4 Appendix B):
    1. Polymarket /trades unauthenticated reachability and field presence
    2. Polymarket /activity — activity types actually observed
    3. Polymarket /closed-positions — P&L field presence
    4. Kalshi /markets/trades — confirm absence of any identity field
    5. Kalshi cursor pagination depth
    6. Polymarket V1->V2 historical continuity across 28 Apr 2026 (HIGHEST PRIORITY)
    7. takerOnly true vs false record-count differential
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("This script requires the 'requests' package: pip install requests")


# --- DNS override: some networks intercept polymarket.com DNS ---
import socket as _socket
_orig_gai = _socket.getaddrinfo
_dns_cache = {}

def _doh_resolve(hostname):
    try:
        r = requests.get("https://cloudflare-dns.com/dns-query",
                         params={"name": hostname, "type": "A"},
                         headers={"Accept": "application/dns-json"}, timeout=10)
        r.raise_for_status()
        for a in r.json().get("Answer", []):
            if a.get("type") == 1:
                return a.get("data")
    except Exception as e:
        print(f"  [dns_override] DoH failed for {hostname}: {e}", file=sys.stderr)
    return None

def _patched_gai(host, port, family=0, type=0, proto=0, flags=0):
    if isinstance(host, str) and host.endswith("polymarket.com"):
        ip = _dns_cache.get(host) or _doh_resolve(host)
        if ip:
            _dns_cache[host] = ip
            return _orig_gai(ip, port, family, type, proto, flags)
    return _orig_gai(host, port, family, type, proto, flags)

_socket.getaddrinfo = _patched_gai
print("  [dns_override] Active: polymarket.com resolving via DoH.", file=sys.stderr)
# --- end DNS override ---

POLYMARKET_DATA_API = "https://data-api.polymarket.com"
KALSHI_API = "https://external-api.kalshi.com/trade-api/v2"

# 28 Apr 2026, ~11:00 UTC cutover per Polymarket Help Centre (WS4 §1.3)
V2_CUTOVER = datetime(2026, 4, 28, 11, 0, 0, tzinfo=timezone.utc)
V2_CUTOVER_TS = int(V2_CUTOVER.timestamp())
PRE_WINDOW_START = V2_CUTOVER_TS - 30 * 86400  # 30 days before cutover
PRE_WINDOW_END = V2_CUTOVER_TS - 1

TIMEOUT = 20


def get(url, params=None):
    try:
        r = requests.get(url, params=params, timeout=TIMEOUT)
        try:
            body = r.json()
        except ValueError:
            body = r.text[:500]
        return {"status_code": r.status_code, "body": body, "error": None}
    except requests.RequestException as e:
        return {"status_code": None, "body": None, "error": str(e)}


def log(msg):
    print(f"  {msg}")


def test_1_polymarket_trades(results):
    print("[1/7] Polymarket /trades — unauthenticated reachability + fields")
    r = get(f"{POLYMARKET_DATA_API}/trades", params={"limit": 5, "takerOnly": "true"})
    entry = {"test": 1, "name": "polymarket_trades_reachability", **r}
    if r["status_code"] == 200 and isinstance(r["body"], list) and r["body"]:
        entry["result"] = "PASS"
        entry["fields_present"] = sorted(r["body"][0].keys())
        entry["record_count"] = len(r["body"])
        log(f"PASS — {entry['record_count']} records, fields: {entry['fields_present']}")
        results.append(entry)
        return r["body"][0].get("proxyWallet")
    else:
        entry["result"] = "FAIL"
        log(f"FAIL — status {r['status_code']}, error {r['error']}")
    results.append(entry)
    return None


def test_2_polymarket_activity(results, user=None):
    print("[2/7] Polymarket /activity — observed activity types")
    if not user:
        print("  SKIPPED — no wallet discovered in test 1")
        results.append({"test": 2, "name": "polymarket_activity_types",
                        "result": "SKIPPED — no wallet available"})
        return
    r = get(f"{POLYMARKET_DATA_API}/activity",
            params={"user": user, "limit": 20, "start": 1})
    entry = {"test": 2, "name": "polymarket_activity_types", **r}
    if r["status_code"] == 200 and isinstance(r["body"], list):
        types = sorted({row.get("type") for row in r["body"] if isinstance(row, dict)})
        entry["result"] = "PASS" if r["body"] else "INCONCLUSIVE (empty page — retry with a user param)"
        entry["types_observed"] = types
        log(f"{entry['result']} — types seen: {types}")
    else:
        entry["result"] = "FAIL"
        log(f"FAIL — status {r['status_code']}, error {r['error']}")
    results.append(entry)


def test_3_polymarket_closed_positions(results, user=None):
    print("[3/7] Polymarket /closed-positions — P&L field presence")
    if not user:
        print("  SKIPPED — no wallet discovered in test 1")
        results.append({"test": 3, "name": "polymarket_closed_positions_fields",
                        "result": "SKIPPED — no wallet available"})
        return
    r = get(f"{POLYMARKET_DATA_API}/closed-positions",
            params={"user": user, "limit": 20})
    entry = {"test": 3, "name": "polymarket_closed_positions_fields", **r}
    if r["status_code"] == 200 and isinstance(r["body"], list) and r["body"]:
        entry["fields_present"] = sorted(r["body"][0].keys())
        expected = {"realizedPnl", "avgPrice", "curPrice", "totalBought"}
        entry["expected_fields_found"] = sorted(expected & set(entry["fields_present"]))
        entry["result"] = "PASS" if expected.issubset(entry["fields_present"]) else "PARTIAL"
        log(f"{entry['result']} — fields: {entry['fields_present']}")
    else:
        entry["result"] = "FAIL" if r["status_code"] != 200 else "INCONCLUSIVE (empty page — retry with a user param)"
        log(f"{entry['result']} — status {r['status_code']}, error {r['error']}")
    results.append(entry)


def test_4_kalshi_trades_fields(results):
    print("[4/7] Kalshi /markets/trades — confirm absence of identity field")
    r = get(f"{KALSHI_API}/markets/trades", params={"limit": 5})
    entry = {"test": 4, "name": "kalshi_trades_no_identity_field", **r}
    if r["status_code"] == 200 and isinstance(r["body"], dict) and r["body"].get("trades"):
        fields = sorted(r["body"]["trades"][0].keys())
        identity_terms = {"user", "account", "trader", "buyer", "seller", "wallet"}
        found_identity = [f for f in fields if any(t in f.lower() for t in identity_terms)]
        entry["fields_present"] = fields
        entry["identity_like_fields_found"] = found_identity
        entry["result"] = "PASS (no identity field, as documented)" if not found_identity else "UNEXPECTED — identity-like field present"
        log(f"{entry['result']} — fields: {fields}")
    else:
        entry["result"] = "FAIL"
        log(f"FAIL — status {r['status_code']}, error {r['error']}")
    results.append(entry)


def test_5_kalshi_pagination_depth(results):
    print("[5/7] Kalshi /markets/trades — cursor pagination depth")
    cursor = None
    pages = 0
    total = 0
    earliest_ts = None
    entry = {"test": 5, "name": "kalshi_cursor_pagination_depth"}
    try:
        while pages < 10:  # depth *probe*, not a full historical pull
            params = {"limit": 1000}
            if cursor:
                params["cursor"] = cursor
            r = get(f"{KALSHI_API}/markets/trades", params=params)
            if r["status_code"] != 200 or not isinstance(r["body"], dict):
                entry["stopped_reason"] = f"status {r['status_code']}, error {r['error']}"
                break
            trades = r["body"].get("trades", [])
            total += len(trades)
            if trades:
                ts_values = [t.get("created_time") for t in trades if t.get("created_time")]
                if ts_values:
                    page_min = min(ts_values)
                    earliest_ts = page_min if earliest_ts is None else min(earliest_ts, page_min)
            cursor = r["body"].get("cursor")
            pages += 1
            if not cursor or not trades:
                entry["stopped_reason"] = "no further cursor / empty page"
                break
            time.sleep(0.1)
        entry["pages_probed"] = pages
        entry["records_seen"] = total
        entry["earliest_created_time_seen"] = earliest_ts
        entry["result"] = "PASS (probe completed)" if total > 0 else "INCONCLUSIVE"
        log(f"{entry['result']} — {pages} pages, {total} records, earliest {earliest_ts}")
    except Exception as e:
        entry["result"] = "FAIL"
        entry["error"] = str(e)
        log(f"FAIL — {e}")
    results.append(entry)


def test_6_v1_v2_continuity(results, markets):
    print("[6/7] Polymarket V1->V2 historical continuity across 28 Apr 2026  *** HIGHEST PRIORITY ***")
    entry = {"test": 6, "name": "polymarket_v1_v2_continuity", "cutover_utc": V2_CUTOVER.isoformat()}
    if not markets:
        entry["result"] = "SKIPPED — no --market condition ID supplied"
        log("SKIPPED — pass one or more --market <condition_id> to run this test")
        results.append(entry)
        return
    per_market = []
    for m in markets:
        r = get(f"{POLYMARKET_DATA_API}/trades", params={
            "market": m,
            "start": PRE_WINDOW_START,
            "end": PRE_WINDOW_END,
            "takerOnly": "false",
            "limit": 100,
        })
        found = isinstance(r["body"], list) and len(r["body"]) > 0
        per_market.append({
            "condition_id": m,
            "status_code": r["status_code"],
            "pre_migration_trades_found": found,
            "record_count": len(r["body"]) if isinstance(r["body"], list) else 0,
            "error": r["error"],
        })
        log(f"  {m}: pre-migration trades found = {found} ({per_market[-1]['record_count']} records)")
    entry["per_market"] = per_market
    any_found = any(p["pre_migration_trades_found"] for p in per_market)
    entry["result"] = "YES — pre-migration history reachable" if any_found else "NO — escalate per R1, do not write collector code yet"
    results.append(entry)


def test_7_taker_only_differential(results, markets):
    print("[7/7] takerOnly true vs false — record-count differential")
    entry = {"test": 7, "name": "taker_only_differential"}
    market = markets[0] if markets else None
    import time as _t
    now = int(_t.time())
    params_base = {"limit": 1000, "start": now - 7 * 86400, "end": now}
    if market:
        params_base["market"] = market
    else:
        print("  NOTE: no --market given; counts may hit the page cap and be uninformative")
    r_true = get(f"{POLYMARKET_DATA_API}/trades", params={**params_base, "takerOnly": "true"})
    r_false = get(f"{POLYMARKET_DATA_API}/trades", params={**params_base, "takerOnly": "false"})
    n_true = len(r_true["body"]) if isinstance(r_true["body"], list) else None
    n_false = len(r_false["body"]) if isinstance(r_false["body"], list) else None
    entry.update({
        "market_used": market,
        "takerOnly_true_count": n_true,
        "takerOnly_false_count": n_false,
    })
    if n_true is not None and n_false is not None:
        entry["differential"] = n_false - n_true
        entry["result"] = "CONFIRMED BIAS RISK" if n_false > n_true else "NO DIFFERENCE OBSERVED (check sample size)"
        log(f"{entry['result']} — true={n_true}, false={n_false}, diff={entry['differential']}")
    else:
        entry["result"] = "FAIL"
        log(f"FAIL — true status {r_true['status_code']}, false status {r_false['status_code']}")
    results.append(entry)


def main():
    parser = argparse.ArgumentParser(description="WS4 API verification suite (PG-S2-55)")
    parser.add_argument("--market", nargs="*", default=[], help="Polymarket condition ID(s) for tests 6 and 7")
    parser.add_argument("--out", default=None, help="Output JSON path (default: data/external/feasibility_check_<date>.json)")
    args = parser.parse_args()

    results = []
    print("=" * 70)
    print("WS4 API VERIFICATION SUITE — PG-S2-55")
    print(f"Run started: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 70)

    sample_wallet = test_1_polymarket_trades(results)
    if sample_wallet:
        print(f"  (using discovered wallet {sample_wallet} for tests 2-3)")
    test_2_polymarket_activity(results, sample_wallet)
    test_3_polymarket_closed_positions(results, sample_wallet)
    test_4_kalshi_trades_fields(results)
    test_5_kalshi_pagination_depth(results)
    test_6_v1_v2_continuity(results, args.market)
    test_7_taker_only_differential(results, args.market)

    out_path = Path(args.out) if args.out else Path(
        f"data/external/feasibility_check_{datetime.now(timezone.utc).date().isoformat()}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    evidence = {
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "markets_tested": args.market,
        "results": results,
    }
    out_path.write_text(json.dumps(evidence, indent=2, default=str))

    print("=" * 70)
    fails = [r for r in results if str(r.get("result", "")).startswith("FAIL")]
    print(f"Done. {len(results)} tests run, {len(fails)} FAIL. Evidence written to {out_path}")
    if fails:
        print("Triage each FAIL in writing before relying on the affected endpoint.")
    print("=" * 70)


if __name__ == "__main__":
    main()
