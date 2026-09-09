# Control cohort — extraction specification

**Story:** WS6 "Specify the control cohort extraction" · **Owner:** BC
**Executable form:** `processing/control_cohort.py` · **Tests:** `tests/test_control_cohort.py`
**Written:** 9 September 2026

> **Status: NOT YET APPROVED. Do not build the cohort from this document alone.**
>
> This story was written as "turn the *approved* sampling design into an
> executable specification". That approved design does not exist: the Sprint 1
> story "Design the control-group sampling frame" has no design note in the
> repository, and risk **R5** states plainly that *the cohort must not be built
> until Mohsen has reviewed the design*.
>
> So this document is both — the design **and** the specification, in one.
> Section 2 is the part that needs review. Everything from section 3 onward is
> mechanical once section 2 is agreed.

---

## 1. What a control cohort is, plainly

Our whole method rests on one sentence: *this trader behaved unusually*. That
sentence is meaningless without a second one: *compared to these traders*.

The control cohort is the second sentence. It is a group of ordinary traders
whose behaviour we measure — position sizes, wallet ages, how concentrated
their portfolios are, how often they win — so that "unusual" becomes a number
instead of an opinion. Every threshold in the detection layer is calibrated
against these distributions.

Get the cohort wrong and nothing downstream can be right. A cohort that is
accidentally full of winners makes real winners look normal. A cohort full of
tiny traders makes every large bet look suspicious.

## 2. The design (**this is the part for review**)

### 2.1 Sampling unit: a wallet in a market

Not a wallet. A **wallet-in-a-market**.

The question the detector asks is always market-relative: *in this market, was
this trader unusual?* A wallet that trades cautiously in politics and
recklessly in crypto is two different behaviours, and averaging them describes
neither.

One wallet appearing in three markets contributes three rows.

### 2.2 Sampling frame: the seed markets and matched comparison markets

**Not the platform at large.** This is the central design decision.

Two obvious frames, both rejected:

- **Leaderboard rankings** — the frame WS4 §3.2 lists. Rejected: it is a
  ranking *by profit*, so it is a sample of winners. Calibrating "unusual
  profitability" against a cohort selected for profitability is circular.
- **The recent global trade feed** — rejected on evidence. Our own recorded
  fixture of an unscoped `/trades` call is almost entirely five-minute
  "Bitcoin Up or Down" markets. A cohort drawn there would be high-frequency
  crypto scalpers. Establishing that a Nobel Prize bettor does not resemble
  them is not a finding.

**The frame we propose:** every distinct wallet that traded in

1. the three **seed markets** (Maduro, Nobel, US–Iran ceasefire), and
2. a set of **matched comparison markets** — for each seed market, two markets
   of the same category, comparable liquidity and a resolution date within
   roughly a month, found through the Gamma `/markets` collector.

Nine markets in total.

**Why matched markets.** Market type is the largest confounder available. A
geopolitical market resolving on a news event has a different natural trading
pattern from a sports market or a five-minute crypto tick. Matching on the
market removes that difference, so what remains to explain is the trader.
Comparison markets are included as well as the seed markets so the baseline is
not defined entirely by markets we already believe contain something unusual.

**What this frame cannot fix, and we disclose rather than mitigate:**

| Bias | Effect | What we do |
|---|---|---|
| Only traders *in these markets* | Cohort is not representative of Polymarket as a whole | Claim only market-relative anomaly; never "unusual for Polymarket" |
| One person, many wallets | A single actor may appear as several "independent" controls | Stated as a limitation; wallet-clustering is out of scope this semester |
| Survivorship in market choice | Matched markets are ones that resolved and are still queryable | Record the matching criteria and how many candidates were rejected |
| Selection by our own case study | Seed markets are chosen *because* something happened in them | Comparison markets dilute this; report the split both ways |

### 2.3 Size: 1,000 wallet-market rows

Not a round number chosen for looking sensible. The binding constraint is the
**99th percentile** — several indicators are calibrated as "above the 99th
percentile of normal". A percentile that extreme is estimated from the tail,
so at *n* = 1,000 it rests on about 10 observations, which is thin but usable;
at *n* = 200 it rests on 2, which is not an estimate at all.

Cost is not the constraint (§5: about 34 minutes), so the size is set by what
the statistics need. If sensitivity analysis in WS12 shows the 99th percentile
moving materially between subsamples, raise it — the frame is far larger than
1,000, so this is cheap to redo.

### 2.4 Stratification

| Stratum | Definition | Share |
|---|---|---|
| `ordinary` | Everything not below | ≥ 90% |
| `market_maker` | Traded **both** sides **and** ≥ 20 trades in the market | capped at 10% |

Market makers are **capped, not removed**. They are part of normal market
behaviour, and a detector that flags every market maker is useless in practice.
But they trade orders of magnitude more than anyone else, so left uncapped they
would drag the trade-count and position-size distributions upward and make
ordinary traders look like outliers.

The 20-trade rule is deliberately crude. We cannot know who is genuinely a
market maker; we can only observe two-sided activity. That is why they get a
label rather than a deletion — the assumption stays visible and reversible.

Markets contribute **in proportion to their wallet count**, so a busy market
does not define the baseline on its own.

### 2.5 Exclusions

Only two:

1. **The candidate wallets under investigation.** A control group containing
   the cases is not a control group. Matched case-insensitively — `0xABC` and
   `0xabc` are one wallet, and missing that leaks a case into the controls.
2. **Nothing else.**

Two exclusions we specifically **reject**, because both would quietly destroy
the study:

- **Do not exclude low-activity wallets.** In the Maduro market, **39% of
  wallets made exactly one trade** and the median wallet made two. More
  importantly, *"new wallet, one large, well-timed trade"* is the exact
  signature we are hunting. Filtering out one-trade wallets removes the
  population the project is about.
- **Do not exclude on profitability.** Profit is the outcome being measured.
  Selecting the cohort on it is circular.

---

## 3. What we learned from the frame that changes WS7

Measured on the real Maduro collection (11,588 trades, 2,657 wallets):

| | |
|---|---|
| Wallets | 2,657 |
| Median trades per wallet **in the market** | **2** |
| Wallets with exactly one trade | 1,033 (39%) |
| Wallets with ≥ 10 trades | **91 (3.4%)** |
| Market-maker-like | 55 (2.1%) |
| Median trade value | **$4.96** |
| 90th percentile trade value | $75.54 |
| Largest single trade | $49,050 |

**The finding that matters:** only 3.4% of wallets have enough in-market
history to compute anything history-based. Win rate, portfolio concentration,
trading frequency and dormancy **cannot** be computed from market trades — for
96% of the cohort there is not enough of it.

Those features must come from **per-wallet `/activity` and `/closed-positions`
collection**, which is why §4 spends most of its API budget there. Discovering
this in week 10 would have cost the baseline.

Second: the median trade is five dollars. Any "large position" threshold
calibrated on this population will be low in absolute terms, and should be
reported as a percentile, never as a dollar figure.

---

## 4. Execution — the exact calls

Run from the repository root, with the collectors on `main`.

**Step 1 — collect trades for all nine markets.**

```python
from collectors.polymarket import TradeQuery, collect_trades, save_trade_collection

query = TradeQuery(
    market=condition_id,
    start=market_start_ts,       # from config/seeds.json
    end=market_resolution_ts,
    taker_only=False,            # MUST be explicit — WS4 §3.1 trap 1
)
trades, metadata = collect_trades(query)
save_trade_collection(trades, metadata, name=f"{market_label}_trades")
```

**Step 2 — build the frame and draw the cohort.**

```python
from processing.control_cohort import build_frame, draw_cohort, estimate_api_calls

frame  = build_frame(trades_by_market, exclude_wallets=CANDIDATE_WALLETS)
cohort = draw_cohort(frame, size=1000, seed=20260913)
```

**The seed is part of the dataset.** Record `20260913` in the M3 manifest.
Without it the cohort cannot be reproduced and neither can anything computed
from it.

**Step 3 — collect each cohort wallet's history.**

```python
from collectors.polymarket_activity import collect_wallet_profile

for wallet in {row.wallet for row in cohort.wallets}:
    profile = collect_wallet_profile(wallet)   # activity + positions + P&L
```

`collect_wallet_profile` requests full history (`start=1`) rather than the
~3-year default and keeps deposits and withdrawals, which is what the
wallet-age and funding-behaviour features need. It also hands back
`first_activity_timestamp`, `funding_events` and `realised_pnl` already
derived.

**Step 4 — anonymise before anything is written outside `data/raw/`.**

```python
from processing.anonymise import anonymise_records, find_identifying_fields

safe = anonymise_records(rows)
assert find_identifying_fields(safe) == {}
```

**Step 5 — freeze.** Version the cohort alongside analysis dataset v1 with the
seed, the market list, the frame size, the stratum counts and a content hash.

---

## 5. API call volume against rate limits

| | |
|---|---|
| Market collection, 9 markets | ~810 requests (the Maduro market took 90) |
| `/activity` — 1,000 wallets × ~20 requests | 20,000 |
| `/closed-positions` — × 2 pages | 2,000 |
| `/positions` — × 1 page | 1,000 |
| **Total** | **≈ 23,810 requests** |
| At our pace (3.3 req/s) | **≈ 2 hours** |

Against the documented ceilings (WS4 §3.3):

| Endpoint | Limit | Ours | Headroom |
|---|---|---|---|
| `/trades` | 200 req/10s | 3.3 req/s | **6× under** |
| `/activity` | 1,000 req/10s | 3.3 req/s | 30× under |
| `/positions` | 150 req/10s | 3.3 req/s | 4× under |
| `/closed-positions` | 150 req/10s | 3.3 req/s | 4× under |

Rate limits are not a constraint on this job. Regenerate the estimate for any
change of size with `estimate_api_calls(cohort, market_collection_calls=810)`.

**The `/activity` figure was corrected on 9 Sep and it is the number to
watch.** The first live SCRUM-45 run cost **2,969 requests for a single
wallet** — 2,945 of them returning nothing, and 2,934 spent walking empty
7-day windows between 1970 and that wallet's first activity, because
wallet-age collection asks for `start=1`. At that rate this cohort would have
been roughly **three million requests and ten days**, not two hours. The
collector now starts with one window and splits only when the 5,000-record
cap is actually reached; on the synthetic 12,000-event wallet that is 144
requests instead of 2,836.

If a future change reintroduces a small fixed `window_s` alongside `start=1`,
this budget is wrong by three orders of magnitude. `tests/test_windowing.py`
guards against it.

Caching means a rerun costs **zero** requests, so the 34 minutes is paid once.

---

## 6. Blockers — read before executing

1. ~~**`fetch_activity` silently truncates at 5,000 records.**~~ **Resolved**
   by SCRUM-45 (`collectors/polymarket_activity.py`). Activity is now
   collected by time window with recursive splitting at the offset cap,
   verified live at 7,374 records across 7 splits, and the old truncating
   stub has been removed. Step 3 above is safe.

2. **Offset paging may be dropping trades.** In the Maduro collection all
   11,588 trades share timestamps with other trades (only 3,374 distinct
   values, up to 98 at one instant), 21 requests paged past offset 0, and 32
   duplicates were removed. Duplicates under offset paging with an unstable
   sort mean records also get *skipped*. If the market trade list is
   incomplete, the sampling frame drawn from it is incomplete too. Test by
   collecting one market twice into different cache directories and comparing.

3. **Mohsen has not reviewed the design** (§2). R5 requires it before the
   cohort is built.

---

## 7. Definition of done

- [ ] §2 reviewed by TL and Mohsen; decision recorded in `docs/decisions/`
- [ ] Blockers 1 and 2 resolved or explicitly accepted in writing
- [ ] Nine markets collected; matched-market criteria recorded
- [ ] Cohort drawn with a recorded seed; stratum counts reported
- [ ] All cohort wallets' activity and closed positions collected
- [ ] `find_identifying_fields` returns empty on everything leaving `data/raw/`
- [ ] Cohort frozen and versioned with analysis dataset v1
- [ ] Biases from §2.2 written up for the report's limitations section
