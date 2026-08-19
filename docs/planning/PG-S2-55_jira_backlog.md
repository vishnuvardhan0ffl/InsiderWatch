# PG-S2-55 — Jira Backlog

*Someone Always Knows: An Analysis of Insider Trading on Polymarket / Kalshi*

Generated from `generate_backlog.py`. Edit the script, not this file — the CSV and this document are emitted from one definition so they cannot drift.

## Roles

- **TL** — Team Leader / Integration (Vish)
- **DE** — Data Engineering — APIs, collectors, storage
- **BC** — Baseline & Control (formerly Blockchain)
- **AN** — Analytics — features, detection, evaluation
- **RV** — Research & Visualisation — literature, cases, figures

Map these to real names before import. Roles are used rather than names so the backlog survives a reallocation.

## Epics

| Key | Epic | Purpose |
|---|---|---|
| E1 | WS1 Requirements and Scope | Agree and freeze the problem definition, platform scope and success criteria with both supervisors. |
| E2 | WS2 Literature Review | Establish the academic grounding: informed trading, prediction markets, anomaly detection, blockchain analytics. |
| E3 | WS3 Case Study Investigation | Build an evidence-graded register of known or alleged suspicious prediction-market trading. |
| E4 | WS4 API and Blockchain Feasibility | Prove empirically what data is obtainable before any pipeline is built. |
| E5 | WS5 Data Collection Pipeline | Reproducible collectors, caching, cleaning and normalisation into an analysis dataset. |
| E6 | WS6 Baseline and Control Dataset | Define and build a defensible 'normal trader' reference population. |
| E7 | WS7 Feature Engineering | Derive the trader, trade, market and outcome features the detection layer consumes. |
| E8 | WS8 Heuristic Development | DELIVERABLE 2. Documented, calibrated, empirically justified suspicion indicators. |
| E9 | WS9 Statistical and Anomaly Detection | Statistical tests and unsupervised methods producing an explainable composite score. |
| E10 | WS10 Visualisation | DELIVERABLE 1. Figures evidencing anomalous trading behaviour. |
| E11 | WS11 Python CLI | DELIVERABLE 3. Modular command-line application over the analysis library. |
| E12 | WS12 Validation and Evaluation | Evidence that the heuristics work, and honest accounting of where they do not. |
| E13 | WS13 Documentation, Testing, Delivery | Repository quality, reproducibility, final report, presentation and demo. |

## Sprint 1 — Lock scope, close feasibility

**17 Aug – 30 Aug 2026** · 13 stories · **39 points**

### Run the WS4 API verification suite

- **Epic:** E4 — WS4 API and Blockchain Feasibility
- **Owner:** DE · **Points:** 3 · **Priority:** Highest
- **Labels:** `feasibility`, `blocker`

**Description.** Execute verify_apis.py from a normal network connection and commit the JSON evidence file to data/external/. The WS4 feasibility study is documentation-verified only; nothing has been confirmed by a live HTTP response.

**Acceptance criteria.** Script runs to completion; JSON evidence file committed; every FAIL triaged in writing as either a real limitation or a script defect.

### Source condition IDs for the three seed markets

- **Epic:** E4 — WS4 API and Blockchain Feasibility
- **Owner:** RV · **Points:** 2 · **Priority:** Highest
- **Labels:** `feasibility`, `blocker`

**Description.** Locate Polymarket condition IDs and resolution dates for one Venezuela/Maduro market, one Nobel Prize market and one Google search-rankings market, all predating the 28 Apr 2026 V2 migration. Route is the Gamma API markets/events/search endpoints.

**Acceptance criteria.** Three condition IDs recorded with market title, slug, resolution date and the API call used to find each; committed as data/external/seed_markets.json.

### Resolve the V1 to V2 historical continuity question

- **Epic:** E4 — WS4 API and Blockchain Feasibility
- **Owner:** DE · **Points:** 3 · **Priority:** Highest
- **Labels:** `feasibility`, `blocker`, `critical-path`

**Description.** Run verify_apis.py --market for each seed condition ID to determine whether the Data API returns trades predating the 28 Apr 2026 cutover. This is the single highest-value unknown in the project: if pre-migration history is unreachable, the entire data strategy changes.

**Acceptance criteria.** A written yes/no answer with evidence attached; if NO, an escalation note to both supervisors with at least two proposed alternative routes before any collector code is written.

### Reconcile scope against the Mark Carman meeting outcomes

- **Epic:** E1 — WS1 Requirements and Scope
- **Owner:** TL · **Points:** 2 · **Priority:** Highest
- **Labels:** `scope`

**Description.** Convert the first industry-supervisor meeting notes into a decision log: what was agreed, what changed from the brief, what remains open. Flag any decision that conflicts with the WS4 findings.

**Acceptance criteria.** Decision log committed to docs/; every one of the 15 meeting questions marked agreed, deferred or not-discussed.

### Produce the agreed scope statement and obtain sign-off

- **Epic:** E1 — WS1 Requirements and Scope
- **Owner:** TL · **Points:** 3 · **Priority:** Highest
- **Labels:** `scope`, `milestone`

**Description.** Write the one-page scope statement: problem definition, in/out of scope, platform split, deliverable definitions, success criteria. Circulate to Mark Carman and Mohsen Dorraki for explicit confirmation.

**Acceptance criteria.** Scope statement committed; written confirmation from both supervisors recorded in docs/decisions/; scope treated as frozen thereafter, changes only via documented change request.

### Decide the blockchain workstream: core or extension

- **Epic:** E1 — WS1 Requirements and Scope
- **Owner:** TL · **Points:** 2 · **Priority:** Highest
- **Labels:** `scope`, `risk`

**Description.** Given the April 2026 V2 migration, the withdrawn Goldsky public subgraphs and the proxy-wallet indirection, make an explicit in/out decision on on-chain analysis. Record the reasoning either way.

**Acceptance criteria.** Written decision with cost justification; if IN, a named owner and a time-box; if OUT, the reallocation of that capacity is documented.

### Scaffold the repository, CI and contribution standards

- **Epic:** E13 — WS13 Documentation, Testing, Delivery
- **Owner:** DE · **Points:** 3 · **Priority:** High
- **Labels:** `infrastructure`

**Description.** Create the module structure (cli/, collectors/, processing/, analysis/, visualisation/, data/, tests/, config/, docs/). Add requirements.txt, .gitignore, .env.example, pre-commit with formatting and linting, and a CI job running tests on push.

**Acceptance criteria.** Fresh clone plus pip install -r requirements.txt succeeds; CI green on main; no credentials anywhere in the repository or its history.

### Draft the data dictionary skeleton

- **Epic:** E13 — WS13 Documentation, Testing, Delivery
- **Owner:** AN · **Points:** 2 · **Priority:** High
- **Labels:** `documentation`

**Description.** One row per field the project will store: source endpoint, field name, type, units, nullability, and the confirmed API field it derives from. Seeded from the confirmed field lists in the WS4 study.

**Acceptance criteria.** Skeleton covers every field in the Data API trades, activity, positions and closed-positions responses; committed to docs/data_dictionary.md.

### Define the case register schema and evidence grading

- **Epic:** E3 — WS3 Case Study Investigation
- **Owner:** RV · **Points:** 3 · **Priority:** High
- **Labels:** `research`, `methodology`

**Description.** Specify the fields of the case-study register and the confidence taxonomy: Confirmed/officially investigated, Strongly documented allegation, Media-reported, Exploratory candidate, Control/normal.

**Acceptance criteria.** Schema and taxonomy documented with a worked example; grading rules explicit enough that two team members independently grade the same case identically.

### Verify seed case 1 — Venezuela / Maduro

- **Epic:** E3 — WS3 Case Study Investigation
- **Owner:** RV · **Points:** 5 · **Priority:** High
- **Labels:** `research`, `case-study`

**Description.** Independently verify the alleged event. Establish the information-release timestamp from primary sources. Distinguish confirmed fact from allegation. Do not carry the project brief's claims forward unverified.

**Acceptance criteria.** Register entry complete with primary sources cited, confidence grade assigned, and at least two alternative explanations recorded; anything unverifiable explicitly marked 'This remains unverified'.

### Establish the literature search strategy and source log

- **Epic:** E2 — WS2 Literature Review
- **Owner:** RV · **Points:** 3 · **Priority:** Medium
- **Labels:** `research`

**Description.** Define databases, search strings and inclusion/exclusion criteria across: informed trading, prediction market efficiency, market manipulation detection, blockchain analytics, unsupervised anomaly detection.

**Acceptance criteria.** Search strategy documented and reproducible; source log started with at least 15 peer-reviewed candidates classified by relevance.

### Design the control-group sampling frame

- **Epic:** E6 — WS6 Baseline and Control Dataset
- **Owner:** BC · **Points:** 5 · **Priority:** High
- **Labels:** `methodology`, `critical-path`

**Description.** Specify how a defensible 'normal trader' population is drawn. Leaderboard sampling is biased toward winners; recent-trade sampling is biased toward the active. Propose and justify a scheme that survives a methods critique.

**Acceptance criteria.** Design note stating the sampling unit, frame, method, known biases and how each is mitigated or disclosed; reviewed by TL and Mohsen before execution.

### Write the ethics and data-handling protocol

- **Epic:** E13 — WS13 Documentation, Testing, Delivery
- **Owner:** TL · **Points:** 3 · **Priority:** High
- **Labels:** `ethics`, `documentation`

**Description.** Document the anonymisation rule (hash wallet identifiers and never publish name/pseudonym/bio profile fields), the no-deanonymisation commitment, terminology rules, and the retention plan.

**Acceptance criteria.** Protocol committed; terminology rules cover every accusatory phrase to be avoided; approved by TL and noted with Mohsen.


## Sprint 2 — Collection pipeline

**31 Aug – 13 Sep 2026** · 12 stories · **57 points**

### Build the Gamma market and event collector

- **Epic:** E5 — WS5 Data Collection Pipeline
- **Owner:** DE · **Points:** 5 · **Priority:** Highest
- **Labels:** `pipeline`, `critical-path`

**Description.** Collect market and event metadata: condition IDs, slugs, titles, tags, liquidity, volume, creation and resolution dates. Support keyset pagination.

**Acceptance criteria.** Collector retrieves a named market by slug and by condition ID; output schema matches the data dictionary; unit tests pass against recorded fixtures.

### Build the trade collector with time-window pagination

- **Epic:** E5 — WS5 Data Collection Pipeline
- **Owner:** DE · **Points:** 8 · **Priority:** Highest
- **Labels:** `pipeline`, `critical-path`

**Description.** Collect trades from data-api /trades for a wallet or market. Offset is capped at 10,000, so pagination must walk start/end time windows, each with its own offset budget. takerOnly must be set explicitly, never left to default.

**Acceptance criteria.** Retrieves >10,000 trades for a high-volume market without loss or duplication; takerOnly setting recorded in output metadata; duplicate-detection test passes.

### Build the activity and positions collectors

- **Epic:** E5 — WS5 Data Collection Pipeline
- **Owner:** DE · **Points:** 5 · **Priority:** Highest
- **Labels:** `pipeline`, `critical-path`

**Description.** Collect /activity (with excludeDepositsWithdrawals=false and start=1 for full history), /positions and /closed-positions. Activity is the off-chain route to wallet age and funding behaviour.

**Acceptance criteria.** For a given wallet the collector returns first-activity timestamp, full funding event list and realised PnL per closed position; offset cap of 5,000 on activity handled by time windowing.

### Implement the raw storage and caching layer

- **Epic:** E5 — WS5 Data Collection Pipeline
- **Owner:** DE · **Points:** 5 · **Priority:** High
- **Labels:** `pipeline`, `reproducibility`

**Description.** Cache every API response to local raw storage keyed by endpoint and parameters, so analyses are reproducible without re-hitting the API and a rate-limit event never loses work.

**Acceptance criteria.** Re-running an identical collection performs zero network calls; raw responses retained unmodified with retrieval timestamp; cache location configurable.

### Add rate limiting, retry and error handling

- **Epic:** E5 — WS5 Data Collection Pipeline
- **Owner:** DE · **Points:** 3 · **Priority:** High
- **Labels:** `pipeline`

**Description.** Token-bucket client-side limiting well below documented ceilings (Data API /trades is 200 req/10s), exponential backoff on 429 and 5xx, and structured logging of every failed call.

**Acceptance criteria.** A forced 429 recovers without data loss; sustained collection runs one hour without manual intervention; all failures logged with endpoint and parameters.

### Build the CLI skeleton with fetch commands

- **Epic:** E11 — WS11 Python CLI
- **Owner:** DE · **Points:** 5 · **Priority:** High
- **Labels:** `deliverable-3`, `cli`

**Description.** Stand the CLI up now, not at the end, so every capability is exposed from the day it exists. Subcommand structure plus fetch market / fetch trader.

**Acceptance criteria.** insiderwatch fetch market <id> and fetch trader <wallet> both write cached output; --help documents every command; CLI is a thin wrapper containing no analysis logic.

### Verify seed cases 2 and 3 — Nobel Prize and Google rankings

- **Epic:** E3 — WS3 Case Study Investigation
- **Owner:** RV · **Points:** 5 · **Priority:** High
- **Labels:** `research`, `case-study`

**Description.** Same verification protocol as case 1. Establish information-release timestamps from primary sources and grade evidence confidence.

**Acceptance criteria.** Two register entries complete with primary sources, confidence grades and alternative explanations; unverifiable elements explicitly marked.

### Define the event timeline construction method

- **Epic:** E3 — WS3 Case Study Investigation
- **Owner:** RV · **Points:** 3 · **Priority:** High
- **Labels:** `methodology`, `critical-path`

**Description.** Specify how an event timeline is built and, critically, how the information-release timestamp is determined and sourced. Every downstream timing feature depends on this being defensible.

**Acceptance criteria.** Method documented with the timestamp-sourcing hierarchy; applied consistently to all three seed cases; ambiguity in any timestamp explicitly recorded as uncertainty.

### Produce literature review draft v1

- **Epic:** E2 — WS2 Literature Review
- **Owner:** RV · **Points:** 8 · **Priority:** Medium
- **Labels:** `research`

**Description.** First full draft covering informed trading theory, prediction market efficiency, detection methodology and anomaly detection technique selection. Must justify why our chosen methods are appropriate, not merely list them.

**Acceptance criteria.** Draft covers all four areas with at least 20 peer-reviewed sources; every methodological choice in the project traceable to a cited justification; no fabricated citations.

### Specify the control cohort extraction

- **Epic:** E6 — WS6 Baseline and Control Dataset
- **Owner:** BC · **Points:** 5 · **Priority:** High
- **Labels:** `methodology`

**Description.** Turn the approved sampling design into an executable specification: cohort size, stratification, exclusion rules, and the exact collector calls required.

**Acceptance criteria.** Specification is precise enough for another team member to execute it without asking questions; expected API call volume estimated against rate limits.

### Set up the test harness and recorded fixtures

- **Epic:** E13 — WS13 Documentation, Testing, Delivery
- **Owner:** TL · **Points:** 3 · **Priority:** High
- **Labels:** `testing`, `infrastructure`

**Description.** pytest structure plus recorded API response fixtures so tests run offline and deterministically in CI.

**Acceptance criteria.** Test suite runs with no network access; fixtures cover trades, activity, positions and an error response; CI enforces the suite on every push.

### Confirm the Kalshi role and market-level scope

- **Epic:** E1 — WS1 Requirements and Scope
- **Owner:** TL · **Points:** 2 · **Priority:** High
- **Labels:** `scope`

**Description.** Kalshi public trades carry no counterparty identifier, so trader-level work is impossible there. Confirm with Mark that Kalshi serves market-level anomaly detection and cross-platform validation.

**Acceptance criteria.** Written confirmation recorded; if agreed, the Kalshi collector story is committed to Sprint 3; if not, an alternative role for Kalshi is documented.


## Sprint 3 — Dataset and baseline

**14 Sep – 27 Sep 2026** · 10 stories · **56 points**

### Build the cleaning and normalisation module

- **Epic:** E5 — WS5 Data Collection Pipeline
- **Owner:** DE · **Points:** 5 · **Priority:** Highest
- **Labels:** `pipeline`, `critical-path`

**Description.** Type coercion, timestamp normalisation to UTC, deduplication, outcome and side normalisation, handling of splits/merges/redemptions when reconstructing positions.

**Acceptance criteria.** Cleaning is idempotent; every transformation logged; a validation report flags nulls, duplicates and out-of-range values; rules documented in the data dictionary.

### Build and freeze analysis dataset v1

- **Epic:** E5 — WS5 Data Collection Pipeline
- **Owner:** DE · **Points:** 5 · **Priority:** Highest
- **Labels:** `pipeline`, `milestone`, `critical-path`

**Description.** Assemble the first frozen analysis dataset covering the seed cases and the control cohort. Freezing matters: analysis run against a moving dataset is not reproducible.

**Acceptance criteria.** Dataset versioned with a manifest recording row counts, date range, collection timestamps and a content hash; all subsequent analysis cites the version.

### Build the control cohort

- **Epic:** E6 — WS6 Baseline and Control Dataset
- **Owner:** BC · **Points:** 8 · **Priority:** Highest
- **Labels:** `methodology`, `critical-path`

**Description.** Execute the approved extraction specification to produce the reference population of ordinary traders.

**Acceptance criteria.** Cohort built to the specified size and stratification; sampling biases documented; cohort frozen and versioned alongside the analysis dataset.

### Compute baseline distributions and descriptive statistics

- **Epic:** E6 — WS6 Baseline and Control Dataset
- **Owner:** BC · **Points:** 5 · **Priority:** Highest
- **Labels:** `methodology`, `critical-path`

**Description.** Characterise normal behaviour: position size, wallet age, markets traded, portfolio concentration, win rate, return distribution, trade timing. This is what 'anomalous' is measured against.

**Acceptance criteria.** Distribution summary for every baseline feature with percentiles; committed as results/baseline_summary; findings written up in plain language for the report.

### Implement the trader and wallet feature module

- **Epic:** E7 — WS7 Feature Engineering
- **Owner:** AN · **Points:** 8 · **Priority:** Highest
- **Labels:** `features`, `critical-path`

**Description.** Wallet age, first-activity timestamp, prior market count, prior trade count, historical volume, mean and max position size, portfolio concentration, win rate, trading frequency, dormancy-then-activity.

**Acceptance criteria.** Every feature unit-tested against a hand-computed fixture; every feature traceable to a confirmed API field in the data dictionary; no feature computed from data we cannot obtain.

### Implement the trade and market feature module

- **Epic:** E7 — WS7 Feature Engineering
- **Owner:** AN · **Points:** 5 · **Priority:** High
- **Labels:** `features`

**Description.** Trade size, entry price, implied probability, time-before-event, deviation from the trader's own norm, position as a share of market liquidity, plus market liquidity, volume, spread, volatility and abnormal volume.

**Acceptance criteria.** Features unit-tested; time-before-event uses the timestamp method from WS3; abnormal volume defined against a stated baseline window.

### Produce the exploratory visualisation set

- **Epic:** E10 — WS10 Visualisation
- **Owner:** RV · **Points:** 5 · **Priority:** High
- **Labels:** `deliverable-1`, `visualisation`

**Description.** First figures: market probability over time, volume over time, position size distribution, wallet age versus position size, trade timing relative to announcement.

**Acceptance criteria.** Five figures produced from the frozen dataset; each regenerable by a single command; no wallet-identifying profile data displayed.

### Build the Kalshi market-level collector

- **Epic:** E5 — WS5 Data Collection Pipeline
- **Owner:** BC · **Points:** 5 · **Priority:** Medium
- **Labels:** `pipeline`, `kalshi`

**Description.** Collect Kalshi market metadata and public trades for market-level anomaly analysis and cross-platform comparison. No trader-level work is possible here.

**Acceptance criteria.** Collector retrieves trades by ticker with cursor pagination; is_block_trade preserved; retrievable historical depth measured and documented.

### Design the evaluation strategy

- **Epic:** E12 — WS12 Validation and Evaluation
- **Owner:** AN · **Points:** 5 · **Priority:** Highest
- **Labels:** `evaluation`, `methodology`, `critical-path`

**Description.** Ground truth is the project's hardest problem, so the evaluation design must exist before results, not after. Specify how heuristics will be judged given only a handful of labelled cases.

**Acceptance criteria.** Strategy covers known-case recall, control-group false positive rate, threshold sensitivity, ablation and qualitative review; explicitly states what the project cannot claim.

### Produce the mid-semester progress report

- **Epic:** E13 — WS13 Documentation, Testing, Delivery
- **Owner:** TL · **Points:** 5 · **Priority:** High
- **Labels:** `documentation`, `milestone`

**Description.** Progress against plan, findings to date, changes to scope, risks realised, and the plan for the remaining sprints.

**Acceptance criteria.** Report submitted to both supervisors by the mid-semester deadline; includes the WS4 findings and any scope changes arising from them.


## Sprint 4 — Heuristics and detection v1

**28 Sep – 11 Oct 2026** · 9 stories · **54 points**

### Implement the candidate heuristic indicators

- **Epic:** E8 — WS8 Heuristic Development
- **Owner:** AN · **Points:** 8 · **Priority:** Highest
- **Labels:** `deliverable-2`, `heuristics`, `critical-path`

**Description.** Implement the indicator set as individually testable functions: new wallet, large first trade, position large relative to liquidity, extreme concentration, low-liquidity market, trade shortly before announcement, unusual directional confidence, outsized profit, abnormal frequency, behavioural change point, trading against consensus.

**Acceptance criteria.** Each indicator is a separate documented function with unit tests; each returns a value plus the evidence supporting it; none is asserted as proof of misconduct.

### Calibrate indicator thresholds against the baseline

- **Epic:** E8 — WS8 Heuristic Development
- **Owner:** AN · **Points:** 5 · **Priority:** Highest
- **Labels:** `deliverable-2`, `heuristics`, `methodology`

**Description.** Derive thresholds empirically from the control cohort distributions rather than choosing round numbers. Record the derivation for every threshold.

**Acceptance criteria.** Every threshold traceable to a baseline percentile or statistical test; no arbitrary constants; calibration reproducible from the frozen dataset.

### Document and justify the heuristic set

- **Epic:** E8 — WS8 Heuristic Development
- **Owner:** AN · **Points:** 5 · **Priority:** Highest
- **Labels:** `deliverable-2`, `documentation`

**Description.** Deliverable 2 in written form: what each indicator measures, why it plausibly relates to informed trading, how it was calibrated, its known failure modes and its false positive behaviour.

**Acceptance criteria.** Every indicator documented to that structure; at least one plausible innocent explanation recorded per indicator; ready to drop into the final report.

### Build the statistical anomaly layer

- **Epic:** E9 — WS9 Statistical and Anomaly Detection
- **Owner:** BC · **Points:** 5 · **Priority:** High
- **Labels:** `detection`

**Description.** Z-scores, percentile ranks and IQR outlier detection per feature against the baseline population, with the distributional assumptions of each stated and checked.

**Acceptance criteria.** Layer outputs a per-feature anomaly value with the reference distribution recorded; non-normal features handled explicitly rather than assumed normal.

### Add unsupervised anomaly detection

- **Epic:** E9 — WS9 Statistical and Anomaly Detection
- **Owner:** AN · **Points:** 5 · **Priority:** High
- **Labels:** `detection`

**Description.** Isolation Forest and Local Outlier Factor over the feature matrix, with a written justification of why each is appropriate. Do not add methods for sophistication alone.

**Acceptance criteria.** Both methods run on the frozen dataset; hyperparameters and their selection documented; results compared against the statistical layer; agreement and disagreement analysed.

### Build the explainable composite score

- **Epic:** E9 — WS9 Statistical and Anomaly Detection
- **Owner:** AN · **Points:** 8 · **Priority:** Highest
- **Labels:** `deliverable-2`, `detection`, `explainability`, `critical-path`

**Description.** Combine indicators into a ranked suspicion score that always reports its constituent contributions. A bare number is not an acceptable output.

**Acceptance criteria.** Score output lists every contributing indicator with its value and contribution; weights are evidence-derived and justified, never invented; output carries the standard interpretation caveat.

### Implement the CLI analysis commands

- **Epic:** E11 — WS11 Python CLI
- **Owner:** DE · **Points:** 8 · **Priority:** High
- **Labels:** `deliverable-3`, `cli`

**Description.** insiderwatch market, insiderwatch trader and insiderwatch score, wired to the analysis library.

**Acceptance criteria.** All three commands run end to end from a clean cache; output matches the explainable format in the brief; errors handled with actionable messages rather than tracebacks.

### Produce the anomaly visualisation set

- **Epic:** E10 — WS10 Visualisation
- **Owner:** RV · **Points:** 5 · **Priority:** High
- **Labels:** `deliverable-1`, `visualisation`

**Description.** Figures that carry the analytical argument: anomaly score distribution, candidate versus control comparison, suspicious wallet timeline, cumulative position and P&L, trade timing relative to announcement.

**Acceptance criteria.** Five figures regenerable by command; each has a caption stating what it does and does not evidence; consistent visual treatment across the set.

### Summarise behavioural signatures from the case studies

- **Epic:** E3 — WS3 Case Study Investigation
- **Owner:** RV · **Points:** 5 · **Priority:** High
- **Labels:** `research`, `methodology`

**Description.** Synthesise the verified cases into the behavioural patterns the detection layer should be sensitive to, with an explicit note on how few cases this is and what that means for generalisation.

**Acceptance criteria.** Signature summary written; each signature mapped to the implemented indicators; small-sample limitation stated plainly.


## Sprint 5 — Evaluation and discovery

**12 Oct – 25 Oct 2026** · 10 stories · **53 points**

### Evaluate detection against the known cases

- **Epic:** E12 — WS12 Validation and Evaluation
- **Owner:** AN · **Points:** 5 · **Priority:** Highest
- **Labels:** `evaluation`, `critical-path`

**Description.** Measure whether the scoring system ranks the verified case wallets above the control population, and analyse every case it misses.

**Acceptance criteria.** Recall reported against the known set; each miss analysed for cause; results reported honestly including negative findings.

### Analyse false positives with manual review

- **Epic:** E12 — WS12 Validation and Evaluation
- **Owner:** BC · **Points:** 8 · **Priority:** Highest
- **Labels:** `evaluation`, `critical-path`

**Description.** Take the top-ranked control-population wallets and manually assess each for innocent explanations: market making, hedging, domain expertise, fast news reaction, luck.

**Acceptance criteria.** At least 20 high-scoring non-case wallets reviewed and categorised; false positive rate reported at several thresholds; findings feed back into indicator documentation.

### Run sensitivity and ablation analysis

- **Epic:** E12 — WS12 Validation and Evaluation
- **Owner:** AN · **Points:** 5 · **Priority:** Highest
- **Labels:** `evaluation`

**Description.** Vary thresholds and remove indicators one at a time to establish which actually carry signal and how stable the ranking is.

**Acceptance criteria.** Sensitivity curves produced; per-indicator contribution quantified; any indicator adding no discriminative value identified and either justified or removed.

### Assess alternative explanations for flagged candidates

- **Epic:** E12 — WS12 Validation and Evaluation
- **Owner:** RV · **Points:** 5 · **Priority:** Highest
- **Labels:** `evaluation`, `ethics`

**Description.** For every candidate surfaced, systematically record the innocent explanations that cannot be excluded. This directly answers RQ5.

**Acceptance criteria.** Alternative-explanation table complete for all reported candidates; no candidate described in language implying proven misconduct.

### Execute the discovery run on unseen markets

- **Epic:** E7 — WS7 Feature Engineering
- **Owner:** AN · **Points:** 5 · **Priority:** High
- **Labels:** `discovery`, `critical-path`

**Description.** Apply the calibrated methodology to markets not used in development, to surface previously unidentified candidates.

**Acceptance criteria.** Discovery run over a documented market set; ranked candidate list produced with full explanations; development-set contamination explicitly ruled out.

### Implement the CLI scan, export and visualise commands

- **Epic:** E11 — WS11 Python CLI
- **Owner:** DE · **Points:** 8 · **Priority:** High
- **Labels:** `deliverable-3`, `cli`

**Description.** insiderwatch scan, insiderwatch export --format csv/json and insiderwatch visualise, completing the intended command surface.

**Acceptance criteria.** All commands functional; export output opens cleanly in a spreadsheet; visualise writes figures to disk; every command covered by at least one test.

### Finalise the visualisation suite

- **Epic:** E10 — WS10 Visualisation
- **Owner:** RV · **Points:** 8 · **Priority:** High
- **Labels:** `deliverable-1`, `visualisation`

**Description.** Consolidate all figures to a consistent standard suitable for the report and the demo, with accessible colour choices and self-explanatory captions.

**Acceptance criteria.** Full suite regenerable by one command from the frozen dataset; consistent styling; no identifying profile data displayed; captions state limitations.

### Run the reproducibility check from a fresh clone

- **Epic:** E13 — WS13 Documentation, Testing, Delivery
- **Owner:** DE · **Points:** 3 · **Priority:** Highest
- **Labels:** `reproducibility`, `critical-path`

**Description.** Clone into a clean environment and reproduce the headline results end to end. Reproducibility claimed but never tested is reproducibility that does not exist.

**Acceptance criteria.** A team member not involved in the pipeline reproduces the headline numbers from a fresh clone using only the README; every gap found is fixed.

### OPTIONAL SPIKE — on-chain funding-trail proof of concept

- **Epic:** E4 — WS4 API and Blockchain Feasibility
- **Owner:** BC · **Points:** 3 · **Priority:** Lowest
- **Labels:** `extension`, `optional`, `blockchain`

**Description.** Time-boxed spike, to be pulled ONLY if Sprint 4 finished clean and Mark confirmed blockchain as core. Trace funding for two candidate proxy wallets on Polygon. Note the two contract eras either side of the 28 Apr 2026 V2 migration and the proxy-wallet indirection.

**Acceptance criteria.** Hard stop at the time-box regardless of progress; outcome written up as either a demonstrated capability or a documented dead end; no impact on any committed deliverable.

### Write the CLI user documentation

- **Epic:** E11 — WS11 Python CLI
- **Owner:** DE · **Points:** 3 · **Priority:** Medium
- **Labels:** `deliverable-3`, `documentation`

**Description.** Installation, configuration, every command with a worked example, and the interpretation caveat that must accompany any score.

**Acceptance criteria.** A reader who has never seen the project can install and run the tool from the documentation alone; every command documented with example output.


## Sprint 6 — Freeze, write, demo

**26 Oct – 8 Nov 2026** · 9 stories · **44 points**

### Freeze code and tag the release

- **Epic:** E13 — WS13 Documentation, Testing, Delivery
- **Owner:** TL · **Points:** 2 · **Priority:** Highest
- **Labels:** `delivery`, `milestone`

**Description.** Feature freeze at the start of the sprint. Only defect fixes and documentation thereafter, so the report describes software that actually exists.

**Acceptance criteria.** Release tagged; freeze announced to the team; any post-freeze change requires TL approval and is logged.

### Write the final report — methodology

- **Epic:** E13 — WS13 Documentation, Testing, Delivery
- **Owner:** TL · **Points:** 8 · **Priority:** Highest
- **Labels:** `documentation`, `delivery`

**Description.** Research questions, data sources with access dates and API versions, collection method, baseline construction, feature definitions, detection approach and every assumption made.

**Acceptance criteria.** Methodology is detailed enough for an independent reader to replicate the study; every method choice justified with a citation; all assumptions explicit.

### Write the final report — results and evaluation

- **Epic:** E13 — WS13 Documentation, Testing, Delivery
- **Owner:** AN · **Points:** 8 · **Priority:** Highest
- **Labels:** `documentation`, `delivery`

**Description.** Findings, evaluation results, discovered candidates and negative results. Correlation must never be presented as evidence of insider knowledge.

**Acceptance criteria.** Results reported with observable evidence, statistical inference and speculation clearly separated; negative results included; no accusatory language anywhere.

### Write the limitations and ethical discussion

- **Epic:** E13 — WS13 Documentation, Testing, Delivery
- **Owner:** RV · **Points:** 5 · **Priority:** Highest
- **Labels:** `documentation`, `ethics`, `delivery`

**Description.** Ground truth scarcity, survivorship and confirmation bias, small case sample, wallet obfuscation, one-person-many-wallets, platform asymmetry, and the ethics of behavioural flagging.

**Acceptance criteria.** Every risk from the register addressed; limitations stated without hedging; ethical position on anonymity and non-accusation clearly argued.

### Write the threats-to-validity section

- **Epic:** E12 — WS12 Validation and Evaluation
- **Owner:** TL · **Points:** 3 · **Priority:** High
- **Labels:** `evaluation`, `documentation`

**Description.** Internal, external and construct validity threats, and what was done to mitigate each.

**Acceptance criteria.** Each threat named, classified and paired with a mitigation or an honest acknowledgement that none exists.

### Finalise dataset documentation and data dictionary

- **Epic:** E13 — WS13 Documentation, Testing, Delivery
- **Owner:** AN · **Points:** 3 · **Priority:** High
- **Labels:** `documentation`, `delivery`

**Description.** Complete the data dictionary, dataset manifest, collection dates, API versions and licensing or terms considerations.

**Acceptance criteria.** Every field in every stored dataset documented; collection dates and API versions recorded for citation; committed alongside the release tag.

### Complete the test coverage pass

- **Epic:** E13 — WS13 Documentation, Testing, Delivery
- **Owner:** DE · **Points:** 5 · **Priority:** High
- **Labels:** `testing`, `delivery`

**Description.** Close gaps in test coverage, particularly around collectors, feature computation and scoring.

**Acceptance criteria.** Test suite green in CI; coverage reported; all collectors, feature functions and the scoring function have at least one test.

### Prepare and rehearse the demonstration

- **Epic:** E13 — WS13 Documentation, Testing, Delivery
- **Owner:** TL · **Points:** 5 · **Priority:** Highest
- **Labels:** `delivery`, `milestone`

**Description.** Scripted live demo of the CLI: fetch, analyse, score, explain, visualise. Rehearsed against a cached dataset so it cannot fail on a network problem.

**Acceptance criteria.** Demo runs inside the allotted time from cache with no live API dependency; every team member can run it; fallback recording produced.

### Build the final presentation deck

- **Epic:** E13 — WS13 Documentation, Testing, Delivery
- **Owner:** RV · **Points:** 5 · **Priority:** Highest
- **Labels:** `delivery`, `milestone`

**Description.** Problem, approach, findings, evaluation, limitations. Written for an audience that has not read the report.

**Acceptance criteria.** Deck complete with the visualisation suite embedded; rehearsed within time; every claim in it traceable to the report.

