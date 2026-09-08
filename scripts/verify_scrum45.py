"""
scripts/verify_scrum45.py

Live verification of the SCRUM-45 acceptance criteria.

    For a given wallet the collector returns first-activity
    timestamp, full funding event list and realised PnL per
    closed position.

    Offset cap of 5,000 on activity handled by time
    windowing.

Runs a real collection against the Polymarket Data API and
writes the evidence to data/raw/scrum45_verification/.

Usage, from the repository root:

    python scripts/verify_scrum45.py 0xWALLET

Responses are cached by collectors.polymarket, so a second
run costs no network calls.
"""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

sys.path.insert(
    0,
    str(ROOT)
)

from collectors.polymarket_activity import collect_wallet_profile


OUT_DIR = (
    ROOT
    / "data"
    / "raw"
    / "scrum45_verification"
)


def main():

    if len(sys.argv) < 2:

        print("usage: python scripts/verify_scrum45.py "
              "0xWALLET")

        print()
        print("Find a suitable wallet first:")
        print("  python scripts/find_test_wallet.py")

        sys.exit(1)

    wallet = sys.argv[1]

    OUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    print(f"collecting {wallet}")
    print("this will take a while on a busy wallet")
    print()

    profile = collect_wallet_profile(wallet)

    meta = profile["activity_metadata"]

    funding = profile["funding"]

    pnl = profile["realised_pnl"]

    # ========================================================
    # Report
    # ========================================================

    print()
    print("=" * 62)
    print("AC 1 - first-activity timestamp")
    print("=" * 62)

    first = profile["first_activity_timestamp"]

    print(f"  first activity : {first}")

    if first:
        import datetime
        iso = datetime.datetime.fromtimestamp(
            first,
            datetime.timezone.utc
        ).isoformat()
        print(f"  as ISO         : {iso}")

    print()
    print("=" * 62)
    print("AC 2 - full funding event list")
    print("=" * 62)

    print(f"  funding events : {funding['event_count']}")
    print(f"  deposits       : {funding['deposit_count']}")
    print(f"  withdrawals    : {funding['withdrawal_count']}")
    print(f"  total deposited: "
          f"{round(funding['total_deposited'], 2)}")
    print(f"  total withdrawn: "
          f"{round(funding['total_withdrawn'], 2)}")
    print(f"  mapping OK     : "
          f"{funding['field_mapping_confirmed']}")
    print(f"  rows w/o amount: "
          f"{funding['records_without_amount_field']}")

    if funding["events"]:
        print()
        print("  first funding record:")
        print(json.dumps(
            funding["events"][0]["raw"],
            indent=4
        ))

    print()
    print("=" * 62)
    print("AC 3 - realised PnL per closed position")
    print("=" * 62)

    print(f"  positions      : {pnl['position_count']}")
    print(f"  missing pnl    : "
          f"{pnl['positions_missing_pnl']}")
    print(f"  total realised : "
          f"{round(pnl['total_realised_pnl'], 4)}")
    print(f"  winners/losers : "
          f"{pnl['winning_positions']} / "
          f"{pnl['losing_positions']}")

    print()
    print("=" * 62)
    print("AC 4 - 5,000 offset cap handled by windowing")
    print("=" * 62)

    print(f"  total activity : "
          f"{meta['final_activity_count']}")
    print(f"  window splits  : "
          f"{meta['window_split_count']}")
    print(f"  requests       : {meta['request_count']}")
    print(f"  duplicates     : {meta['duplicates_removed']}")
    print(f"  types observed : {meta['types_observed']}")

    # ========================================================
    # Write evidence
    # ========================================================

    (OUT_DIR / "activity_metadata.json").write_text(
        json.dumps(meta, indent=2, default=str),
        encoding="utf-8"
    )

    (OUT_DIR / "funding_events.json").write_text(
        json.dumps(funding, indent=2, default=str),
        encoding="utf-8"
    )

    (OUT_DIR / "realised_pnl.json").write_text(
        json.dumps(pnl, indent=2, default=str),
        encoding="utf-8"
    )

    summary = {
        "wallet": wallet,
        "first_activity_timestamp": first,
        "funding_event_count": funding["event_count"],
        "total_deposited":
            funding["total_deposited"],
        "total_withdrawn":
            funding["total_withdrawn"],
        "funding_mapping_confirmed":
            funding["field_mapping_confirmed"],
        "closed_position_count": pnl["position_count"],
        "positions_missing_pnl":
            pnl["positions_missing_pnl"],
        "activity_record_count":
            meta["final_activity_count"],
        "window_split_count":
            meta["window_split_count"],
        "duplicates_removed": meta["duplicates_removed"],
    }

    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary, indent=2, default=str),
        encoding="utf-8"
    )

    # ========================================================
    # Verdict
    # ========================================================

    print()
    print("=" * 62)

    problems = []

    if first is None:
        problems.append(
            "no first-activity timestamp"
        )

    if funding["event_count"] == 0:
        problems.append(
            "no funding events - field mapping still "
            "unconfirmed, try another wallet"
        )

    if not funding["field_mapping_confirmed"] \
            and funding["event_count"] > 0:
        problems.append(
            "some funding rows carry no usdcSize amount"
        )

    if meta["window_split_count"] == 0:
        problems.append(
            "cap never reached - this wallet does not "
            "demonstrate windowing, try a busier one"
        )

    if pnl["position_count"] == 0:
        problems.append(
            "no closed positions"
        )

    if problems:
        print("INCOMPLETE")
        for p in problems:
            print(f"  - {p}")
    else:
        print("ALL ACCEPTANCE CRITERIA VERIFIED LIVE")

    print()
    print(f"evidence written to {OUT_DIR}")
    print("=" * 62)


if __name__ == "__main__":
    main()
