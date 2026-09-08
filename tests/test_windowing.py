"""
tests/test_windowing.py

SCRUM-45 acceptance criterion:
    "Offset cap of 5,000 on activity handled by time windowing"

Runs offline against a synthetic API. Proves that a wallet with
more activity than the offset cap is collected completely, with
no loss and no duplication.

Run from the repository root:
    python tests/test_windowing.py
"""

import pathlib
import random
import sys

sys.path.insert(
    0,
    str(pathlib.Path(__file__).resolve().parents[1])
)

import collectors.polymarket_activity as act


# ============================================================
# Synthetic wallet: 12,000 events over 30 days
# ============================================================

random.seed(7)

T0 = 1_700_000_000

N = 12_000

EVENTS = []

for i in range(N):

    EVENTS.append({
        "proxyWallet": "0xtest",
        "timestamp": T0 + int(i * (30 * 86400) / N),
        "type": "DEPOSIT" if i % 1500 == 0 else "TRADE",
        "usdcSize": round(random.random() * 10, 4),
        "transactionHash": f"0x{i:064x}",
    })

EVENTS.sort(
    key=lambda r: r["timestamp"]
)


# ============================================================
# Fake API
# ============================================================

def fake_get(
    endpoint,
    params,
    use_cache=True,
    retries=5
):

    assert endpoint == "/activity"

    # Collector must not rely on API defaults.
    assert params["sortDirection"] == "ASC"
    assert params["excludeDepositsWithdrawals"] == "false"

    # Feasibility test 8: unscoped calls ignore start/end.
    assert "user" in params, \
        "scope trap: user= must always be present"

    s = params["start"]
    e = params["end"]
    off = params["offset"]
    lim = params["limit"]

    window = [
        r
        for r in EVENTS
        if s <= r["timestamp"] <= e
    ]

    return window[off:off + lim]


act._get = fake_get


# ============================================================
# Collect
# ============================================================

query = act.ActivityQuery(
    user="0xtest",
    start=1,
    end=T0 + 31 * 86400
)

# One oversized window on purpose, to force the cap.
rows, meta = act.collect_activity(
    query,
    window_s=30 * 86400
)

print("collected      :", len(rows))
print("expected       :", N)
print("splits         :", meta["window_split_count"])
print("requests       :", meta["request_count"])
print("duplicates     :", meta["duplicates_removed"])
print("types          :", meta["types_observed"])
print("funding types  :", meta["funding_types_observed"])
print()

assert len(rows) == N, \
    f"DATA LOSS: got {len(rows)} of {N}"

assert meta["window_split_count"] > 0, \
    "cap never triggered - test is not exercising the split"

assert rows == sorted(
    rows,
    key=lambda r: r["timestamp"]
), "records not ascending by timestamp"


# ============================================================
# Derivations
# ============================================================

first = act.derive_first_activity_timestamp(rows)

print("first activity :", first,
      "| expected:", EVENTS[0]["timestamp"])

assert first == EVENTS[0]["timestamp"], \
    "first-activity timestamp is wrong"

fund = act.derive_funding_events(rows)

print("funding events :", fund["event_count"],
      "| deposits:", fund["deposit_count"])

print("total deposited:", fund["total_deposited"])
print("mapping conf.  :", fund["field_mapping_confirmed"])

assert fund["event_count"] == 8

print()
print("ALL WINDOWING ASSERTIONS PASSED")
