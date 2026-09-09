"""
Activity collection by time window (SCRUM-45).

Acceptance criterion:
    "Offset cap of 5,000 on activity handled by time windowing"

/activity refuses to page past offset 5,000. A wallet with more history than
that cannot be collected by offset alone, so the collector walks time windows
and splits a window in half whenever it hits the cap. If that goes wrong the
result is not an error - it is a wallet whose history stops early and whose
age looks perfectly plausible.

Offline, against a synthetic wallet with 12,000 events. The window is
deliberately set wide enough to force the cap.
"""

import random

import pytest

import collectors.polymarket_activity as act

T0 = 1_700_000_000
EVENT_COUNT = 12_000
EVERY_NTH_IS_FUNDING = 1500


def _synthetic_wallet():
    """12,000 events spread evenly over 30 days, oldest first."""

    rng = random.Random(7)

    events = [
        {
            "proxyWallet": "0xtest",
            "timestamp": T0 + int(i * (30 * 86400) / EVENT_COUNT),
            "type": "DEPOSIT" if i % EVERY_NTH_IS_FUNDING == 0 else "TRADE",
            "usdcSize": round(rng.random() * 10, 4),
            "transactionHash": "0x{:064x}".format(i),
        }
        for i in range(EVENT_COUNT)
    ]

    events.sort(key=lambda row: row["timestamp"])
    return events


EVENTS = _synthetic_wallet()


@pytest.fixture
def fake_api(monkeypatch):
    """Serve EVENTS through a stand-in for _get, and check what was asked for.

    monkeypatch puts the real _get back after the test. The previous version
    of this file assigned to act._get at import time, which left the collector
    permanently patched for every other test in the suite.
    """

    calls = []

    def fake_get(endpoint, params, use_cache=True, retries=5):
        calls.append(params)

        assert endpoint == "/activity"

        # The collector must not lean on API defaults.
        assert params["sortDirection"] == "ASC"
        assert params["excludeDepositsWithdrawals"] == "false"

        # WS4 test 8: an unscoped call ignores start and end.
        assert "user" in params, "scope trap: user= must always be present"

        window = [
            row for row in EVENTS
            if params["start"] <= row["timestamp"] <= params["end"]
        ]
        return window[params["offset"]:params["offset"] + params["limit"]]

    monkeypatch.setattr(act, "_get", fake_get)
    return calls


@pytest.fixture
def collected(fake_api):
    """One collection over a 30-day window - wide enough to hit the cap."""

    query = act.ActivityQuery(
        user="0xtest", start=1, end=T0 + 31 * 86400
    )
    return act.collect_activity(query, window_s=30 * 86400)


# ===========================================================================
# The acceptance criterion
# ===========================================================================

def test_no_records_are_lost_when_the_offset_cap_is_hit(collected):
    rows, _ = collected

    assert len(rows) == EVENT_COUNT


def test_the_window_really_did_have_to_split(collected):
    """Otherwise this file proves nothing - the cap was never reached."""

    _, meta = collected

    assert meta["window_split_count"] > 0


def test_no_duplicates_are_introduced_by_splitting(collected):
    rows, meta = collected

    hashes = [row["transactionHash"] for row in rows]
    assert len(set(hashes)) == len(hashes)
    assert meta["duplicates_removed"] == 0


def test_records_come_back_in_time_order(collected):
    """Downstream features assume ascending time; splitting must not shuffle."""

    rows, _ = collected

    assert rows == sorted(rows, key=lambda row: row["timestamp"])


# ===========================================================================
# The features this unlocks
# ===========================================================================

def test_the_first_activity_timestamp_is_the_oldest_record(collected):
    """Wallet age. Truncated collection would make this wrong and plausible."""

    rows, _ = collected

    assert act.derive_first_activity_timestamp(rows) == EVENTS[0]["timestamp"]


def test_funding_events_are_picked_out_of_the_history(collected):
    rows, _ = collected

    funding = act.derive_funding_events(rows)

    assert funding["event_count"] == EVENT_COUNT // EVERY_NTH_IS_FUNDING
    assert funding["deposit_count"] == funding["event_count"]
    assert funding["field_mapping_confirmed"]


def test_full_history_is_requested_not_the_default_window(fake_api, collected):
    """start=1 asks for everything; the API's default is about three years."""

    assert all(params["start"] >= 1 for params in fake_api)
    assert fake_api[0]["start"] == 1


# ===========================================================================
# The cost of asking for all of history
# ===========================================================================

def test_the_default_does_not_walk_empty_years_one_week_at_a_time(fake_api):
    """The first live run cost 2,969 requests for one wallet.

    2,945 of them returned nothing and 2,934 were spent on empty weeks
    between 1970 and the wallet's first activity, because start=1 with a
    7-day window means walking 56 years a week at a time. The control cohort
    budget assumed a handful of requests per wallet; at that rate 1,000
    wallets would be about three million requests instead of three thousand.

    Leaving window_s unset starts with one window and lets the offset-cap
    split decide the size from the data.
    """

    query = act.ActivityQuery(user="0xtest", start=1, end=T0 + 31 * 86400)

    rows, meta = act.collect_activity(query)                  # no window_s
    _, fixed_windows = act.collect_activity(query, window_s=7 * 86400)

    assert len(rows) == EVENT_COUNT                           # still complete
    assert meta["window_split_count"] > 0                     # cap still handled

    # An order of magnitude fewer requests for the same records.
    assert meta["request_count"] < fixed_windows["request_count"] / 10

    # And almost none of them wasted on stretches of time with no activity.
    empty = sum(1 for entry in meta["request_log"]
                if entry.get("records_received") == 0)
    assert empty / meta["request_count"] < 0.1
