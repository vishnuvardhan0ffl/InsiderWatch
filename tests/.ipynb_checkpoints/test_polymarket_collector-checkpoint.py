"""
Offline smoke tests — no network access required. Run with: pytest -q

These only check the parts of the collector that don't need a live API
(cache-key determinism, explicit-takerOnly enforcement in TradeQuery).
Fixture-backed tests against recorded API responses belong in Sprint 2's
"Set up the test harness and recorded fixtures" story.
"""

from collectors.polymarket import TradeQuery, _cache_key


def test_cache_key_is_deterministic():
    params = {
        "limit": 5,
        "takerOnly": "true"
    }

    key_a = _cache_key("/trades", params)
    key_b = _cache_key("/trades", params)

    assert key_a == key_b


def test_cache_key_differs_by_params():
    key_a = _cache_key(
        "/trades",
        {"limit": 5}
    )

    key_b = _cache_key(
        "/trades",
        {"limit": 10}
    )

    assert key_a != key_b


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