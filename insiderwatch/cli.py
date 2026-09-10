from __future__ import annotations

import argparse
import json
from pathlib import Path

from collectors.polymarket import TradeQuery, collect_trades


def add_trade_options(parser):
    parser.add_argument(
        "--start",
        type=int,
        required=True,
        help="Start Unix timestamp.",
    )

    parser.add_argument(
        "--end",
        type=int,
        required=True,
        help="End Unix timestamp.",
    )

    parser.add_argument(
        "--taker-only",
        action=argparse.BooleanOptionalAction,
        required=True,
        help="Use only taker trades or include maker-side trades.",
    )


def build_parser():
    parser = argparse.ArgumentParser(
        prog="insiderwatch",
        description="InsiderWatch command-line interface.",
    )

    commands = parser.add_subparsers(
        dest="command",
        required=True,
    )

    # ---------------------------------------------------------
    # fetch
    # ---------------------------------------------------------

    fetch_parser = commands.add_parser(
        "fetch",
        help="Fetch Polymarket trade data.",
    )

    fetch_commands = fetch_parser.add_subparsers(
        dest="fetch_command",
        required=True,
    )

    # ---------------------------------------------------------
    # fetch market
    # ---------------------------------------------------------

    market_parser = fetch_commands.add_parser(
        "market",
        help="Fetch trades for a market.",
    )

    market_parser.add_argument(
        "condition_id",
        help="Polymarket market condition ID.",
    )

    add_trade_options(market_parser)

    # ---------------------------------------------------------
    # fetch trader
    # ---------------------------------------------------------

    trader_parser = fetch_commands.add_parser(
        "trader",
        help="Fetch trades for a trader wallet.",
    )

    trader_parser.add_argument(
        "wallet",
        help="Polymarket trader/proxy wallet address.",
    )

    add_trade_options(trader_parser)

    return parser


def fetch_market(args):
    query = TradeQuery(
        market=args.condition_id,
        start=args.start,
        end=args.end,
        taker_only=args.taker_only,
    )

    trades, metadata = collect_trades(query)

    print(
        json.dumps(
            {
                "command": "fetch market",
                "condition_id": args.condition_id,
                "trade_count": len(trades),
                "cached": True,
                "metadata": metadata,
            },
            indent=2,
            default=str,
        )
    )


def fetch_trader(args):
    query = TradeQuery(
        user=args.wallet,
        start=args.start,
        end=args.end,
        taker_only=args.taker_only,
    )

    trades, metadata = collect_trades(query)

    print(
        json.dumps(
            {
                "command": "fetch trader",
                "wallet": args.wallet,
                "trade_count": len(trades),
                "cached": True,
                "metadata": metadata,
            },
            indent=2,
            default=str,
        )
    )


def main():
    parser = build_parser()

    args = parser.parse_args()

    if (
        args.command == "fetch"
        and args.fetch_command == "market"
    ):
        fetch_market(args)

    elif (
        args.command == "fetch"
        and args.fetch_command == "trader"
    ):
        fetch_trader(args)


if __name__ == "__main__":
    main()