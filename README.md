# insiderwatch

**PG-S2-55 — Someone Always Knows: An Analysis of Insider Trading on Polymarket / Kalshi**

Sprint 1/2 starting scaffold: WS4 API verification suite, repository
structure, and starter collectors for the Polymarket Data API and the
Kalshi Trade API v2. See `WS4_data_feasibility.md`, `PG-S2-55_project_plan.md`
and `PG-S2-55_jira_backlog.md` for the full plan this was built from.

## What's here

```
insiderwatch/
├── verify_apis.py          # WS4 verification suite — run this FIRST
├── collectors/
│   ├── polymarket.py       # /trades, /activity, /closed-positions
│   └── kalshi.py           # /markets/trades (market-level only, no identity field)
├── cli/                    # CLI skeleton — Sprint 2 story
├── processing/              # cleaning/normalisation — Sprint 3 story
├── analysis/                # features, heuristics, scoring — Sprint 3-4
├── visualisation/           # figures — Sprint 3-5
├── config/
├── tests/
├── docs/
│   └── data_dictionary.md  # field-level dictionary, seeded from WS4 §3
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
network connection (unauthenticated Polymarket/Kalshi endpoints, no
egress restrictions):

```bash
python verify_apis.py
```

To also test the V1→V2 historical-continuity question (the single
highest-value unknown in the project — WS4 §1.3), pass the seed markets'
Polymarket condition IDs once you have them:

```bash
python verify_apis.py --market 0xabc123... 0xdef456...
```

This writes `data/external/feasibility_check_<date>.json`. **Commit that
file** — it's the dated evidence the methodology section will cite.
Triage every `FAIL` in writing before building anything on top of that
endpoint (per the Sprint 1 acceptance criteria).

## Step 2 — Collect data

Once verification passes, pull data through the collectors directly, or
build the CLI wrapper around them (Sprint 2 story: "Build the CLI
skeleton with fetch commands"). Example — Polymarket trades for one
market, one week:

```python
from collectors.polymarket import fetch_trades, TradeQuery
import time

query = TradeQuery(
    market="0xabc123...",
    taker_only=False,             # set explicitly — see WS4 §3.1 trap 1
    start=int(time.time()) - 7 * 86400,
    end=int(time.time()),
)
trades = list(fetch_trades(query))
print(f"{len(trades)} trades")
```

Kalshi market trades:

```python
from collectors.kalshi import fetch_trades

trades = list(fetch_trades(ticker="KXSOMETICKER"))
print(f"{len(trades)} trades")
```

Both collectors cache every response under `data/raw/` (gitignored) so a
repeated run makes zero network calls — this is what makes the pipeline
reproducible per WS5's "raw storage and caching layer" story.

## Step 3 — Run tests

```bash
pytest -q
```

The included tests are offline smoke tests only (cache-key determinism,
explicit-`takerOnly` enforcement). Fixture-backed tests against recorded
API responses are Sprint 2's "test harness and recorded fixtures" story.

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

- **`takerOnly` silent default.** The Polymarket API defaults this to
  `true`, silently dropping maker-side fills. `TradeQuery` forces the
  caller to set it explicitly — never left implicit (risk R4).
- **Offset caps.** `/trades` caps `offset` at 10,000, `/activity` at
  5,000. Both collectors paginate by time window, not offset alone, and
  the trades collector shrinks its window automatically if a window is
  too dense to fit under the cap.
- **No identity field on Kalshi.** The Kalshi collector is intentionally
  market-level only — there is no wallet/user/account field in the
  schema to collect (WS4 §4).

## Not yet built (see the Sprint backlog)

Cleaning/normalisation, the frozen analysis dataset, the control cohort,
feature engineering, heuristics, scoring, and the CLI's `market`/
`trader`/`score`/`export` commands. See `PG-S2-55_jira_backlog.md` for
the full sequencing.
