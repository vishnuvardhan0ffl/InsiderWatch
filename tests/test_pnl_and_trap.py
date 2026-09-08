"""
tests/test_pnl_and_trap.py

SCRUM-45 acceptance criterion:
    "realised PnL per closed position"

Runs the PnL derivation against the REAL /closed-positions
payload captured in the 2026-08-20 feasibility check, and
verifies the two guards that protect against the start/end
scope trap confirmed by feasibility test 8.

Run from the repository root:
    python tests/test_pnl_and_trap.py
"""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

sys.path.insert(
    0,
    str(ROOT)
)

import collectors.polymarket_activity as act


FEASIBILITY = (
    ROOT
    / "data"
    / "external"
    / "feasibility_check_2026-08-20.json"
)


# ============================================================
# Realised PnL against real captured data
# ============================================================

d = json.loads(
    FEASIBILITY.read_text(encoding="utf-8")
)

# results[2] is test 3, polymarket_closed_positions_fields
closed = d["results"][2]["body"]

pnl = act.derive_realised_pnl(closed)

print("positions      :", pnl["position_count"])
print("missing pnl    :", pnl["positions_missing_pnl"])
print("total realised :", round(pnl["total_realised_pnl"], 4))
print("winners/losers :",
      pnl["winning_positions"], "/", pnl["losing_positions"])

assert pnl["position_count"] > 0, \
    "no closed positions found in feasibility payload"

assert pnl["positions_missing_pnl"] == 0, \
    "realizedPnl missing on real data"

print()


# ============================================================
# Scope-trap guard
#
# Feasibility test 8 proved the API silently ignores
# start/end on unscoped calls and returns current data with
# a 200. If that ever happens on an activity call, the
# collector must fail loudly rather than record a wrong
# wallet age.
# ============================================================

def trap_get(
    endpoint,
    params,
    use_cache=True,
    retries=5
):
    # Deliberately return a current-time record regardless of
    # the requested window.
    return [{
        "proxyWallet": "0xtest",
        "timestamp": 1787241468,
        "type": "TRADE"
    }]


act._get = trap_get

query = act.ActivityQuery(
    user="0xtest",
    start=1,
    end=1730100000
)

try:

    act.collect_activity(
        query,
        window_s=86400
    )

    raise AssertionError(
        "FAIL: out-of-window records were accepted"
    )

except RuntimeError as exc:

    print("scope-trap guard fired:", str(exc)[:110])


# ============================================================
# Unscoped queries rejected outright
# ============================================================

try:

    act._validate_activity_query(
        act.ActivityQuery(
            user="",
            start=1,
            end=2
        )
    )

    raise AssertionError(
        "FAIL: unscoped query was accepted"
    )

except ValueError as exc:

    print("unscoped rejected     :", str(exc)[:90])


print()
print("ALL PNL + TRAP ASSERTIONS PASSED")
