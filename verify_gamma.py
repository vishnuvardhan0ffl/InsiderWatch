#!/usr/bin/env python3
"""
verify_gamma.py — live acceptance check for the Gamma market and event collector
PG-S2-55: Someone Always Knows

WHY THIS EXISTS
---------------
tests/test_gamma_collector.py proves the collector's behaviour offline, against
recorded fixtures. But those Gamma fixtures are marked UNVERIFIED in
tests/fixtures/MANIFEST.json: their shape came from the published Gamma
reference, not from a live response, because the environment the collector was
written in could not reach gamma-api.polymarket.com.

So the offline suite proves the collector handles the shape we *believe* Gamma
returns. This script proves what Gamma actually returns. Until it has been run
and its evidence file committed, the unmarked rows in the Gamma section of
docs/data_dictionary.md stay documentation-only and must not be cited.

Run it from a machine with normal (unblocked) internet access:

    python verify_gamma.py
    python verify_gamma.py --out data/external/gamma_check_2026-09-10.json

It writes into a throwaway cache directory under the system temp folder, never
into data/raw/, so running it cannot disturb a frozen dataset.

WHAT IT SETTLES
---------------
    1. /markets is reachable unauthenticated and returns a JSON list
    2. Which documented fields are actually present on a market record
    3. Which types they arrive as (volumeNum a string or a number? outcomes
       JSON-encoded?) — the answers go straight into the data dictionary
    4. The `slug` parameter is honoured
    5. The `condition_ids` parameter is honoured
    6. `order` / `ascending` are honoured — ids come back ascending
    7. `offset` is honoured — page two is disjoint from page one
    8. A live keyset walk returns no duplicate ids
    9. /events is reachable and carries markets[].conditionId for the join
   10. Every seed market in config/seeds.json resolves, and its endDate agrees
       with the resolution_date recorded there

AFTER RUNNING IT
----------------
    * commit data/external/gamma_check_<date>.json
    * mark the confirmed rows *(obs)* in docs/data_dictionary.md, with the date
    * fix any parameter-name constant in collectors/gamma.py that check 4-7
      says is wrong (they are constants precisely so this is a one-line change)
    * replace the fixtures with real recordings:
          python tests/record_fixtures.py --endpoint /markets
          python tests/record_fixtures.py --endpoint /events
      then re-run pytest and update MANIFEST.json's notes
"""

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from collectors import gamma                                    # noqa: E402
from collectors.cache import CachedClient, ResponseCache        # noqa: E402
from collectors.session import ThrottledRetryingSession         # noqa: E402

try:
    from config.dns_override import install_dns_override
    install_dns_override()
except Exception:
    pass

DEFAULT_SEEDS = Path("config/seeds.json")

# The rows in docs/data_dictionary.md that carry no *(obs)* marker. Check 2
# exists to settle exactly these.
UNCONFIRMED_MARKET_FIELDS = [
    "id", "liquidityNum", "createdAt", "closed", "active", "archived",
    "outcomes", "clobTokenIds", "eventSlug", "events", "tags",
]

CONFIRMED_MARKET_FIELDS = [
    "question", "slug", "conditionId", "startDate", "endDate", "volumeNum",
]


def log(message):
    print(message, flush=True)


def record(results, check, name, result, detail):
    results.append(
        {"check": check, "name": name, "result": result, "detail": detail}
    )
    log("  [{}] {}. {} — {}".format(result, check, name, detail))


def load_seeds(seeds_path):
    path = Path(seeds_path) if seeds_path else DEFAULT_SEEDS

    if not path.exists():
        sys.exit(
            "{} not found. Pass --seeds <path>.".format(path)
        )

    return json.loads(path.read_text(encoding="utf-8"))


def describe_type(value):
    """What arrived, in the terms the data dictionary cares about."""

    if value is None:
        return "null"

    if isinstance(value, bool):
        return "bool"

    if isinstance(value, (int, float)):
        return "number"

    if isinstance(value, list):
        return "list[{}]".format(len(value))

    if isinstance(value, dict):
        return "object"

    text = str(value).strip()

    if text.startswith("["):
        return "JSON-encoded list (string)"

    try:
        float(text.replace(",", ""))
        return "numeric string"
    except ValueError:
        return "string"


def main():
    parser = argparse.ArgumentParser(
        description="Live verification of the Gamma collector (PG-S2-55)"
    )
    parser.add_argument("--seeds", default=None, help="Seed markets JSON")
    parser.add_argument(
        "--out", default=None,
        help="Output JSON path (default: data/external/gamma_check_<date>.json)"
    )
    parser.add_argument(
        "--keep", action="store_true",
        help="Leave the probe cache directory on disk for inspection"
    )
    args = parser.parse_args()

    seeds = load_seeds(args.seeds)
    probe_dir = Path(tempfile.mkdtemp(prefix="insiderwatch_gamma_check_"))

    client = CachedClient(
        gamma.BASE_URL,
        cache=ResponseCache(probe_dir),
        session=ThrottledRetryingSession(min_interval_s=gamma.MIN_INTERVAL_S),
    )

    results = []
    observations = {}

    log("=" * 70)
    log("GAMMA COLLECTOR LIVE CHECK — PG-S2-55")
    log("Run started: {}".format(datetime.now(timezone.utc).isoformat()))
    log("Base URL: {}".format(gamma.BASE_URL))
    log("Probe cache: {}".format(probe_dir))
    log("=" * 70)

    # ------------------------------------------------------------------
    # 1. Reachability
    # ------------------------------------------------------------------
    sample = None
    try:
        payload = client.get_json(
            gamma.MARKETS_ENDPOINT,
            {gamma.LIMIT_PARAM: 5, gamma.ORDER_PARAM: gamma.KEYSET_FIELD,
             gamma.ASCENDING_PARAM: False},
        )
        rows = gamma._rows(payload, gamma.MARKETS_ENDPOINT)
        sample = rows[0] if rows else None

        record(results, 1, "/markets reachable unauthenticated",
               "PASS" if rows else "FAIL",
               "{} records returned".format(len(rows)))
    except Exception as error:
        record(results, 1, "/markets reachable unauthenticated", "FAIL",
               "{}: {}".format(type(error).__name__, error))

    # ------------------------------------------------------------------
    # 2 and 3. Which fields are present, and as what type
    # ------------------------------------------------------------------
    if sample is not None:
        present = {
            name: describe_type(sample.get(name))
            for name in CONFIRMED_MARKET_FIELDS + UNCONFIRMED_MARKET_FIELDS
            if name in sample
        }
        missing = [
            name for name in CONFIRMED_MARKET_FIELDS + UNCONFIRMED_MARKET_FIELDS
            if name not in sample
        ]
        observations["market_field_types"] = present
        observations["market_fields_absent"] = missing
        observations["market_fields_undocumented"] = sorted(
            set(sample) - set(CONFIRMED_MARKET_FIELDS)
            - set(UNCONFIRMED_MARKET_FIELDS)
        )

        settled = [f for f in UNCONFIRMED_MARKET_FIELDS if f in present]

        record(results, 2, "documented fields present on a market record",
               "PASS" if not missing else "PARTIAL",
               "{}/{} present; absent: {}".format(
                   len(present),
                   len(CONFIRMED_MARKET_FIELDS + UNCONFIRMED_MARKET_FIELDS),
                   missing or "none"))

        record(results, 3, "types observed for the unconfirmed fields",
               "PASS" if settled else "FAIL",
               "settled {} of {}: {}".format(
                   len(settled), len(UNCONFIRMED_MARKET_FIELDS),
                   {k: v for k, v in present.items() if k in settled}))

    # ------------------------------------------------------------------
    # 4 and 5. The by-name lookups, which are the story's acceptance criteria
    # ------------------------------------------------------------------
    first_seed = (seeds.get("markets") or [{}])[0]

    if first_seed.get("slug"):
        try:
            market = gamma.fetch_market_by_slug(first_seed["slug"], client=client)
            ok = market["condition_id"] == first_seed["condition_id"]
            record(results, 4,
                   "`{}` parameter honoured (lookup by slug)".format(
                       gamma.SLUG_PARAM),
                   "PASS" if ok else "FAIL",
                   "{} -> {}".format(first_seed["slug"], market["condition_id"]))
        except Exception as error:
            record(results, 4,
                   "`{}` parameter honoured (lookup by slug)".format(
                       gamma.SLUG_PARAM),
                   "FAIL",
                   "{}: {} — if this is a parameter-name problem, fix "
                   "gamma.SLUG_PARAM".format(type(error).__name__, error))

    if first_seed.get("condition_id"):
        try:
            market = gamma.fetch_market_by_condition_id(
                first_seed["condition_id"], client=client
            )
            ok = market["slug"] == first_seed.get("slug", market["slug"])
            record(results, 5,
                   "`{}` parameter honoured (lookup by condition ID)".format(
                       gamma.CONDITION_ID_PARAM),
                   "PASS" if ok else "FAIL",
                   "{} -> {}".format(first_seed["condition_id"], market["slug"]))
        except Exception as error:
            record(results, 5,
                   "`{}` parameter honoured (lookup by condition ID)".format(
                       gamma.CONDITION_ID_PARAM),
                   "FAIL",
                   "{}: {} — if this is a parameter-name problem, fix "
                   "gamma.CONDITION_ID_PARAM".format(
                       type(error).__name__, error))

    # ------------------------------------------------------------------
    # 6 and 7. Ordering and offset, on which the whole walk depends
    # ------------------------------------------------------------------
    try:
        page_params = {
            gamma.LIMIT_PARAM: 10,
            gamma.ORDER_PARAM: gamma.KEYSET_FIELD,
            gamma.ASCENDING_PARAM: True,
        }

        page_one = gamma._rows(
            client.get_json(gamma.MARKETS_ENDPOINT,
                            dict(page_params, **{gamma.OFFSET_PARAM: 0})),
            gamma.MARKETS_ENDPOINT)

        page_two = gamma._rows(
            client.get_json(gamma.MARKETS_ENDPOINT,
                            dict(page_params, **{gamma.OFFSET_PARAM: 10})),
            gamma.MARKETS_ENDPOINT)

        ids_one = [str(row.get(gamma.KEYSET_FIELD)) for row in page_one]
        ids_two = [str(row.get(gamma.KEYSET_FIELD)) for row in page_two]

        numeric = all(value.isdigit() for value in ids_one)
        ascending = (
            [int(v) for v in ids_one] == sorted(int(v) for v in ids_one)
            if numeric else ids_one == sorted(ids_one)
        )

        record(results, 6,
               "`{}`/`{}` honoured — ids ascending".format(
                   gamma.ORDER_PARAM, gamma.ASCENDING_PARAM),
               "PASS" if ascending else "FAIL",
               "first ids: {}".format(ids_one[:5]))

        overlap = set(ids_one) & set(ids_two)
        record(results, 7,
               "`{}` honoured — page two disjoint from page one".format(
                   gamma.OFFSET_PARAM),
               "PASS" if not overlap else "FAIL",
               "{} overlapping ids".format(len(overlap)))

        observations["keyset_field_is_numeric"] = numeric
    except Exception as error:
        record(results, 6, "ordering and offset", "FAIL",
               "{}: {}".format(type(error).__name__, error))

    # ------------------------------------------------------------------
    # 8. The walk itself, live
    # ------------------------------------------------------------------
    try:
        markets, metadata = gamma.collect_markets(
            gamma.MarketQuery(limit=50, max_records=200), client=client
        )
        ids = [market["market_id"] for market in markets]

        record(results, 8, "live keyset walk returns no duplicate ids",
               "PASS" if len(ids) == len(set(ids)) else "FAIL",
               "{} records over {} requests, {} duplicates dropped, stopped: {}"
               .format(len(ids), metadata["request_count"],
                       metadata["duplicates_dropped"],
                       metadata["stopped_because"]))

        observations["walk_metadata"] = metadata
    except Exception as error:
        record(results, 8, "live keyset walk returns no duplicate ids", "FAIL",
               "{}: {}".format(type(error).__name__, error))

    # ------------------------------------------------------------------
    # 9. Events, and the join key
    # ------------------------------------------------------------------
    try:
        events, _ = gamma.collect_events(
            gamma.EventQuery(limit=5, max_records=5), client=client
        )
        with_markets = [e for e in events if e["market_condition_ids"]]

        record(results, 9, "/events carries markets[].conditionId for the join",
               "PASS" if with_markets else "FAIL",
               "{} of {} events carry condition IDs".format(
                   len(with_markets), len(events)))
    except Exception as error:
        record(results, 9, "/events carries markets[].conditionId for the join",
               "FAIL", "{}: {}".format(type(error).__name__, error))

    # ------------------------------------------------------------------
    # 10. The seed markets, which the case studies depend on
    # ------------------------------------------------------------------
    for index, seed in enumerate(seeds.get("markets", []), start=1):
        name = "seed market {} ({})".format(index, seed.get("category", "?"))
        try:
            market = gamma.fetch_market_by_condition_id(
                seed["condition_id"], client=client
            )
            recorded = str(seed.get("resolution_date") or "")[:10]
            returned = str(market.get("end_date") or "")[:10]
            agrees = recorded == returned

            record(results, 10, name, "PASS" if agrees else "FAIL",
                   "endDate {} vs seeds.json resolution_date {}{}".format(
                       returned or "none", recorded or "none",
                       "" if agrees else "  <- RECONCILE THIS"))
        except Exception as error:
            record(results, 10, name, "FAIL",
                   "{}: {}".format(type(error).__name__, error))

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------
    out_path = Path(args.out) if args.out else Path(
        "data/external/gamma_check_{}.json".format(
            datetime.now(timezone.utc).date().isoformat()
        )
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fails = [r for r in results if r["result"] == "FAIL"]

    evidence = {
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "story": "WS5 — Build the Gamma market and event collector",
        "base_url": gamma.BASE_URL,
        "parameter_names_tested": {
            "slug": gamma.SLUG_PARAM,
            "condition_ids": gamma.CONDITION_ID_PARAM,
            "offset": gamma.OFFSET_PARAM,
            "order": gamma.ORDER_PARAM,
            "ascending": gamma.ASCENDING_PARAM,
            "limit": gamma.LIMIT_PARAM,
        },
        "headline_question": (
            "Does the Gamma API behave as collectors/gamma.py assumes, and "
            "which documentation-only rows in the data dictionary can now be "
            "marked (obs)?"
        ),
        "headline_answer": "YES" if not fails else "NO",
        "observations": observations,
        "results": results,
    }

    out_path.write_text(
        json.dumps(evidence, indent=2, default=str), encoding="utf-8"
    )

    if not args.keep:
        import shutil
        shutil.rmtree(probe_dir, ignore_errors=True)

    log("=" * 70)
    log("Done. {} checks run, {} FAIL. Evidence written to {}".format(
        len(results), len(fails), out_path))
    log("Next: mark the confirmed data-dictionary rows (obs) with today's "
        "date, then re-record the Gamma fixtures.")
    log("=" * 70)

    return 0 if not fails else 2


if __name__ == "__main__":
    sys.exit(main())
