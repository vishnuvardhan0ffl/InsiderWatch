import sys

import pytest

from insiderwatch import cli


# ============================================================
# HELP TESTS
# ============================================================

@pytest.mark.parametrize(
    "argv, expected",
    [
        (
            ["insiderwatch", "--help"],
            "fetch",
        ),
        (
            ["insiderwatch", "fetch", "--help"],
            "market",
        ),
        (
            ["insiderwatch", "fetch", "market", "--help"],
            "condition_id",
        ),
        (
            ["insiderwatch", "fetch", "trader", "--help"],
            "wallet",
        ),
    ],
)
def test_help_documents_every_command(
    monkeypatch,
    capsys,
    argv,
    expected,
):
    """
    Acceptance criterion:
    --help documents every command.
    """

    monkeypatch.setattr(
        sys,
        "argv",
        argv,
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0

    output = capsys.readouterr().out

    assert expected in output


# ============================================================
# FETCH MARKET TEST
# ============================================================

def test_fetch_market_uses_existing_collector(
    monkeypatch,
    capsys,
):
    """
    Acceptance criterion:
    fetch market delegates work to the existing collector.

    No real API request is made in this unit test.
    """

    captured = {}

    def fake_collect_trades(query):
        captured["query"] = query

        return (
            [
                {
                    "timestamp": 100,
                    "price": 0.50,
                }
            ],
            {
                "cached": True,
            },
        )

    monkeypatch.setattr(
        cli,
        "collect_trades",
        fake_collect_trades,
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "insiderwatch",
            "fetch",
            "market",
            "0xtestmarket",
            "--start",
            "100",
            "--end",
            "200",
            "--no-taker-only",
        ],
    )

    cli.main()

    query = captured["query"]

    assert query.market == "0xtestmarket"
    assert query.user is None
    assert query.start == 100
    assert query.end == 200
    assert query.taker_only is False

    output = capsys.readouterr().out

    assert '"command": "fetch market"' in output
    assert '"trade_count": 1' in output


# ============================================================
# FETCH TRADER TEST
# ============================================================

def test_fetch_trader_uses_existing_collector(
    monkeypatch,
    capsys,
):
    """
    Acceptance criterion:
    fetch trader delegates work to the existing collector.

    No real API request is made in this unit test.
    """

    captured = {}

    def fake_collect_trades(query):
        captured["query"] = query

        return (
            [
                {
                    "timestamp": 100,
                    "price": 0.40,
                },
                {
                    "timestamp": 101,
                    "price": 0.60,
                },
            ],
            {
                "cached": True,
            },
        )

    monkeypatch.setattr(
        cli,
        "collect_trades",
        fake_collect_trades,
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "insiderwatch",
            "fetch",
            "trader",
            "0xtestwallet",
            "--start",
            "100",
            "--end",
            "200",
            "--no-taker-only",
        ],
    )

    cli.main()

    query = captured["query"]

    assert query.user == "0xtestwallet"
    assert query.market is None
    assert query.start == 100
    assert query.end == 200
    assert query.taker_only is False

    output = capsys.readouterr().out

    assert '"command": "fetch trader"' in output
    assert '"trade_count": 2' in output


# ============================================================
# THIN-WRAPPER TEST
# ============================================================

def test_cli_is_thin_wrapper():
    """
    The CLI should delegate collection to collect_trades.

    Analysis functionality should not be implemented in cli.py.
    """

    assert hasattr(
        cli,
        "collect_trades",
    )

    assert callable(
        cli.collect_trades
    )