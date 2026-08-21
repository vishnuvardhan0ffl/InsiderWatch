# WS4 Test 6 — V1→V2 Historical Continuity: Finding

**Project:** PG-S2-55 — *Someone Always Knows: An Analysis of Insider Trading on Polymarket / Kalshi*
**Question:** Does the Polymarket Data API return trade history predating the CLOB V1→V2 cutover of 28 April 2026, ~11:00 UTC?
**Date of observation:** 20 August 2026
**Status:** **Confirmed by a scripted run.** Evidence: `data/external/feasibility_check_2026-08-20.json`
**Closes:** Risk **R1** (project plan §10), WS4 open questions **4** and **7**

---

## 1. Answer

# YES.

Pre-migration history is fully reachable through the public, unauthenticated Data API. All three seed condition IDs return trade records. The schema is identical either side of the cutover. Wallet identity is stable across it. Realised P&L is served for positions closed eighteen months before it.

**The data strategy does not change. The collector can be written against the Data API as planned.**

This was the highest-value unknown in the project. It is now closed in our favour, and it is closed with evidence rather than with documentation.

---

## 2. Evidence

**Citable artefact: `data/external/feasibility_check_2026-08-20.json`** — produced by
`verify_apis.py`, 8 tests, 0 FAIL, run 2026-08-20 15:57 UTC. Cite this in the
methodology section.

`feasibility_check_2026-08-20_manual.json` is the earlier interactive record. Keep
it for provenance, but it is superseded — one of its caveats turned out to matter,
see §7.

Scripted results, verbatim:

| Test | Result |
|---|---|
| 6a Maduro `0xd1e4e03a…` | pre-migration trades = True, earliest 2026-01-30T10:15:32Z |
| 6a Machado `0x14a3dfeb…` | pre-migration trades = True, earliest 2025-10-10T10:05:28Z |
| 6a US x Iran `0x4c5701bc…` | pre-migration trades = True, earliest 2026-04-11T00:06:43Z |
| 6b boundary probe | 100 trades in the 12h before the cutover, 100 in the 24h after |
| 6c wallet identity | **4 of 5** sampled wallets active in both eras under the same address |
| 8 scope trap | **TRAP CONFIRMED** — `start`/`end` ignored without `user=`/`market=` |

Headline: `pre-migration history reachable = YES`.

The detail below is from the interactive session and adds the depth probes and
field-level observations the scripted suite does not record.

### 2.1 Seed markets — all three return pre-migration trades

| Seed case | Earliest trade observed | Latest trade observed | Pre-cutover? |
|---|---|---|---|
| Maduro released by 31 Jan 2026 | 2026-01-30 11:46:48Z | 2026-02-01 07:38:08Z | Yes |
| Machado — Nobel Peace Prize 2025 | **2025-08-29 00:12:13Z** | 2025-10-10 12:05:56Z | Yes |
| US x Iran ceasefire by 7 Apr | 2026-04-11 00:09:31Z | 2026-04-11 00:30:01Z | Yes |

The Machado figure is the one that matters most for us. The prize was announced on 10 October 2025; trades are retrievable from **six weeks before the announcement**. That is the entire pre-announcement window the case study needs, and it is exactly the window RQ2 asks about.

Field set on pre-migration records is identical to current records, including `transactionHash` — so V1-era trades can still be cross-referenced on Polygon if we later want to.

### 2.2 No gap at the boundary

Probe market: *Strait of Hormuz traffic returns to normal by May 15?* (`0xffe381a8…`), opened 22 April 2026, resolved 15 May 2026 — one `conditionId` spanning both contract eras.

- 09:47–10:58 UTC on 28 April 2026 (final hour before cutover): dense trade records returned.
- 09:40–10:59 UTC on 29 April 2026 (day after cutover): dense trade records returned.

One market, one identifier, both eras. The API abstracts the contract migration away entirely.

### 2.3 `proxyWallet` survives the migration — WS4 open question 7, answered

Wallet `0x07d126ea…` returns trades up to 10:59:52 UTC on 28 April 2026 and again from 18–20 August 2026, under **the same address**.

This matters more than it looks. Had proxy wallets been reissued at migration, every trader-level feature spanning the boundary — wallet age, trading frequency, repeated success, portfolio concentration — would have needed an identity join we could not have built from public data. We do not need one.

### 2.4 `/activity` and `/closed-positions` have the same coverage

- `/activity` returns pre-cutover records with `TRADE`, `REDEEM`, `YIELD` types and post-cutover records including `DEPOSIT`. Wallet-age and funding-behaviour features are obtainable for pre-migration wallets.
- `/closed-positions` returns a realised-P&L record for the **2024 US Presidential Election** market — `avgPrice` 0.5349, `realizedPnl` 43.88, closed 6 November 2024. Profitability features work on pre-migration cases.

One null result worth recording so nobody re-discovers it: a wallet with pre-migration trades returned an **empty** `/closed-positions` array. That is a property of that wallet's book, not an API limitation. Do not let it be written up as one.

---

## 3. A bug in our own test 6, which would have produced the wrong answer

Worth recording plainly, because it nearly cost us a supervisor escalation on a false alarm.

The version of `verify_apis.py` in the repo before 20 August searched a window of `cutover − 30 days .. cutover − 1` for pre-migration trades. Two of the three seed markets resolved well outside that window:

| Seed case | Last trade | Days before cutover | Inside the old 30-day window? |
|---|---|---|---|
| Machado — Nobel Peace Prize 2025 | 2025-10-10 | ~200 | **No** |
| Maduro released by 31 Jan 2026 | 2026-02-01 | ~86 | **No** |
| US x Iran ceasefire by 7 Apr | 2026-04-11 | 17 | Yes |

Run as written with all three seed IDs, test 6 would have reported `pre_migration_trades_found = False` for the Nobel and Venezuela cases. Under the "any market found" rule it would still have passed overall — but the per-market lines in the committed evidence file would have said, in writing, that our two strongest seed cases had no reachable history. That is the kind of artefact that gets quoted in a meeting.

The window is now `1 .. cutover − 1` — all retrievable history. `tests/test_verify_apis.py::test_pre_window_covers_all_retrievable_history` asserts it with two real seed-case timestamps so it cannot silently regress.

Two smaller fixes went in alongside it. Test 7 now refuses to run unscoped: the 19 August evidence file records `takerOnly` true = 1000, false = 1000, differential = 0, which reads as "no bias risk" but is really the page cap plus the scope trap below — the run never filtered by market at all. And test 3 now distinguishes an empty `/closed-positions` array from an API failure, because a wallet with no closed positions is not evidence of missing history.

---

## 4. Unplanned finding — this one bites, and it bites silently

**`start` / `end` appear to be ignored on an unscoped `/trades` call.**

| Call | Window requested | Newest record returned | Window honoured |
|---|---|---|---|
| `/trades?start=1730000000&end=1730100000` | Oct 2024 | 2026-08-20 15:17:55Z | **No** |
| `/trades?start=1777280000&end=1777374000` | Apr 2026 | 2026-08-20 15:17:33Z | **No** |
| `/trades?market=0xdd22472e…&start=1730000000&end=1730100000` | Oct 2024 | 2024-10-28 05:20:00Z | Yes |

Two different historical windows both returned current-day trades, so this is not a caching artefact. Add `user=` or `market=` and the window is respected.

**Consequence:** a collector that walks the global feed by time window returns *today's* data while looking entirely healthy. No error, no empty array, no warning — just a silently wrong dataset. This is the same failure class as the `takerOnly` default (risk R4), and it deserves the same treatment.

**Action:** every historical collector call must carry `user=` or `market=`. Enforce in code review; record in the data dictionary; assert it in the collector itself.

Confidence: two observations plus one control, from a single session. `verify_apis.py` test 8 re-tests it on every run. Do not put it in the report until that run is committed.

---

## 5. Contingency routes — recorded even though we do not need them

The acceptance criteria ask for at least two alternative routes before collector code is written. The answer came back YES, so these are contingency only. Recording them now means we are not designing under pressure if the API changes mid-project (risk R6).

**Route A — Goldsky Turbo Pipelines.** Full historical indexing, both contract eras. Rejected as a primary route: requires an account, an API key and our own destination database, with user-positions backfill flagged at ~1.2 billion entities. Capstone-infeasible on cost and time; viable only if someone else funds and hosts it.

**Route B — Direct on-chain reconstruction from Polygon.** Read `OrderFilled` events from the V1 CTF Exchange for pre-April-2026 markets and V2 contracts thereafter, resolving `proxyWallet` through the two factory contracts. Fully public, no gatekeeper, and it is the only route that survives the Data API being withdrawn. Costs: two contract eras, two collateral tokens (USDC.e → pUSD), unverified V1 addresses, and an RPC provider. Estimate three to four weeks for one member — which is precisely the "four weeks of infrastructure producing no analytical output" scenario WS4 §1.3 warned about. Time-box it if it is ever triggered.

**Route C — narrow the case window.** Reselect case studies to post-April-2026 events only. Cheapest by far and needs no new engineering, but it discards the Nobel and Venezuela cases, which are the strongest documented seeds we have. Last resort.

**Trigger for any of these:** `verify_apis.py` returning a non-YES headline on a scheduled re-run. Until then, build on the Data API.

---

## 6. What this changes

| Item | Before | After |
|---|---|---|
| Risk R1 (Data API misses the V1→V2 boundary) | Critical, unknown probability | **Closed** — retire from the active register, keep the entry with the evidence link |
| WS4 open question 4 (continuity) | Open, highest priority | **Answered: continuous** |
| WS4 open question 7 (`proxyWallet` stability) | Open | **Answered: stable** |
| Blockchain workstream | Blocked on a scope decision | Confirmed **optional extension**. The argument in WS4 §1.2 now holds empirically: the off-chain API covers the core feature set for pre-migration cases too |
| Collector design | Pending feasibility | **Unblocked.** Build against the Data API, with mandatory `user=`/`market=` scoping and explicit `takerOnly` |
| Supervisor escalation | Contingent on a NO | **Not required.** Report as a closed risk at the next meeting, not as an issue |

---

## 7. Still open

| # | Question | Status |
|---|---|---|
| U1 | Is `limit` honoured above 100? | **Closed — yes.** The scripted probe returned `{100: 100, 500: 500, 1000: 1000}`. The uniform 100-record results in the manual record were a truncation artefact of the tool used to capture them, exactly as that file warned. Nothing in the continuity answer depended on them |
| U2 | `takerOnly` true/false differential | **Still open, and the first two attempts were not evidence.** Both runs returned true = 1000, false = 1000, differential = 0 — two censored counts that happened to be equal, which says nothing about maker-side fills. Test 7 now shrinks the window until the count fits under the page cap before comparing |
| U3 | Maximum retrievable depth — confirmed to Oct 2024, floor not probed | Open. Bounds the control-cohort sampling frame. Binary-search `start`/`end` on a 2023-era market |

U2 is the one that matters now. Risk R4 says the `takerOnly` default silently
biases every downstream feature, and we still have no measurement of how large
that bias is. A `differential = 0` line in a committed evidence file is worse
than no line at all — it reads as reassurance, and the next person to open that
file will not know the counts were censored.

The warning generalises: **a count that equals the page limit is not a count.**
Anywhere the pipeline compares record counts, it must first establish that
neither side hit a cap.

---

## 8. Method note

These observations were captured interactively over public, unauthenticated endpoints at a few requests per second — orders of magnitude below the documented 200 req/10s limit on `/trades`. No credentials were used. No rate limit was approached. Nothing here required or used non-public data.

Two honest limitations on this document:

1. **Record counts above 100 are not reliable.** They are counts of objects visible in the summarised response and may reflect truncation rather than the API. Timestamps, field names and empty/non-empty verdicts *are* reliable — and the continuity answer rests only on those.
2. **Sample sizes are small.** One probe market, one continuity wallet, three seed markets. The direction of the answer is not in doubt — a "no pre-migration data" API cannot return August 2025 trades — but the report should cite the scripted run, not this memo.

`verify_apis.py` automates all of it. Run it, commit `data/external/feasibility_check_<date>.json`, and cite that.
