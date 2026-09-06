#!/usr/bin/env python3
"""
verify_apis.py — WS4 API verification suite
PG-S2-55: Someone Always Knows

Confirms empirically what WS4_data_feasibility.md only confirmed from
documentation. Run this from a machine with normal (unblocked) internet
access — it will not run inside a sandboxed environment with egress
blocked.

Usage:
    python verify_apis.py                       # seeds read from config/seeds.json
    python verify_apis.py --market <condition_id> [<condition_id> ...]
    python verify_apis.py --seeds config/seeds.json
    python verify_apis.py --out data/external/feasibility_check_2026-08-20.json

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
       6a  seed markets return pre-migration trades
       6b  a market live across the cutover returns trades on both sides
       6c  the same proxyWallet is retrievable in both contract eras
    7. takerOnly true vs false record-count differential (+ limit honouring)
    8. Scope trap — are start/end honoured on an UNSCOPED /trades call?

CHANGE LOG
    2026-08-20  Test 6 rewritten. The previous version searched only the
                30 days immediately before the cutover, which returns zero
                records for any seed market that resolved earlier than that
                — including the Nobel and Maduro cases. It would have
                reported "NO pre-migration history" and triggered the R1
                escalation on a false negative. The window is now
                start=1 .. cutover-1, i.e. all retrievable history.
                Tests 6b, 6c and 8 added; test 7 now refuses to run
                unscoped. See docs/WS4_test6_V1V2_continuity_finding.md.
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
V2_CUTOVER_TS = int(V2_CUTOVER.timestamp())  # 1777374000

# All retrievable history strictly before the cutover. Do NOT narrow this to a
# fixed number of days before the cutover — see the 2026-08-20 change-log entry.
PRE_WINDOW_START = 1
PRE_WINDOW_END = V2_CUTOVER_TS - 1

DEFAULT_SEEDS = Path(__file__).parent / "config" / "seeds.json"

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


def iso(ts):
    """Unix seconds -> ISO 8601 Z string. Every timestamp in the evidence file
    carries its ISO form so a reader does not have to trust our arithmetic."""
    if ts is None:
        return None
    return datetime.fromtimestamp(int(ts), timezone.utc).isoformat().replace("+00:00", "Z")


def ts_summary(body):
    """Reduce a /trades or /activity array to the facts the evidence file needs."""
    if not isinstance(body, list):
        return {"count": None, "note": "response was not a JSON array"}
    if not body:
        return {"count": 0, "min_ts": None, "max_ts": None,
                "pre_migration_records": 0, "post_migration_records": 0}
    stamps = [r.get("timestamp") for r in body
              if isinstance(r, dict) and isinstance(r.get("timestamp"), (int, float))]
    return {
        "count": len(body),
        "min_ts": min(stamps) if stamps else None,
        "max_ts": max(stamps) if stamps else None,
        "min_iso": iso(min(stamps)) if stamps else None,
        "max_iso": iso(max(stamps)) if stamps else None,
        "pre_migration_records": sum(1 for t in stamps if t < V2_CUTOVER_TS),
        "post_migration_records": sum(1 for t in stamps if t >= V2_CUTOVER_TS),
        "distinct_wallets": len({r.get("proxyWallet") for r in body
                                 if isinstance(r, dict) and r.get("proxyWallet")}),
    }


def load_seeds(seeds_path, cli_markets):
    """CLI --market wins. Otherwise read config/seeds.json. Returns
    (seed_markets, probe_market_condition_id)."""
    if cli_markets:
        return ([{"condition_id": m, "category": "cli", "title": None} for m in cli_markets], None)
    path = Path(seeds_path) if seeds_path else DEFAULT_SEEDS
    if not path.exists():
        return ([], None)
    doc = json.loads(path.read_text())
    markets = doc.get("markets", []) if isinstance(doc, dict) else list(doc)
    probe = None
    for c in (doc.get("control_markets", []) if isinstance(doc, dict) else []):
        if c.get("role") == "boundary_probe":
            probe = c.get("condition_id")
    return (markets, probe)


def test_1_polymarket_trades(results):
    print("[1/8] Polymarket /trades — unauthenticated reachability + fields")
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
    print("[2/8] Polymarket /activity — observed activity types")
    if not user:
        print("  SKIPPED — no wallet discovered in test 1")
        results.append({"test": 2, "name": "polymarket_activity_types",
                        "result": "SKIPPED — no wallet available"})
        return
    r = get(f"{POLYMARKET_DATA_API}/activity",
            params={"user": user, "limit": 20, "start": 1,
                    "excludeDepositsWithdrawals": "false"})
    entry = {"test": 2, "name": "polymarket_activity_types", **r}
    if r["status_code"] == 200 and isinstance(r["body"], list):
        types = sorted({row.get("type") for row in r["body"] if isinstance(row, dict)})
        entry["result"] = "PASS" if r["body"] else "INCONCLUSIVE (empty page — retry with a user param)"
        entry["types_observed"] = types
        entry["fields_present"] = sorted(r["body"][0].keys()) if r["body"] else []
        log(f"{entry['result']} — types seen: {types}")
    else:
        entry["result"] = "FAIL"
        log(f"FAIL — status {r['status_code']}, error {r['error']}")
    results.append(entry)


def test_3_polymarket_closed_positions(results, user=None):
    print("[3/8] Polymarket /closed-positions — P&L field presence")
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
        stamps = [row.get("timestamp") for row in r["body"]
                  if isinstance(row, dict) and isinstance(row.get("timestamp"), (int, float))]
        if stamps:
            entry["oldest_closed_position"] = {"ts": min(stamps), "iso": iso(min(stamps)),
                                               "pre_migration": min(stamps) < V2_CUTOVER_TS}
        log(f"{entry['result']} — fields: {entry['fields_present']}")
    else:
        # An empty array is a property of the wallet's book, not of the API.
        entry["result"] = "FAIL" if r["status_code"] != 200 else \
            "INCONCLUSIVE (empty — this wallet has no closed positions; not an API limitation)"
        log(f"{entry['result']} — status {r['status_code']}, error {r['error']}")
    results.append(entry)


def test_4_kalshi_trades_fields(results):
    print("[4/8] Kalshi /markets/trades — confirm absence of identity field")
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
    print("[5/8] Kalshi /markets/trades — cursor pagination depth")
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
        entry["interpretation"] = (
            "The unfiltered Kalshi feed is dense enough that 10 pages of 1000 reach back "
            "only minutes. Historical Kalshi collection MUST filter by ticker and min_ts; "
            "cursor-walking the global feed is not a viable strategy."
        )
        log(f"{entry['result']} — {pages} pages, {total} records, earliest {earliest_ts}")
    except Exception as e:
        entry["result"] = "FAIL"
        entry["error"] = str(e)
        log(f"FAIL — {e}")
    results.append(entry)


def test_6_v1_v2_continuity(results, markets, probe_market):
    print("[6/8] Polymarket V1->V2 historical continuity across 28 Apr 2026  *** HIGHEST PRIORITY ***")
    entry = {
        "test": 6,
        "name": "polymarket_v1_v2_continuity",
        "cutover_utc": V2_CUTOVER.isoformat(),
        "cutover_ts": V2_CUTOVER_TS,
        "pre_window": {"start": PRE_WINDOW_START, "end": PRE_WINDOW_END,
                       "end_iso": iso(PRE_WINDOW_END)},
    }
    if not markets:
        entry["result"] = "SKIPPED — no seed markets (populate config/seeds.json or pass --market)"
        log("SKIPPED — populate config/seeds.json or pass --market <condition_id>")
        results.append(entry)
        return

    # --- 6a: do the seed markets return trades from before the cutover? ---
    per_market = []
    for m in markets:
        cid = m["condition_id"] if isinstance(m, dict) else m
        r = get(f"{POLYMARKET_DATA_API}/trades", params={
            "market": cid,
            "start": PRE_WINDOW_START,
            "end": PRE_WINDOW_END,
            "takerOnly": "false",
            "limit": 100,
        })
        s = ts_summary(r["body"])
        found = bool(s.get("count"))
        clean = found and s.get("post_migration_records") == 0
        per_market.append({
            "condition_id": cid,
            "category": m.get("category") if isinstance(m, dict) else None,
            "title": m.get("title") if isinstance(m, dict) else None,
            "status_code": r["status_code"],
            "pre_migration_trades_found": found,
            "all_records_pre_migration": clean,
            "summary": s,
            "fields_present": sorted(r["body"][0].keys())
            if isinstance(r["body"], list) and r["body"] else [],
            "error": r["error"],
        })
        log(f"  6a {cid[:14]}…: pre-migration trades = {found} "
            f"({s.get('count')} records, earliest {s.get('min_iso')})")
    entry["a_seed_markets"] = per_market

    # --- 6b: a market live across the cutover, queried either side of it ---
    if probe_market:
        before = get(f"{POLYMARKET_DATA_API}/trades", params={
            "market": probe_market, "start": V2_CUTOVER_TS - 43200,
            "end": V2_CUTOVER_TS - 1, "takerOnly": "false", "limit": 100})
        after = get(f"{POLYMARKET_DATA_API}/trades", params={
            "market": probe_market, "start": V2_CUTOVER_TS,
            "end": V2_CUTOVER_TS + 86400, "takerOnly": "false", "limit": 100})
        s_before, s_after = ts_summary(before["body"]), ts_summary(after["body"])
        entry["b_boundary_probe"] = {
            "condition_id": probe_market,
            "window_before": s_before,
            "window_after": s_after,
            "no_gap_at_boundary": bool(s_before.get("count")) and bool(s_after.get("count")),
        }
        log(f"  6b boundary probe: {s_before.get('count')} trades in the 12h before, "
            f"{s_after.get('count')} in the 24h after")

        # --- 6c: is the same proxyWallet retrievable in both eras? ---
        wallets, seen = [], set()
        if isinstance(before["body"], list):
            for rec in before["body"]:
                w = rec.get("proxyWallet")
                if w and w not in seen:
                    seen.add(w)
                    wallets.append(w)
                if len(wallets) >= 5:
                    break
        per_wallet, continuous = [], 0
        for w in wallets:
            w_pre = get(f"{POLYMARKET_DATA_API}/trades", params={
                "user": w, "start": 1, "end": PRE_WINDOW_END, "takerOnly": "false", "limit": 50})
            w_post = get(f"{POLYMARKET_DATA_API}/trades", params={
                "user": w, "start": V2_CUTOVER_TS, "takerOnly": "false", "limit": 50})
            sp, sq = ts_summary(w_pre["body"]), ts_summary(w_post["body"])
            both = bool(sp.get("count")) and bool(sq.get("count"))
            continuous += int(both)
            per_wallet.append({"proxyWallet": w, "pre": sp, "post": sq,
                               "active_both_eras_same_address": both})
            time.sleep(0.25)
        entry["c_wallet_identity_stability"] = {
            "wallets_sampled": len(wallets),
            "wallets_active_in_both_eras": continuous,
            "per_wallet": per_wallet,
            "interpretation": (
                "A wallet appearing in both eras under one proxyWallet means trader-level "
                "features can be computed across the boundary with no identity join. "
                "Zero here may be sampling rather than a data gap — re-run with a different "
                "probe market before concluding anything."
            ),
        }
        log(f"  6c wallet identity: {continuous}/{len(wallets)} sampled wallets active in both eras")

    any_found = any(p["pre_migration_trades_found"] for p in per_market)
    all_found = all(p["pre_migration_trades_found"] for p in per_market)
    if all_found:
        entry["result"] = "YES — pre-migration history reachable for every seed market"
    elif any_found:
        entry["result"] = "PARTIAL — some seed markets returned no pre-migration trades; triage each before escalating"
    else:
        entry["result"] = "NO — escalate per R1, do not write collector code yet"
    log(entry["result"])
    results.append(entry)


PAGE_LIMIT = 1000  # request size used for counting; raise only with evidence


def _count_trades(market, start, end, taker_only):
    """Records returned for one market in one window. Returns (count, censored).

    `censored` is True when the response filled the page, i.e. the true count is
    >= count and we cannot see the rest without paginating. A censored count is
    not a count — callers must shrink the window rather than report it.
    """
    r = get(f"{POLYMARKET_DATA_API}/trades", params={
        "market": market, "start": start, "end": end,
        "takerOnly": "true" if taker_only else "false", "limit": PAGE_LIMIT})
    if not isinstance(r["body"], list):
        return None, False
    return len(r["body"]), len(r["body"]) >= PAGE_LIMIT


def test_7_taker_only_differential(results, markets):
    """Quantify what the takerOnly=true default silently drops (risk R4).

    The naive version of this test compares two full-history counts and reports
    'no difference' whenever both fill the page — which is exactly what happened
    on 19 and 20 Aug 2026 (true=1000, false=1000). Equal censored counts carry no
    information. This version shrinks the window until the larger count fits
    under the page cap, so the comparison is real.
    """
    print("[7/8] takerOnly true vs false — record-count differential (+ limit honouring)")
    entry = {"test": 7, "name": "taker_only_differential"}
    if not markets:
        entry["result"] = "SKIPPED — refuses to run unscoped; see test 8"
        log("SKIPPED — an unscoped run ignores start/end and hits the page cap, "
            "so the differential is uninformative. Supply a market.")
        results.append(entry)
        return

    market = markets[0]["condition_id"] if isinstance(markets[0], dict) else markets[0]

    # Is `limit` honoured above 100? Documentation says max 10000; verify.
    limit_probe = {}
    for lim in (100, 500, 1000):
        rp = get(f"{POLYMARKET_DATA_API}/trades",
                 params={"market": market, "start": 1, "end": PRE_WINDOW_END,
                         "takerOnly": "false", "limit": lim})
        limit_probe[str(lim)] = len(rp["body"]) if isinstance(rp["body"], list) else None
        time.sleep(0.25)

    # Halve the window from the market's newest trade backwards until the
    # takerOnly=false count fits under the page cap.
    start, end = 1, PRE_WINDOW_END
    span = end - start
    attempts = []
    n_false, censored = _count_trades(market, start, end, taker_only=False)
    while censored and len(attempts) < 12:
        attempts.append({"start": start, "end": end, "count": n_false, "censored": True})
        span = max(span // 2, 60)
        start = end - span
        n_false, censored = _count_trades(market, start, end, taker_only=False)
        time.sleep(0.25)
        if span <= 60:
            break
    n_true, true_censored = _count_trades(market, start, end, taker_only=True)

    entry.update({
        "market_used": market,
        "window_used": {"start": start, "end": end,
                        "start_iso": iso(start), "end_iso": iso(end),
                        "span_seconds": end - start},
        "window_shrink_attempts": attempts,
        "takerOnly_true_count": n_true,
        "takerOnly_false_count": n_false,
        "counts_censored": bool(censored or true_censored),
        "limit_probe_records_returned": limit_probe,
        "limit_honoured_above_100": (limit_probe.get("500") or 0) > 100,
        "page_limit_used": PAGE_LIMIT,
    })

    if n_true is None or n_false is None:
        entry["result"] = "FAIL — non-array response"
    elif censored or true_censored:
        entry["result"] = ("INCONCLUSIVE — still censored after window shrinking; "
                           "rerun against a lower-volume market")
    elif n_false > n_true:
        entry["differential"] = n_false - n_true
        entry["maker_side_share"] = round(1 - (n_true / n_false), 4) if n_false else None
        entry["result"] = "CONFIRMED BIAS RISK"
    else:
        entry["differential"] = n_false - n_true
        entry["result"] = "NO DIFFERENCE OBSERVED (uncensored window — genuinely no maker-side rows here)"
    log(f"{entry['result']} — true={n_true}, false={n_false}, "
        f"window={entry['window_used']['start_iso']}..{entry['window_used']['end_iso']}, "
        f"limit probe={limit_probe}")
    results.append(entry)


def test_8_scope_trap(results):
    """Are start/end honoured on an UNSCOPED /trades call?

    Observed 20 Aug 2026: an unscoped call with a 2024 window returned CURRENT
    trades, while the identical window with market= was honoured. If that holds,
    a collector that walks the global feed by time window silently returns
    today's data — no error, no empty array, no warning.
    """
    print("[8/8] Scope trap — are start/end honoured without user=/market=?")
    window = {"start": 1730000000, "end": 1730100000}  # 27-28 Oct 2024
    control_market = "0xdd22472e552920b8438158ea7238bfadfa4f736aa4cee91a6b86c39ead110917"

    unscoped = get(f"{POLYMARKET_DATA_API}/trades",
                   params={**window, "limit": 20, "takerOnly": "false"})
    scoped = get(f"{POLYMARKET_DATA_API}/trades",
                 params={**window, "market": control_market, "limit": 20, "takerOnly": "false"})
    su, ss = ts_summary(unscoped["body"]), ts_summary(scoped["body"])

    unscoped_ok = bool(su.get("max_ts")) and su["max_ts"] <= window["end"]
    scoped_ok = bool(ss.get("max_ts")) and ss["max_ts"] <= window["end"]

    entry = {
        "test": 8,
        "name": "start_end_scope_trap",
        "window": {**window, "start_iso": iso(window["start"]), "end_iso": iso(window["end"])},
        "unscoped": {"summary": su, "window_honoured": unscoped_ok, "status_code": unscoped["status_code"]},
        "market_scoped": {"summary": ss, "window_honoured": scoped_ok, "status_code": scoped["status_code"]},
    }
    if scoped_ok and not unscoped_ok:
        entry["result"] = "TRAP CONFIRMED — start/end ignored without user=/market="
        entry["consequence"] = (
            "Every historical collector call MUST carry user= or market=. Walking the global "
            "feed by time window silently returns current data. Record in the data dictionary "
            "and enforce in code review."
        )
    elif scoped_ok and unscoped_ok:
        entry["result"] = "NO TRAP — start/end honoured in both cases (behaviour has changed; update the docs)"
    else:
        entry["result"] = "FAIL — scoped control did not honour its own window; investigate before trusting test 6"
    log(entry["result"])
    results.append(entry)


def main():
    parser = argparse.ArgumentParser(description="WS4 API verification suite (PG-S2-55)")
    parser.add_argument("--market", nargs="*", default=[],
                        help="Polymarket condition ID(s) for tests 6 and 7; overrides --seeds")
    parser.add_argument("--seeds", default=None,
                        help="Seed markets JSON (default: config/seeds.json)")
    parser.add_argument("--out", default=None,
                        help="Output JSON path (default: data/external/feasibility_check_<date>.json)")
    args = parser.parse_args()

    seed_markets, probe_market = load_seeds(args.seeds, args.market)

    results = []
    print("=" * 70)
    print("WS4 API VERIFICATION SUITE — PG-S2-55")
    print(f"Run started: {datetime.now(timezone.utc).isoformat()}")
    print(f"Seed markets: {len(seed_markets)} | boundary probe: {probe_market or 'none'}")
    print("=" * 70)

    sample_wallet = test_1_polymarket_trades(results)
    if sample_wallet:
        print(f"  (using discovered wallet {sample_wallet} for tests 2-3)")
    test_2_polymarket_activity(results, sample_wallet)
    test_3_polymarket_closed_positions(results, sample_wallet)
    test_4_kalshi_trades_fields(results)
    test_5_kalshi_pagination_depth(results)
    test_6_v1_v2_continuity(results, seed_markets, probe_market)
    test_7_taker_only_differential(results, seed_markets)
    test_8_scope_trap(results)

    out_path = Path(args.out) if args.out else Path(
        f"data/external/feasibility_check_{datetime.now(timezone.utc).date().isoformat()}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    t6 = next((r for r in results if r.get("test") == 6), {})
    headline = "YES" if str(t6.get("result", "")).startswith("YES") else \
               "PARTIAL" if str(t6.get("result", "")).startswith("PARTIAL") else "NO_OR_SKIPPED"

    evidence = {
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "markets_tested": [m["condition_id"] if isinstance(m, dict) else m for m in seed_markets],
        "boundary_probe_market": probe_market,
        "headline_question": "Does the Data API return trade history predating the 28 Apr 2026 V1->V2 cutover?",
        "headline_answer": headline,
        "results": results,
    }
    out_path.write_text(json.dumps(evidence, indent=2, default=str))

    print("=" * 70)
    fails = [r for r in results if str(r.get("result", "")).startswith("FAIL")]
    print(f"Done. {len(results)} tests run, {len(fails)} FAIL. Evidence written to {out_path}")
    if fails:
        print("Triage each FAIL in writing before relying on the affected endpoint.")
    print(f"HEADLINE: pre-migration history reachable = {headline}")
    print("=" * 70)
    return 0 if headline == "YES" else 2


if __name__ == "__main__":
    sys.exit(main())
