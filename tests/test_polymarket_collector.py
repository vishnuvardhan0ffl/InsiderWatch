"""
Offline smoke tests — no network access required. Run with: pytest -q

Two cache-key tests used to live here, against the collector's own
_cache_key(). The collector no longer has one: storage moved to
collectors/cache.py, and key construction is tested there, in
tests/test_cache.py, against the module that now does it.

What is tested here instead is the wiring — that the collector really does
go through the cache, and that a repeated collection therefore makes no
requests. That is the WS5 acceptance criterion, exercised through the
collector rather than asserted about it.

The fake API lives in tests/conftest.py, shared with every other test file.
Window-pagination behaviour is tests/test_trade_pagination.py; the recorded
fixtures are tests/test_fixtures.py.
"""

import json

import pytest

from collectors import polymarket
from collectors.cache import UnscopedRequestError, build_cache_key
from collectors.polymarket import TradeQuery

# ===========================================================================
# The acceptance criterion, exercised through the collector
# ===========================================================================

def test_collecting_the_same_window_twice_makes_no_second_request(installed_api):
    query = TradeQuery(market="0xabc", start=0, end=100, taker_only=False)

    first, _ = polymarket.collect_trades(query)
    calls_after_first = installed_api.network_calls
    second, _ = polymarket.collect_trades(query)

    assert first == second
    assert calls_after_first > 0                        # it really did collect
    assert installed_api.network_calls == calls_after_first    # and then it did not


def test_the_response_is_stored_as_bytes_with_a_retrieval_timestamp(installed_api):
    query = TradeQuery(market="0xabc", start=0, end=100, taker_only=False)
    polymarket.collect_trades(query)

    index = (installed_api.cache.cache_dir / "index.jsonl").read_text().strip().splitlines()
    meta = json.loads(index[0])

    assert meta["endpoint"] == "/trades"
    assert meta["retrieved_at"].endswith("+00:00")      # UTC, stated explicitly
    assert len(meta["body_sha256"]) == 64               # verifiable later
    assert ["takerOnly", "false"] in meta["params"]     # the setting is recorded


def test_an_unscoped_query_is_refused_before_anything_is_sent(installed_api):
    """WS4 test 8: with no user and no market, start/end are ignored."""
    query = TradeQuery(start=0, end=100, taker_only=False)

    with pytest.raises((UnscopedRequestError, ValueError)):
        polymarket.collect_trades(query)


def test_taker_only_reaches_the_api_as_a_lowercase_string(installed_api):
    """Python would send "False"; the API wants "false"."""
    polymarket.collect_trades(
        TradeQuery(market="0xabc", start=0, end=100, taker_only=False)
    )

    _, params_sent = installed_api.session.calls[0]
    assert ("takerOnly", "false") in params_sent


def test_cache_keys_stay_deterministic_and_parameter_sensitive():
    """The property the old collector-level tests checked, at its new home."""
    assert build_cache_key("/trades", {"limit": 5, "takerOnly": "true"}) == \
           build_cache_key("/trades", {"limit": 5, "takerOnly": "true"})

    assert build_cache_key("/trades", {"limit": 5}) != \
           build_cache_key("/trades", {"limit": 10})


# ===========================================================================
# Unchanged from before the caching retrofit
# ===========================================================================

def test_trade_query_requires_explicit_taker_only():

    # No explicit takerOnly choice has been made yet
    q = TradeQuery(
        market="0xabc",
        start=0,
        end=100
    )

    assert q.taker_only is None


    # Explicitly include maker and taker trades
    q2 = TradeQuery(
        market="0xabc",
        start=0,
        end=100,
        taker_only=False
    )

    assert q2.taker_only is False


    # Explicitly request taker-only trades
    q3 = TradeQuery(
        market="0xabc",
        start=0,
        end=100,
        taker_only=True
    )

    assert q3.taker_only is True
