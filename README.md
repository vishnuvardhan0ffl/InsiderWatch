# insiderwatch

**PG-S2-55 — Someone Always Knows: An Analysis of Insider Trading on Polymarket / Kalshi**

Sprint 1/2 starting scaffold: WS4 API verification suite, repository
structure, and the collector for the Polymarket Data API. See
`WS4_data_feasibility.md`, `PG-S2-55_project_plan.md` and
`PG-S2-55_jira_backlog.md` for the full plan this was built from.

Kalshi is descoped. Its public trade schema carries no counterparty
identifier of any kind (WS4 §4), so trader-level work was never possible
there; the collector has been removed rather than left as dead code. The
WS4 evidence for that finding stays in `verify_apis.py` (tests 4 and 5) and
`docs/data_dictionary.md`, because the decision rests on it.

## What's here

```
insiderwatch/
├── verify_apis.py          # WS4 verification suite — run this FIRST
├── collectors/
│   ├── polymarket.py       # /trades, /activity, /closed-positions
│   ├── cache.py            # raw response storage — see docs/caching_layer.md
│   └── session.py          # pacing and retries, outside the cache
├── analysis/
│   └── pagination_validation.ipynb
├── cli/                    # CLI skeleton — Sprint 2 story
├── processing/              # cleaning/normalisation — Sprint 3 story
├── analysis/                # features, heuristics, scoring — Sprint 3-4
├── visualisation/           # figures — Sprint 3-5
├── config/
│   └── seeds.json          # seed-case condition IDs + boundary probe market
├── tests/
├── docs/
│   ├── data_dictionary.md  # field-level dictionary, seeded from WS4 §3
│   └── WS4_test6_V1V2_continuity_finding.md   # R1 closed — read this before collector work
├── data/
│   ├── external/            # committed evidence (verify_apis.py output)
│   └── raw/                 # gitignored API response cache
└── .github/workflows/ci.yml
```

## Setup

```bash
git clone <your-repo-url>
cd insiderwatch
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

No API keys are required — every endpoint used here is public and
unauthenticated. `.env.example` is a placeholder for the optional
Sprint 5 on-chain spike only.

## Step 1 — Run the API verification suite

This is Sprint 1's highest-priority story. It must be run from a normal
network connection (unauthenticated public endpoints, no egress
restrictions):

```bash
python verify_apis.py
```

The V1→V2 historical-continuity tests (6a/6b/6c) run automatically from
`config/seeds.json` — no arguments needed. To test other markets instead:

```bash
python verify_apis.py --market 0xabc123... 0xdef456...
```

This writes `data/external/feasibility_check_<date>.json`. **Commit that
file** — it's the dated evidence the methodology section will cite.
Triage every `FAIL` in writing before building anything on top of that
endpoint (per the Sprint 1 acceptance criteria). The script exits non-zero
if the continuity headline is anything other than `YES`.

### Where the continuity question landed

**Answered YES on 20 August 2026.** Pre-migration history is fully reachable:
all three seed markets return trades, a market live across the cutover returns
trades on both sides of it, and `proxyWallet` values survive the migration.
Risk **R1 is closed** and the collector is unblocked.

Read `docs/WS4_test6_V1V2_continuity_finding.md` before writing collector code —
it also records two traps that will silently corrupt a dataset if you don't know
about them.

## Step 2 — Collect data

Once verification passes, pull data through the collectors directly, or
build the CLI wrapper around them (Sprint 2 story: "Build the CLI
skeleton with fetch commands"). Example — Polymarket trades for one
market, one week:

```python
from collectors.polymarket import collect_trades, TradeQuery
import time

query = TradeQuery(
    market="0xabc123...",
    taker_only=False,             # set explicitly — see WS4 §3.1 trap 1
    start=int(time.time()) - 7 * 86400,
    end=int(time.time()),
)
trades, metadata = collect_trades(query)
print(f"{len(trades)} trades")
```

`fetch_trades(query)` is the iterator-shaped wrapper around the same call.

The collector goes through the caching layer (`collectors/cache.py`),
which saves every response under `data/raw/` (gitignored) byte-for-byte, beside
a metadata file recording the URL, parameters, retrieval time and a SHA-256 of
the body. A repeated run makes zero network calls, and the saved file is
citable evidence of what the API returned on a given date — this is what makes
the pipeline reproducible per WS5's "raw storage and caching layer" story.

To point the cache somewhere else, set `INSIDERWATCH_CACHE_DIR` or pass a path
to `ResponseCache(...)`. To replay a frozen dataset with no network access at
all, pass `offline=True` — anything not already collected raises `CacheMiss`
rather than quietly downloading fresh data. See `docs/caching_layer.md`.

## Step 3 — Run tests

```bash
pytest -q
```

The included tests are offline only — no network required. They cover the
caching layer, the collector's wiring into it (including that a repeated
collection makes no requests), window pagination and offset-cap splitting,
explicit-`takerOnly` enforcement, and the verification suite's cutover
constant, pre-migration window and response summarisation. Fixture-backed tests against recorded API responses
are Sprint 2's "test harness and recorded fixtures" story.

To demonstrate the caching layer against the **live** API and write dated
evidence for it:

```bash
python verify_cache.py
```

This writes `data/external/cache_check_<date>.json`. **Commit that file.**

## Step 4 — Push to GitHub

See the step-by-step in the project chat / your team's setup notes for
creating the remote repository and pushing this scaffold. In short:

```bash
git init
git add .
git commit -m "Scaffold repo: WS4 verification suite + starter collectors"
git branch -M main
git remote add origin <your-repo-url>
git push -u origin main
```

## Known traps this scaffold already handles

- **`start`/`end` ignored without scope.** A `/trades` call carrying a time
  window but no `user=` or `market=` returns *current* trades, silently. No
  error, no empty array. Every historical call must be scoped — `verify_apis.py`
  test 8 re-checks this on every run.
- **`takerOnly` silent default.** The Polymarket API defaults this to
  `true`, silently dropping maker-side fills. `TradeQuery` forces the
  caller to set it explicitly — never left implicit (risk R4).
- **Offset caps.** `/trades` caps `offset` at 10,000, `/activity` at
  5,000. The collector paginates by time window, not offset alone, and
  shrinks its window automatically if a window is too dense to fit under
  the cap.
- **No identity field on Kalshi.** There is no wallet/user/account field
  anywhere in the public Kalshi trade schema (WS4 §4), which is why Kalshi
  is descoped rather than collected. Do not reintroduce a Kalshi collector
  without a scope decision recorded first.

## Not yet built (see the Sprint backlog)

Cleaning/normalisation, the frozen analysis dataset, the control cohort,
feature engineering, heuristics, scoring, and the CLI's `market`/
`trader`/`score`/`export` commands. See `PG-S2-55_jira_backlog.md` for
the full sequencing.
