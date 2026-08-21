"""
Offline tests for verify_apis.py — no network access required. Run with: pytest -q

The suite itself can only be evidenced by a live run (that is what
data/external/feasibility_check_<date>.json is for). What these tests protect is
the *reasoning* around it: the cutover constant, the pre-migration window, and
the summarisation that decides PASS from FAIL.

The window test is the important one. Before 20 Aug 2026 test 6 searched only the
30 days immediately before the cutover, which returns nothing for a seed market
that resolved earlier — the Nobel case among them — and would have reported "no
pre-migration history" on a false negative.
"""
import verify_apis as v


PRE = v.V2_CUTOVER_TS - 3600
POST = v.V2_CUTOVER_TS + 3600


def trade(ts, wallet="0xabc"):
    return {"proxyWallet": wallet, "timestamp": ts, "side": "BUY", "size": 1.0, "price": 0.5}


def test_cutover_constant_matches_documented_upgrade():
    # Guard against someone "tidying" this. 28 Apr 2026, 11:00 UTC.
    assert v.V2_CUTOVER_TS == 1777374000
    assert v.iso(v.V2_CUTOVER_TS) == "2026-04-28T11:00:00Z"


def test_pre_window_covers_all_retrievable_history():
    # Regression guard for the false-negative bug. The window must start at 1,
    # not at some fixed number of days before the cutover.
    assert v.PRE_WINDOW_START == 1
    assert v.PRE_WINDOW_END == v.V2_CUTOVER_TS - 1

    nobel_announcement = 1760091208      # 2025-10-10, a real seed-case trade
    trump_2024 = 1730906435              # 2024-11-06
    assert v.PRE_WINDOW_START <= nobel_announcement <= v.PRE_WINDOW_END
    assert v.PRE_WINDOW_START <= trump_2024 <= v.PRE_WINDOW_END


def test_iso_handles_none():
    assert v.iso(None) is None


def test_ts_summary_empty_array():
    s = v.ts_summary([])
    assert s["count"] == 0
    assert s["min_ts"] is None


def test_ts_summary_counts_each_side_of_the_cutover():
    s = v.ts_summary([trade(PRE), trade(PRE - 10), trade(POST)])
    assert s["count"] == 3
    assert s["pre_migration_records"] == 2
    assert s["post_migration_records"] == 1
    assert s["min_ts"] == PRE - 10
    assert s["max_ts"] == POST


def test_ts_summary_counts_distinct_wallets():
    s = v.ts_summary([trade(PRE, "0xa"), trade(PRE, "0xa"), trade(POST, "0xb")])
    assert s["distinct_wallets"] == 2


def test_ts_summary_handles_non_array_response():
    s = v.ts_summary({"error": "bad request"})
    assert s["count"] is None
    assert "not a JSON array" in s["note"]


def test_ts_summary_tolerates_missing_timestamps():
    s = v.ts_summary([{"proxyWallet": "0xa"}])
    assert s["count"] == 1
    assert s["min_ts"] is None


def test_load_seeds_cli_markets_override_the_file():
    markets, probe = v.load_seeds(None, ["0xdeadbeef"])
    assert markets == [{"condition_id": "0xdeadbeef", "category": "cli", "title": None}]
    assert probe is None


def test_load_seeds_reads_file_and_finds_boundary_probe(tmp_path):
    p = tmp_path / "seeds.json"
    p.write_text(
        '{"markets": [{"condition_id": "0x1", "category": "x"}],'
        ' "control_markets": [{"role": "boundary_probe", "condition_id": "0x9"}]}'
    )
    markets, probe = v.load_seeds(str(p), [])
    assert markets[0]["condition_id"] == "0x1"
    assert probe == "0x9"


def test_load_seeds_missing_file_is_not_fatal():
    markets, probe = v.load_seeds("no-such-file.json", [])
    assert markets == []
    assert probe is None


def test_shipped_seed_file_is_valid_and_covers_the_three_seed_cases():
    markets, probe = v.load_seeds(v.DEFAULT_SEEDS, [])
    categories = {m["category"] for m in markets}
    assert {"venezuela_maduro", "nobel_prize", "us_iran_ceasefire"} <= categories
    assert all(m["condition_id"].startswith("0x") for m in markets)
    assert probe and probe.startswith("0x")
