"""
The recorded fixtures, and the rules they have to keep obeying.

Two different jobs in one file, deliberately:

  1. Collectors work against real recorded responses, not invented ones. If
     the API's shape and ours ever disagree, these fail.
  2. The fixtures themselves stay honest - anonymised, and every one of them
     documented in MANIFEST.json.

The second job is the one that will still be earning its keep in November.
A fixture nobody can trace is a test asserting something nobody can explain.
"""

import json

import pytest

from collectors import polymarket
from collectors.cache import CacheMiss
from processing.anonymise import PROFILE_FIELDS, find_identifying_fields

from tests.conftest import FIXTURE_DIR, ReplaySession, load_fixture

RECORDED_ENDPOINTS = [
    ("trades.json", "/trades"),
    ("trades_maduro.json", "/trades"),
    ("activity.json", "/activity"),
    ("positions.json", "/positions"),
    ("closed_positions.json", "/closed-positions"),
]


# ===========================================================================
# The collectors, against real recorded responses
# ===========================================================================

@pytest.mark.session("fixtures")
def test_the_trade_collector_reads_a_recorded_response(installed_api):
    query = polymarket.TradeQuery(
        market="0xd1e4e03a", start=1787241000, end=1787241999, taker_only=False
    )

    trades, metadata = polymarket.collect_trades(query)

    assert len(trades) == len(load_fixture("trades.json"))
    assert metadata["takerOnly"] is False
    assert all("price" in row and "size" in row for row in trades)


@pytest.mark.session("fixtures")
def test_the_activity_collector_reads_a_recorded_response(installed_api):
    activity = list(polymarket.fetch_activity("0xabc"))

    assert activity == load_fixture("activity.json")
    assert {row["type"] for row in activity} <= {"TRADE", "REDEEM", "SPLIT",
                                                 "MERGE", "REWARD", "CONVERSION",
                                                 "DEPOSIT", "WITHDRAWAL"}


@pytest.mark.session("fixtures")
def test_closed_positions_carry_the_profitability_fields(installed_api):
    positions = list(polymarket.fetch_closed_positions("0xabc"))

    assert positions
    for row in positions:
        assert "realizedPnl" in row      # feeds the profitability features
        assert "avgPrice" in row         # feeds "unusual confidence"


def test_positions_is_reachable_but_has_no_collector_yet(fixture_api):
    """/positions has a fixture and no collector. That is a gap, not an oversight.

    The fixture is marked unverified in MANIFEST.json because nobody has called
    the endpoint yet. When someone writes fetch_positions(), record a real
    response first and this test should grow teeth.
    """

    rows = fixture_api.get_json("/positions", {"user": "0xabc"})

    documented = {"size", "avgPrice", "currentValue", "cashPnl",
                  "percentPnl", "curPrice", "redeemable", "conditionId"}
    assert documented <= set(rows[0])

    assert not hasattr(polymarket, "fetch_positions")


# ===========================================================================
# The error response
# ===========================================================================

def test_a_rate_limited_response_is_raised_and_never_cached(make_api):
    """A cached 429 would be served as data for the rest of the project."""

    error = load_fixture("error_429.json")
    api = make_api(ReplaySession((error["body"].encode(), error["status_code"])))

    params = {"market": "0xabc", "takerOnly": False}

    with pytest.raises(RuntimeError):
        api.get_json("/trades", params)

    assert not api.cache.has("/trades", params)


def test_a_failed_request_leaves_nothing_to_replay_offline(make_api, cache_dir):
    """The follow-on: after a failure there is genuinely nothing on disk."""

    error = load_fixture("error_429.json")
    api = make_api(ReplaySession((error["body"].encode(), error["status_code"])))
    params = {"market": "0xabc", "takerOnly": False}

    with pytest.raises(RuntimeError):
        api.get_json("/trades", params)

    offline = make_api(session=None, offline=True)
    with pytest.raises(CacheMiss):
        offline.get_json("/trades", params)


# ===========================================================================
# The fixtures stay honest
# ===========================================================================

@pytest.mark.parametrize("name,endpoint", RECORDED_ENDPOINTS)
def test_no_fixture_carries_identifying_profile_data(name, endpoint):
    """The ethics protocol, enforced rather than promised.

    The API returns name, pseudonym, bio and profileImage on every trade. Our
    protocol says those are never published. This repository is public, so a
    fixture recorded without scrubbing would publish them.
    """

    records = load_fixture(name)

    assert find_identifying_fields(records) == {}
    for row in records:
        assert not (set(row) & set(PROFILE_FIELDS))


def test_every_fixture_is_documented_and_every_entry_exists():
    """No undocumented fixtures, no entries for files that are gone."""

    manifest = load_fixture("MANIFEST.json")["fixtures"]

    on_disk = {
        path.name for path in FIXTURE_DIR.iterdir()
        if path.suffix == ".json" and path.name != "MANIFEST.json"
    }

    assert on_disk == set(manifest), (
        "MANIFEST.json and tests/fixtures/ disagree. Add the fixture to the "
        "manifest, with where it came from."
    )


@pytest.mark.parametrize("name", [n for n, _ in RECORDED_ENDPOINTS])
def test_each_manifest_entry_says_where_it_came_from(name):
    entry = load_fixture("MANIFEST.json")["fixtures"][name]

    assert entry["status"] in ("observed", "unverified")
    assert entry["source"]
    assert entry["notes"]

    # An observed fixture is citable, so it must carry a recording date and
    # the record count must actually match the file.
    if entry["status"] == "observed":
        assert entry["recorded"]
        assert entry["records"] == len(load_fixture(name))


def test_fixtures_are_valid_json_and_not_empty():
    for path in sorted(FIXTURE_DIR.glob("*.json")):
        content = json.loads(path.read_text())
        assert content, "{} is empty".format(path.name)


# ===========================================================================
# The guard that makes "offline" true rather than hopeful
# ===========================================================================

def test_reaching_the_real_network_fails_loudly():
    """Proves block_network in conftest.py is actually doing something."""

    import socket

    from tests.conftest import NetworkAccessDenied

    with pytest.raises(NetworkAccessDenied):
        socket.socket().connect(("data-api.polymarket.com", 443))
