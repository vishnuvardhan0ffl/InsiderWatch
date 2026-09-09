"""
Realised P&L, and the guard against the scope trap (SCRUM-45).

Acceptance criterion:
    "realised PnL per closed position"

The P&L half runs against the REAL /closed-positions payload captured in the
2026-08-20 feasibility check, so it checks our derivation against bytes the
API actually returned rather than against something we invented.

The trap half is the more important one. WS4 test 8 proved that an unscoped
call returns *current* data with a 200 and no error, silently ignoring start
and end. If that ever happens on an activity call, the collector has to fail
loudly - a wallet age quietly computed from today's data would be wrong in a
way nothing downstream could detect.
"""

import json
import pathlib

import pytest

import collectors.polymarket_activity as act

FEASIBILITY = (
    pathlib.Path(__file__).resolve().parents[1]
    / "data" / "external" / "feasibility_check_2026-08-20.json"
)


@pytest.fixture
def real_closed_positions():
    """results[2] is test 3, polymarket_closed_positions_fields."""

    evidence = json.loads(FEASIBILITY.read_text(encoding="utf-8"))
    return evidence["results"][2]["body"]


# ===========================================================================
# Realised P&L, against real captured data
# ===========================================================================

def test_pnl_is_derived_for_every_real_closed_position(real_closed_positions):
    pnl = act.derive_realised_pnl(real_closed_positions)

    assert pnl["position_count"] > 0
    assert pnl["positions_missing_pnl"] == 0


def test_winners_and_losers_add_up(real_closed_positions):
    pnl = act.derive_realised_pnl(real_closed_positions)

    assert pnl["winning_positions"] + pnl["losing_positions"] <= pnl["position_count"]
    assert isinstance(pnl["total_realised_pnl"], float)


def test_an_empty_wallet_is_not_an_error():
    """An empty array means no closed positions, not missing history
    (docs/data_dictionary.md). Common for wallets whose bets resolved worthless."""

    pnl = act.derive_realised_pnl([])

    assert pnl["position_count"] == 0
    assert pnl["positions_missing_pnl"] == 0


# ===========================================================================
# The scope trap (WS4 test 8)
# ===========================================================================

def test_records_outside_the_requested_window_are_refused(monkeypatch):
    """The collector must not quietly accept today's data for an old window."""

    def returns_current_data_regardless(endpoint, params, use_cache=True, retries=5):
        return [{
            "proxyWallet": "0xtest",
            "timestamp": 1787241468,        # now, not the window asked for
            "type": "TRADE",
        }]

    monkeypatch.setattr(act, "_get", returns_current_data_regardless)

    query = act.ActivityQuery(user="0xtest", start=1, end=1730100000)

    with pytest.raises(RuntimeError):
        act.collect_activity(query, window_s=86400)


def test_a_query_with_no_wallet_is_rejected_before_any_request():
    """Unscoped means start and end are ignored, so there is nothing to salvage."""

    with pytest.raises(ValueError):
        act._validate_activity_query(act.ActivityQuery(user="", start=1, end=2))
