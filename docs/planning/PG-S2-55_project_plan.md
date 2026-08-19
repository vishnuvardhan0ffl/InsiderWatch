# PG-S2-55 — Project Plan and Work Breakdown

**Project:** *Someone Always Knows — An Analysis of Insider Trading on Polymarket / Kalshi*
**Client:** Adelaide University, College of Engineering & IT
**Industry Supervisor:** Mark Carman · **Academic Supervisor:** Mohsen Dorraki
**Team Leader:** Vish · **Team size:** 5
**Plan version:** v1.0, 17 August 2026
**Horizon:** 6 × 2-week sprints, 17 Aug – 8 Nov 2026

---

## 1. What this document is for

This is the plan of record. It defines what the project will deliver, in what order, who owns each part, and what would cause us to change course. The companion `PG-S2-55_jira_backlog.csv` is the same plan expressed as importable Jira issues — both are generated from one source so they cannot disagree.

**Two things this plan is waiting on.** Neither blocks starting.

1. **Mark Carman's meeting outcomes.** Sprint 1 contains stories that absorb his decisions into a frozen scope statement. Until that lands, the scope in §3 is *proposed*, not agreed.
2. **The V1→V2 continuity answer** (§5). This is the one unknown that could change the project's shape, and Sprint 1 exists largely to close it.

---

## 2. The three deliverables, defined

The brief names three deliverables. Vague deliverables are how capstones fail in week 11, so each is given a concrete minimum and a stretch target here.

### Deliverable 1 — Visualisations

| | |
|---|---|
| **Minimum** | Ten reproducible figures: five exploratory (price, volume, position-size distribution, wallet age vs. position size, trade timing relative to announcement) and five analytical (anomaly score distribution, candidate vs. control comparison, wallet timeline, cumulative position and P&L, abnormal pre-event volume). |
| **Stretch** | Cross-platform Polymarket/Kalshi volume comparison; trader–market network graph. |
| **Done means** | Every figure regenerates from the frozen dataset by a single command, carries a caption stating what it does *and does not* evidence, and displays no wallet-identifying profile data. |
| **Owner** | RV |

### Deliverable 2 — Heuristics

| | |
|---|---|
| **Minimum** | Eight to twelve implemented indicators, each individually testable, each with an empirically derived threshold, each documented with its rationale, failure modes and at least one innocent explanation. |
| **Stretch** | Evidence-weighted composite with per-indicator contribution quantified by ablation. |
| **Done means** | No threshold is an arbitrary round number — every one traces to a baseline percentile or a statistical test on the control population. |
| **Owner** | AN |

### Deliverable 3 — Python CLI

| | |
|---|---|
| **Minimum** | `fetch`, `market`, `trader`, `score`, `export` working end to end from a clean install, with explainable score output. |
| **Stretch** | `scan` across recent markets; `visualise`. |
| **Done means** | Someone outside the team installs and runs it from the README alone. The CLI is a thin wrapper — all logic lives in the library and is unit-tested. |
| **Owner** | DE |

**The CLI is built from Sprint 2 onward, not at the end.** A CLI assembled in the final sprint is demo-ware. Every capability is exposed through it on the day that capability exists.

---

## 3. Scope

### In scope

Polymarket as the primary platform for trader-level behavioural analysis, via the public Data API. Kalshi for market-level anomaly detection and cross-platform validation. Historical analysis on a frozen dataset. Heuristic development, statistical and unsupervised anomaly detection, explainable scoring, candidate ranking, a normal-trading baseline, visualisations, and the Python CLI.

### Out of scope

Proving insider trading. Identifying or deanonymising individuals. Legal conclusions. Causal claims. Automated trading. Financial advice. Production surveillance infrastructure.

### Extensions — only if the core is complete

On-chain funding-trail analysis (one time-boxed spike, Sprint 5, explicitly optional). Wallet clustering. Live monitoring. Dashboards.

### The platform split is forced, not chosen

Kalshi's public trade schema contains no counterparty identifier of any kind. Trader-level analysis on public Kalshi data is impossible — this is a property of the data, not a preference. Kalshi therefore earns its place through two things it *can* do: market-level abnormal-volume detection, and acting as an **independent cross-platform confirmation channel**. An anomaly visible on both venues is materially more defensible than one visible on one, which serves RQ5 directly.

---

## 4. Workstream to sprint mapping

| WS | Workstream | S1 | S2 | S3 | S4 | S5 | S6 |
|---|---|:-:|:-:|:-:|:-:|:-:|:-:|
| WS1 | Requirements and scope | ●● | ● | | | | |
| WS2 | Literature review | ● | ●● | | | | ○ |
| WS3 | Case study investigation | ●● | ●● | | ● | | |
| WS4 | API/blockchain feasibility | ●●● | | | | ○ | |
| WS5 | Data collection pipeline | | ●●● | ●● | | | |
| WS6 | Baseline and control | ● | ● | ●●● | | | |
| WS7 | Feature engineering | | | ●● | ● | ● | |
| WS8 | Heuristic development | | | | ●●● | | ○ |
| WS9 | Anomaly detection | | | | ●●● | | |
| WS10 | Visualisation | | | ● | ●● | ●● | ○ |
| WS11 | Python CLI | | ● | | ●● | ●● | ○ |
| WS12 | Validation and evaluation | | | ● | | ●●● | ● |
| WS13 | Docs, testing, delivery | ●● | ● | ● | | ● | ●●● |

● effort · ○ tail-off

---

## 5. Critical path

```
Mark's decisions ──┐
                   ├─→ Scope frozen ─┐
V1→V2 continuity ──┘                 │
        ↓                            ↓
  Collectors ─→ Frozen dataset ─→ Features ─→ Heuristics ─→ Score ─→ Evaluation ─→ Report
                      ↑                            ↑
              Control cohort ────────────────→ Calibration
```

**The gating unknown.** Whether the Polymarket Data API returns trades predating the 28 April 2026 V2 migration. Our seed cases all sit on V1 contracts. If pre-migration history is unreachable through this route, the case studies become unreachable and the data strategy must change before a line of collector code is written. Sprint 1 closes this. Everything downstream assumes the answer is yes.

**Two things that must not slip:**

- **Frozen dataset by end of Sprint 3.** The analysis *is* the project. A team that spends eight weeks on a beautiful pipeline and two weeks on analysis has built infrastructure, not research.
- **Control cohort by end of Sprint 3.** "Anomalous" is meaningless without a reference population. This is why the sampling frame is designed in Sprint 1, not discovered in Sprint 5.

**Designed early on purpose:** the evaluation strategy (Sprint 3, before results exist) and the control-group sampling frame (Sprint 1). Both determine what data must be collected. Deciding in week 10 that a matched control group is needed is too late to collect one.

---

## 6. Sprint plan

### Sprint 1 · 17–30 Aug · Lock scope, close feasibility
**39 points · 13 stories**

Close the feasibility question, freeze scope against Mark's decisions, and stand up the repository. No analysis work — this sprint buys certainty.

**Milestone M1 (30 Aug):** Scope statement signed off by both supervisors; V1→V2 continuity answered in writing.

### Sprint 2 · 31 Aug–13 Sep · Collection pipeline
**57 points · 12 stories — runs hot**

Collectors for markets, trades, activity and positions, with caching, rate limiting and time-window pagination. CLI skeleton. Case studies 2 and 3 verified.

**Milestone M2 (13 Sep):** Collectors retrieve a full seed-case market end to end and results are cached and reproducible.

### Sprint 3 · 14–27 Sep · Dataset and baseline
**56 points · 10 stories — runs hot**

Cleaning, dataset freeze, control cohort, baseline distributions, first features, first figures. Mid-semester report.

**Milestone M3 (27 Sep):** Analysis dataset v1 and control cohort both frozen and versioned. **This is the most important milestone in the project.**

### Sprint 4 · 28 Sep–11 Oct · Heuristics and detection v1
**54 points · 9 stories — runs hot, no slack**

Deliverable 2 is built here. Indicators implemented, thresholds calibrated against the baseline, statistical and unsupervised layers, explainable composite score, CLI analysis commands.

**Milestone M4 (11 Oct):** A wallet can be scored end to end with a full explanation of every contributing indicator.

### Sprint 5 · 12–25 Oct · Evaluation and discovery
**53 points · 10 stories — runs hot**

Known-case recall, false positive analysis with manual review, sensitivity and ablation, alternative-explanation assessment, discovery run on unseen markets, visualisation suite, reproducibility check.

**Milestone M5 (25 Oct):** Evaluation complete and reproducibility verified from a fresh clone by someone who did not build the pipeline.

### Sprint 6 · 26 Oct–8 Nov · Freeze, write, demo
**44 points · 9 stories**

Code freeze on day one. Report, limitations, ethics, threats to validity, test coverage, demo rehearsal, presentation.

**Milestone M6:** Submission and demonstration.

---

## 7. Team allocation

| Role | Focus | Load |
|---|---|---|
| **TL** — Vish | Scope, supervisor liaison, architecture, integration, methodology sections, demo | 38 pts |
| **DE** — Member 3 | Collectors, storage, cleaning, CLI, reproducibility, tests | 77 pts |
| **AN** — Member 4 | Features, heuristics, scoring, evaluation, results | 77 pts |
| **RV** — Member 5 | Literature, case studies, visualisations, ethics, presentation | 67 pts |
| **BC** — Member 2 | Baseline and control cohort, statistical layer, Kalshi, false positive review, optional on-chain spike | 44 pts |

**The TL figure is deliberately low.** Coordination, supervisor communication, unblocking and review do not appear as story points but consume real time. Do not fill this gap with implementation work.

**Member 2 needs an explicit conversation, not a quiet reallocation.** They were recruited to the project as the blockchain specialist, and the April 2026 migration plus the withdrawal of public subgraphs has made that workstream expensive for little analytical return. Their reallocation to baseline and control is not a demotion — the control cohort is on the critical path and is the single most methodologically demanding piece of work in the project. Frame it that way, and keep the optional on-chain spike in Sprint 5 as a genuine path back if Mark rules blockchain to be core.

---

## 8. Honest notes on the plan

**Four of six sprints run above the assumed 50-point velocity.** This is deliberate visibility rather than an expectation of overtime. Assumed velocity of 50 points implies roughly 12 hours per person per week; recalibrate after Sprint 1 using actual throughput and re-plan from real numbers.

**Designated cuts if a sprint runs long** — take these first, in this order:

- Sprint 2: literature review draft v1 (8) → slips to Sprint 3
- Sprint 3: Kalshi collector (5) → slips to Sprint 4
- Sprint 5: CLI user documentation (3) → slips to Sprint 6; optional on-chain spike (3) → dropped
- Sprint 4: **no designated cut.** Every story is on the critical path. This is the sprint to protect, which means Sprint 3 must not slip.

**Sprint 1 is deliberately light** because scope is not yet frozen and velocity is unknown. Do not fill the gap.

---

## 9. Definition of Done

Applies to every story:

1. Code merged to main with CI green
2. Unit tests for new logic, passing offline against fixtures
3. Any new data field recorded in the data dictionary
4. Any methodological choice documented with its justification
5. No credentials in code, config or git history
6. Reviewed by one team member other than the author
7. Acceptance criteria demonstrably met, not merely asserted

**Additionally, for anything producing an analytical claim:** the claim separates observable evidence, statistical inference and speculation; it uses the agreed non-accusatory terminology; and at least one alternative explanation is recorded.

---

## 10. Risk register

| # | Risk | Impact | Trigger to watch | Response | Owner |
|---|---|---|---|---|---|
| R1 | Data API does not span the V1→V2 boundary | **Critical** — case studies unreachable | Sprint 1 test 6 returns no pre-migration trades | Escalate to both supervisors before coding; evaluate on-chain reconstruction or reselect cases to post-April 2026 | DE |
| R2 | Ground truth too thin to validate anything | High — weakens every claim | Fewer than 3 cases survive verification | Shift emphasis to baseline-deviation evidence and qualitative case analysis; state the limitation prominently | RV |
| R3 | Pipeline overruns and squeezes analysis | High — infrastructure instead of research | M3 not met by 27 Sep | Freeze collector scope immediately; analyse whatever data exists | TL |
| R4 | `takerOnly` default silently biases features | High — invalidates results, hard to detect | Any collector call without an explicit setting | Enforce explicit parameter in code review; record in dataset metadata | DE |
| R5 | Control cohort not defensible | High — "anomalous" becomes unfalsifiable | Sampling design not reviewed before execution | Mohsen reviews the design note before the cohort is built | BC |
| R6 | API change mid-project | Medium | Collector failures or schema drift | Cached raw responses insulate analysis; pin and record API access dates | DE |
| R7 | Member 2 disengages after descope | Medium | Reduced participation after Sprint 1 | Explicit conversation now; ownership of a critical-path workstream; optional spike retained | TL |
| R8 | Confirmation bias in candidate review | Medium — academic credibility | Reviewers know which wallets are seed cases | Blind the manual review where practical; record reviewer knowledge | AN |
| R9 | Scope creep into ML sophistication | Medium | Methods proposed without justification | Every technique must answer "why is this appropriate" in writing or it is not built | TL |
| R10 | Reproducibility claimed but untested | Medium | Fresh-clone test deferred past Sprint 5 | Fixed Sprint 5 story, run by someone who did not build the pipeline | DE |
| R11 | Mid-semester break disrupts a sprint | Low–Medium | Break dates fall inside Sprint 3 or 4 | **Verify the S2 2026 break dates and re-baseline the calendar before importing** | TL |

---

## 11. Stop rules

Agreed in advance, so the decision is not made under deadline pressure:

- **On-chain work** is dropped if not demonstrably useful within its time-box. No extensions.
- **Machine learning** is not added beyond Isolation Forest and LOF unless a written justification tied to a research question exists.
- **A new case study** is not added after Sprint 4.
- **Any extension** is dropped the moment a core deliverable is behind.

---

## 12. Assumptions to verify

These are assumptions, not facts. Check each before relying on it.

1. Semester 2 concludes with submission in early November 2026 — **confirm the exact date**.
2. Mid-semester break dates are unknown to this plan — **confirm and re-baseline** (R11).
3. The team can sustain roughly 12 hours per person per week.
4. Mark Carman accepts the proposed platform split.
5. The Polymarket Data API remains publicly accessible without authentication for the project's duration.
6. Sufficient verifiable case studies exist to seed the work — being tested in Sprints 1–2.

---

## 13. Next 72 hours

1. **Verify the semester end date and mid-semester break**, then re-baseline the sprint calendar. Do this before importing the backlog — shifting dates afterwards is painful.
2. **Import the backlog CSV** and map the five role codes to real names.
3. **Start the two Sprint 1 blockers immediately**: RV sources the three seed condition IDs, then DE runs `verify_apis.py --market` against each. This is roughly a day's work between two people and it gates the project.
4. **Have the conversation with Member 2** before the sprint planning session, not during it.
5. **Send me Mark's meeting notes** so the scope statement can be written against his actual decisions rather than the brief's assumptions.

---

## Appendix — companion artefacts

| File | Purpose |
|---|---|
| `PG-S2-55_jira_backlog.csv` | 13 epics, 63 stories, Jira-importable |
| `PG-S2-55_jira_backlog.md` | Same backlog, readable and reviewable |
| `generate_backlog.py` | Single source for both; edit this, not the outputs |
| `WS4_data_feasibility.md` | Feasibility study underpinning the scope decisions |
| `verify_apis.py` | Verification suite that closes the WS4 open questions |
