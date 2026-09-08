"""
scripts/find_test_wallet.py

Find a wallet suitable for verifying SCRUM-45 live.

A suitable wallet must satisfy BOTH conditions:

  1. More than 5,000 activity events, so the offset cap is
     actually reached and window splitting is exercised.
  2. At least one DEPOSIT or WITHDRAWAL record, so the
     funding-event field mapping can be confirmed.

Strategy
--------
Harvest candidate wallets from trades on a high-volume seed
market, then probe each candidate with two cheap calls:

  * one call at offset 4999 limit 1 - a non-empty response
    proves the wallet has more than 5,000 events, without
    paginating through any of them
  * one call with type=DEPOSIT,WITHDRAWAL limit 5 - proves
    funding records exist and shows their shape

Two requests per candidate. Run from the repository root:

    python scripts/find_test_wallet.py
"""

import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

sys.path.insert(
    0,
    str(ROOT)
)

from collectors.polymarket import _get


# ============================================================
# Candidate harvesting
# ============================================================

# Seed markets from the 2026-08-20 feasibility run. These are
# real resolved markets with genuine retail participation,
# which is what we want - the 5-minute crypto markets are
# dominated by bots that rarely deposit.
SEED_MARKETS = [
    "0xd1e4e03a0129aad7b23e835bfb5c0166d7342fb98e91aa7dd0f3e6cb423d9c21",
    "0x14a3dfeba8b22a32feb0f10763db68bc4d2abeb5bff90e9ae20de53793b35a1d",
    "0x4c5701bcde0b8fb7d7f48c8e9d20245a6caa58c61a77f981fad98f2bfa0b1bc7",
]

CANDIDATES_PER_MARKET = 300

MAX_CANDIDATES_TO_PROBE = 25


def harvest_candidates() -> list:
    """
    Collect wallets seen trading on the seed markets, ordered
    by how often they appear. Frequent traders are the most
    likely to breach the activity cap.
    """

    counter = collections.Counter()

    for market in SEED_MARKETS:

        print(f"harvesting {market[:18]}...")

        page = _get(
            "/trades",
            {
                "market": market,
                "limit": CANDIDATES_PER_MARKET,
                "offset": 0,
                "takerOnly": "false",
            }
        )

        if not isinstance(page, list):
            print("  unexpected response, skipping")
            continue

        for row in page:

            wallet = row.get("proxyWallet")

            if wallet:
                counter[wallet] += 1

        print(f"  {len(page)} trades, "
              f"{len(counter)} distinct wallets so far")

    return [
        wallet
        for wallet, _ in counter.most_common()
    ]


# ============================================================
# Cheap probes
# ============================================================

def exceeds_cap(
    wallet: str
) -> bool:
    """
    True if the wallet has more than 5,000 activity events.

    Asks for a single row at offset 4999. If anything comes
    back, event 5,000 exists.
    """

    page = _get(
        "/activity",
        {
            "user": wallet,
            "limit": 1,
            "offset": 4999,
            "start": 1,
            "sortBy": "TIMESTAMP",
            "sortDirection": "ASC",
            "excludeDepositsWithdrawals": "false",
        }
    )

    return bool(page)


def funding_sample(
    wallet: str
) -> list:
    """
    Return up to five DEPOSIT or WITHDRAWAL records.

    excludeDepositsWithdrawals must be false: the API default
    is true even when type= explicitly asks for them.
    """

    page = _get(
        "/activity",
        {
            "user": wallet,
            "limit": 5,
            "offset": 0,
            "start": 1,
            "type": "DEPOSIT,WITHDRAWAL",
            "sortBy": "TIMESTAMP",
            "sortDirection": "ASC",
            "excludeDepositsWithdrawals": "false",
        }
    )

    return page if isinstance(page, list) else []


# ============================================================
# Main
# ============================================================

def main():

    candidates = harvest_candidates()

    print()
    print(f"{len(candidates)} candidate wallets harvested")
    print(f"probing top {MAX_CANDIDATES_TO_PROBE}")
    print()

    winners = []

    partial = []

    for wallet in candidates[:MAX_CANDIDATES_TO_PROBE]:

        big = exceeds_cap(wallet)

        funding = funding_sample(wallet)

        flag = (
            "BOTH"
            if big and funding
            else "cap only" if big
            else "funding only" if funding
            else "-"
        )

        print(f"{wallet}  >5000={big!s:5s}  "
              f"funding={len(funding)}  {flag}")

        if big and funding:
            winners.append((wallet, funding))

        elif big or funding:
            partial.append((wallet, big, len(funding)))

    print()
    print("=" * 62)

    if winners:

        wallet, funding = winners[0]

        print("SUITABLE WALLET FOUND")
        print()
        print(f"  {wallet}")
        print()
        print("Funding record shape (this settles the field "
              "mapping):")
        print()
        print(json.dumps(funding[0], indent=2))
        print()
        print("Next:")
        print(f"  python scripts/verify_scrum45.py {wallet}")

    else:

        print("NO WALLET SATISFIED BOTH CONDITIONS")
        print()

        if partial:
            print("Partial matches - a funding-only wallet "
                  "still settles the field mapping:")
            for wallet, big, n in partial:
                print(f"  {wallet}  >5000={big}  funding={n}")
        print()
        print("Widen the search: raise "
              "CANDIDATES_PER_MARKET, raise "
              "MAX_CANDIDATES_TO_PROBE, or add a "
              "higher-volume market to SEED_MARKETS.")

    print("=" * 62)


if __name__ == "__main__":
    main()
