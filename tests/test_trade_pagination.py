"""
Tests for Polymarket time-window pagination.

Run from the repository root:

    pytest -q
"""

import collectors.polymarket as polymarket


def _make_trade(i):

    return {
        "transactionHash": f"0x{i:064x}",
        "proxyWallet": f"wallet_{i % 100}",
        "asset": f"asset_{i % 2}",
        "conditionId": "0xtestmarket",
        "size": 1.0,
        "price": 0.5,
        "timestamp": i,
        "side": "BUY"
    }


def test_more_than_10000_trades_without_loss(
    monkeypatch
):
    """
    Simulate a market containing 12,050 trades.

    The first large time window will exceed the 10,000
    offset ceiling, forcing the collector to split the
    window.

    The collector must still return every record.
    """

    fake_trades = [
        _make_trade(i)
        for i in range(12050)
    ]

    def fake_get(
        endpoint,
        params,
        use_cache=True,
        retries=5
    ):

        assert endpoint == "/trades"

        start = params["start"]

        end = params["end"]

        offset = params["offset"]

        limit = params["limit"]

        # Verify takerOnly was explicitly supplied.
        assert "takerOnly" in params

        matching = [
            row
            for row in fake_trades
            if start
            <= row["timestamp"]
            <= end
        ]

        return matching[
            offset:
            offset + limit
        ]

    monkeypatch.setattr(
        polymarket,
        "_get",
        fake_get
    )

    query = polymarket.TradeQuery(
        market="0xtestmarket",
        start=0,
        end=12049,
        taker_only=False
    )

    trades, metadata = (
        polymarket.collect_trades(
            query,
            window_s=20000
        )
    )

    # Acceptance criterion 1
    assert len(trades) > 10000

    assert len(trades) == 12050

    # No records lost
    timestamps = {
        row["timestamp"]
        for row in trades
    }

    assert timestamps == set(
        range(12050)
    )

    # Window splitting actually happened
    assert (
        metadata["window_split_count"]
        >= 1
    )


def test_taker_only_recorded_in_metadata(
    monkeypatch
):

    def fake_get(
        endpoint,
        params,
        use_cache=True,
        retries=5
    ):

        return []

    monkeypatch.setattr(
        polymarket,
        "_get",
        fake_get
    )

    query = polymarket.TradeQuery(
        market="0xtestmarket",
        start=0,
        end=100,
        taker_only=False
    )

    trades, metadata = (
        polymarket.collect_trades(
            query
        )
    )

    # Acceptance criterion 2
    assert (
        metadata["takerOnly"]
        is False
    )


def test_taker_only_must_be_explicit():

    query = polymarket.TradeQuery(
        market="0xtestmarket",
        start=0,
        end=100
    )

    try:

        polymarket.collect_trades(
            query
        )

        assert False

    except ValueError as error:

        assert (
            "taker_only"
            in str(error)
        )


def test_duplicate_detection(
    monkeypatch
):
    """
    Return an intentional duplicate and verify that
    only one copy survives.
    """

    trade_a = _make_trade(1)

    trade_b = _make_trade(2)

    responses = {

        0: [
            trade_a,
            trade_a,
            trade_b
        ]
    }

    def fake_get(
        endpoint,
        params,
        use_cache=True,
        retries=5
    ):

        return responses.get(
            params["offset"],
            []
        )

    monkeypatch.setattr(
        polymarket,
        "_get",
        fake_get
    )

    query = polymarket.TradeQuery(
        market="0xtestmarket",
        start=0,
        end=10,
        taker_only=False
    )

    trades, metadata = (
        polymarket.collect_trades(
            query
        )
    )

    assert len(trades) == 2

    assert (
        metadata[
            "duplicates_removed"
        ]
        == 1
    )


def test_no_duplicates_after_large_collection(
    monkeypatch
):

    fake_trades = [
        _make_trade(i)
        for i in range(12050)
    ]

    def fake_get(
        endpoint,
        params,
        use_cache=True,
        retries=5
    ):

        matching = [
            row
            for row in fake_trades
            if params["start"]
            <= row["timestamp"]
            <= params["end"]
        ]

        offset = params["offset"]

        limit = params["limit"]

        return matching[
            offset:
            offset + limit
        ]

    monkeypatch.setattr(
        polymarket,
        "_get",
        fake_get
    )

    query = polymarket.TradeQuery(
        market="0xtestmarket",
        start=0,
        end=12049,
        taker_only=False
    )

    trades, metadata = (
        polymarket.collect_trades(
            query,
            window_s=20000
        )
    )

    keys = [
        polymarket._trade_key(row)
        for row in trades
    ]

    # Acceptance criterion 3
    assert (
        len(keys)
        == len(set(keys))
    )

    assert (
        metadata[
            "duplicates_removed"
        ]
        == 0
    )