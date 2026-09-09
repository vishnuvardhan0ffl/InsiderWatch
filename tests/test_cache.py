"""
Tests for the raw response cache.

These run offline. Instead of a real requests.Session we pass in ReplaySession
from tests/conftest.py, which records every call it is given. That is how we
prove the cache works: we do not assume the second collection was fast, we
assert that no request was made at all.

The tests are grouped under the three acceptance criteria from the Jira story,
plus the safety guards. If you are reading this module to learn the codebase,
read the tests in order - they are roughly a tour of what the cache promises.
"""

import json
from pathlib import Path

import pytest

from tests.conftest import ReplaySession

from collectors.cache import (
    CACHE_DIR_ENV_VAR,
    CachedClient,
    CacheMiss,
    ResponseCache,
    UnscopedRequestError,
    build_cache_key,
    resolve_cache_dir,
    tidy_params,
)

# A stand-in for a real API response body. Deliberately not pretty-printed:
# we want to prove we store exactly what arrives, spacing and all.
FAKE_TRADES = b'[{"proxyWallet":"0x07d126ea","side":"BUY","size":1200,"price":0.34}]'


@pytest.fixture
def api(make_api):
    """A client writing to a throwaway directory, talking to a fake API.

    make_api and ReplaySession come from tests/conftest.py, so every test file
    fakes the API the same way. The cache lands in a temp folder that pytest
    deletes afterwards, so tests never touch the real data/raw/.
    """
    return make_api(ReplaySession(FAKE_TRADES))


# ===========================================================================
# Criterion 1: re-running an identical collection performs zero network calls
# ===========================================================================

def test_the_same_request_twice_only_hits_the_api_once(api):
    params = {"market": "0xd1e4e03a", "takerOnly": False, "limit": 500}

    first = api.get_json("/trades", params)
    second = api.get_json("/trades", params)

    assert api.network_calls == 1
    assert second == first


def test_parameter_order_does_not_matter(api):
    """Two dicts with the same contents in a different order are one request."""
    api.get_json("/trades", {"market": "0xd1e4e03a", "takerOnly": False})
    api.get_json("/trades", {"takerOnly": False, "market": "0xd1e4e03a"})

    assert api.network_calls == 1


def test_changing_takeronly_is_a_different_request(api):
    """takerOnly true and false must not share a cache entry.

    They return different data, and comparing the two is exactly how we measure
    the maker-side bias that risk R4 is about.
    """
    api.get_json("/trades", {"market": "0xd1e4e03a", "takerOnly": True})
    api.get_json("/trades", {"market": "0xd1e4e03a", "takerOnly": False})

    assert api.network_calls == 2


def test_refresh_downloads_again_on_purpose(api):
    params = {"market": "0xd1e4e03a", "takerOnly": False}

    api.get_json("/trades", params)
    api.get_json("/trades", params, refresh=True)

    assert api.network_calls == 2


def test_an_offline_client_replays_the_cache_and_never_goes_online(tmp_path):
    """This is the mode the M2 demo and all frozen-dataset analysis run in."""
    params = {"market": "0xd1e4e03a", "takerOnly": False}

    collector = CachedClient("https://api", ResponseCache(tmp_path), ReplaySession(FAKE_TRADES))
    collected = collector.get_json("/trades", params)

    # No session at all, so there is nothing that could reach the network.
    replay = CachedClient("https://api", ResponseCache(tmp_path), offline=True)
    assert replay.get_json("/trades", params) == collected

    # Anything not collected is an error, not a silent trip to the API.
    with pytest.raises(CacheMiss):
        replay.get_json("/trades", {"market": "0xnever-collected"})


# ===========================================================================
# Criterion 2: raw responses retained unmodified, with a retrieval timestamp
# ===========================================================================

def test_the_saved_file_is_exactly_what_the_api_sent(api):
    params = {"market": "0xd1e4e03a", "takerOnly": False}
    api.get_json("/trades", params)

    body_path, _ = api.cache.paths_for("/trades", params)
    assert body_path.read_bytes() == FAKE_TRADES


def test_the_metadata_says_where_it_came_from_and_when(api):
    params = {"market": "0xd1e4e03a", "takerOnly": False, "start": 1}
    response = api.get("/trades", params)

    _, meta_path = api.cache.paths_for("/trades", params)
    meta = json.loads(meta_path.read_text())

    assert meta["retrieved_at"] == response.retrieved_at
    assert meta["retrieved_at"].endswith("+00:00")     # UTC, stated explicitly
    assert meta["status_code"] == 200
    assert ["takerOnly", "false"] in meta["params"]    # the setting is recorded
    assert meta["body_bytes"] == len(FAKE_TRADES)
    assert len(meta["body_sha256"]) == 64              # verifiable later


def test_every_saved_response_adds_a_line_to_the_index(api):
    api.get_json("/trades", {"market": "0xaaa", "takerOnly": False})
    api.get_json("/trades", {"market": "0xbbb", "takerOnly": False})

    index = (api.cache.cache_dir / "index.jsonl").read_text().strip().splitlines()

    assert len(index) == 2
    assert json.loads(index[0])["endpoint"] == "/trades"


def test_failed_requests_are_not_saved(tmp_path):
    """A cached 429 would be replayed forever as if it were data."""
    api = CachedClient("https://api", ResponseCache(tmp_path),
                       ReplaySession((b"rate limited", 429)))

    with pytest.raises(RuntimeError):
        api.get_json("/trades", {"market": "0xd1e4e03a"})

    assert not api.cache.has("/trades", {"market": "0xd1e4e03a"})


def test_an_interrupted_write_counts_as_not_collected(api):
    """Both files must exist, so a half-finished save is re-downloaded."""
    params = {"market": "0xd1e4e03a"}
    api.get_json("/trades", params)

    _, meta_path = api.cache.paths_for("/trades", params)
    meta_path.unlink()

    assert api.cache.read("/trades", params) is None


# ===========================================================================
# Criterion 3: cache location is configurable
# ===========================================================================

def test_where_the_cache_lives_argument_beats_env_beats_default(tmp_path, monkeypatch):
    monkeypatch.delenv(CACHE_DIR_ENV_VAR, raising=False)
    assert resolve_cache_dir() == Path("data/raw")

    monkeypatch.setenv(CACHE_DIR_ENV_VAR, str(tmp_path / "from_env"))
    assert resolve_cache_dir() == tmp_path / "from_env"

    assert resolve_cache_dir(tmp_path / "explicit") == tmp_path / "explicit"


def test_two_caches_in_two_places_stay_separate(tmp_path):
    params = {"market": "0xd1e4e03a"}

    first = CachedClient("https://api", ResponseCache(tmp_path / "a"), ReplaySession(FAKE_TRADES))
    second = CachedClient("https://api", ResponseCache(tmp_path / "b"), ReplaySession(FAKE_TRADES))

    first.get_json("/trades", params)

    assert second.cache.read("/trades", params) is None


# ===========================================================================
# The scoping guard (WS4 test 8)
# ===========================================================================

def test_an_unscoped_trades_call_is_refused_before_anything_is_sent(api):
    with pytest.raises(UnscopedRequestError):
        api.get_json("/trades", {"start": 1730000000, "end": 1730100000})

    assert api.session.calls == []


@pytest.mark.parametrize("scope", ["user", "market", "eventId"])
def test_any_one_scoping_parameter_is_enough(api, scope):
    api.get_json("/trades", {scope: "0xd1e4e03a", "start": 1})
    assert api.network_calls == 1


def test_endpoints_without_the_trap_are_left_alone(api):
    """Gamma market metadata has no scope requirement, so do not invent one."""
    api.get_json("/markets", {"limit": 100})
    assert api.network_calls == 1


# ===========================================================================
# Parameter tidying
# ===========================================================================

def test_booleans_are_sent_lowercase(api):
    """Python would send "False"; the API wants "false"."""
    api.get_json("/trades", {"market": "0xd1e4e03a", "takerOnly": False})

    _, params_sent = api.session.calls[0]
    assert ("takerOnly", "false") in params_sent


def test_parameters_set_to_none_are_ignored():
    assert tidy_params({"market": "0xa", "side": None}) == [("market", "0xa")]

    assert build_cache_key("/trades", {"market": "0xa"}) == \
           build_cache_key("/trades", {"market": "0xa", "side": None})


def test_lists_become_comma_separated():
    assert tidy_params({"market": ["0xa", "0xb"]}) == [("market", "0xa,0xb")]


def test_spelling_the_endpoint_differently_does_not_split_the_cache():
    assert build_cache_key("trades", {"market": "0xa"}) == \
           build_cache_key("/trades/", {"market": "0xa"})
