#!/usr/bin/env python3
"""
Re-record the test fixtures from the live Polymarket API.

WHEN TO RUN THIS
----------------
Rarely, and deliberately. Fixtures are recorded evidence: a test that quietly
starts passing against different data is worse than one that fails. Re-record
when the API changes shape, when you need an endpoint that has no fixture yet,
or when a fixture is marked "unverified" in MANIFEST.json and you want to
replace it with the real thing.

Needs a normal network connection - it will not run where egress is blocked.

USAGE
-----
    python tests/record_fixtures.py --list
    python tests/record_fixtures.py --endpoint /positions --user 0xabc...
    python tests/record_fixtures.py --all --user 0xabc...

Nothing is written until you confirm. Every recording is anonymised before it
touches disk (processing.anonymise) and MANIFEST.json is updated with the date,
the record count and the exact call that produced it.

WHAT IT WILL NOT DO
-------------------
Write a fixture still carrying name, pseudonym or bio. That check is not
optional and not a flag: this repository is public, and the ethics protocol
says those fields are never published.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from collectors.session import ThrottledRetryingSession          # noqa: E402
from processing.anonymise import (                               # noqa: E402
    anonymise_records,
    find_identifying_fields,
)

try:
    from config.dns_override import install_dns_override
    install_dns_override()
except Exception:
    pass

BASE_URL = "https://data-api.polymarket.com"
FIXTURE_DIR = Path(__file__).parent / "fixtures"

# Each recipe says which endpoint to call, what to save it as, and the
# parameters that make the response worth keeping.
RECIPES = {
    "/trades": {
        "file": "trades.json",
        "params": lambda a: {"market": a.market, "takerOnly": False, "limit": 5},
        "needs": "market",
    },
    "/activity": {
        "file": "activity.json",
        "params": lambda a: {
            "user": a.user, "limit": 20, "start": 1,
            # false, so funding events are included - the activity fixture is
            # useless for the wallet-funding features without them.
            "excludeDepositsWithdrawals": False,
        },
        "needs": "user",
    },
    "/positions": {
        "file": "positions.json",
        "params": lambda a: {"user": a.user, "limit": 10},
        "needs": "user",
    },
    "/closed-positions": {
        "file": "closed_positions.json",
        "params": lambda a: {"user": a.user, "limit": 20},
        "needs": "user",
    },
}


def load_manifest():
    return json.loads((FIXTURE_DIR / "MANIFEST.json").read_text(encoding="utf-8"))


def save_manifest(manifest):
    (FIXTURE_DIR / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


def show_fixtures():
    manifest = load_manifest()
    print("{:<24} {:<12} {:>8}  {}".format("FIXTURE", "STATUS", "RECORDS", "RECORDED"))
    for name, entry in sorted(manifest["fixtures"].items()):
        print("{:<24} {:<12} {:>8}  {}".format(
            name, entry["status"], entry["records"], entry["recorded"] or "-"
        ))
    print("\nunverified = written from documentation, never seen from the live "
          "API. Replace these when you can.")


def record(endpoint, args, session):
    recipe = RECIPES[endpoint]
    params = recipe["params"](args)

    print("\nGET {}{}".format(BASE_URL, endpoint))
    print("    params: {}".format(params))

    sendable = {
        k: ("true" if v is True else "false" if v is False else v)
        for k, v in params.items() if v is not None
    }
    response = session.get(BASE_URL + endpoint, params=sendable, timeout=30)
    response.raise_for_status()
    records = response.json()

    if not isinstance(records, list) or not records:
        print("    got {} - refusing to save an empty or unexpected response."
              .format(type(records).__name__))
        return False

    print("    {} records".format(len(records)))

    found = find_identifying_fields(records)
    if found:
        print("    profile fields present in the raw response: {}".format(found))
    safe = anonymise_records(records)

    still_there = find_identifying_fields(safe)
    if still_there:
        sys.exit("REFUSING TO WRITE: {} still identifying after anonymisation: {}"
                 .format(recipe["file"], still_there))
    print("    anonymised: profile fields removed, wallets hashed")

    if input("    write {}? [y/N] ".format(recipe["file"])).strip().lower() != "y":
        print("    skipped")
        return False

    (FIXTURE_DIR / recipe["file"]).write_text(
        json.dumps(safe, indent=2) + "\n", encoding="utf-8"
    )

    manifest = load_manifest()
    entry = manifest["fixtures"].setdefault(recipe["file"], {})
    entry.update({
        "endpoint": endpoint,
        "status": "observed",
        "records": len(safe),
        "recorded": datetime.now(timezone.utc).date().isoformat(),
        "source": "tests/record_fixtures.py --endpoint {} ({})".format(endpoint, sendable),
    })
    entry.setdefault("notes", "Re-recorded. Describe what makes this sample "
                              "worth keeping, and anything it does NOT cover.")
    save_manifest(manifest)

    print("    written, MANIFEST.json updated")
    print("    NOW: edit the 'notes' for this entry, run pytest, and say in "
          "the commit message what changed and why.")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Re-record test fixtures from the live Polymarket API")
    parser.add_argument("--list", action="store_true",
                        help="show the current fixtures and their provenance")
    parser.add_argument("--endpoint", choices=sorted(RECIPES),
                        help="record one endpoint")
    parser.add_argument("--all", action="store_true",
                        help="record every endpoint")
    parser.add_argument("--user", help="wallet address for the wallet endpoints")
    parser.add_argument("--market",
                        default="0xd1e4e03a0129aad7b23e835bfb5c0166d7342fb98e91aa7dd0f3e6cb423d9c21",
                        help="condition ID for /trades (default: the Maduro seed market)")
    args = parser.parse_args()

    if args.list or not (args.endpoint or args.all):
        show_fixtures()
        return 0

    endpoints = sorted(RECIPES) if args.all else [args.endpoint]

    for endpoint in endpoints:
        if RECIPES[endpoint]["needs"] == "user" and not args.user:
            print("\nskipping {} - needs --user".format(endpoint))
            continue

    session = ThrottledRetryingSession()
    written = 0
    for endpoint in endpoints:
        if RECIPES[endpoint]["needs"] == "user" and not args.user:
            continue
        if record(endpoint, args, session):
            written += 1

    print("\n{} fixture(s) written.".format(written))
    return 0


if __name__ == "__main__":
    sys.exit(main())
