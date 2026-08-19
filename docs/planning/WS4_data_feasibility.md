# WS4 — Data Feasibility Study

**Project:** PG-S2-55 — *Someone Always Knows: An Analysis of Insider Trading on Polymarket / Kalshi*
**Author:** Team Leader (Vish), with research assistance
**Date compiled:** 16 August 2026
**Status:** Draft v0.1 — documentation-verified, **not yet runtime-verified**

---

## 0. How to read this document

Every claim below carries a confidence label. Do not cite this document in the final report without first re-running the verification script (`verify_apis.py`, Appendix B) and recording the results.

| Label | Meaning |
|---|---|
| **[CONFIRMED-DOC]** | Stated explicitly in official platform documentation, accessed 16 Aug 2026. |
| **[CONFIRMED-DOC*]** | As above, but the documentation is a help-centre or migration page rather than the API reference. |
| **[UNVERIFIED]** | Not confirmed from a primary source. Must be tested before we rely on it. |
| **[INFERENCE]** | Our reasoning from confirmed facts, not itself a documented fact. |

**Important limitation on this draft:** the environment used to compile it could not reach `data-api.polymarket.com`, `gamma-api.polymarket.com` or `external-api.kalshi.com` (network egress blocked). Nothing here has been confirmed by an actual HTTP response. Field names, parameter names and limits are taken from the published API reference. **Treat the whole document as provisional until a team member runs the smoke test from a normal network connection.**

---

## 1. Verdict — the four things that matter

### 1.1 The Polymarket/Kalshi asymmetry is real, and it is worse than "different"

Kalshi's public trade endpoint returns **no counterparty identifier of any kind** — not a user ID, not an account ID, not a pseudonymous handle. The full trade schema is `trade_id`, `ticker`, `count_fp`, `yes_price_dollars`, `no_price_dollars`, `taker_outcome_side`, `taker_book_side`, `created_time`, `is_block_trade`. **[CONFIRMED-DOC]**

Polymarket's public data API returns `proxyWallet` on **every trade record**, unauthenticated. **[CONFIRMED-DOC]**

**Consequence:** trader-level anomaly detection on Kalshi using public data is **not possible**. This is not a scoping preference we are proposing to Mark for convenience — it is a hard constraint imposed by the data. RQ1–RQ4, as written, can only be answered on Polymarket. Kalshi can support market-level analysis only (abnormal volume, price movement, pre-event activity, cross-platform comparison).

This is good news for the meeting: the scope split in §6 of the project brief is now evidence-backed rather than a guess.

### 1.2 We probably do not need blockchain analysis for the core deliverables

The public Polymarket Data API alone supplies, with no authentication:

- full wallet trade history (`/trades?user=`)
- full wallet activity including deposits, withdrawals, splits, merges, redemptions (`/activity?user=`)
- realised profit and average entry price per closed position (`/closed-positions?user=`)
- current open positions and their value
- top holders per market, total markets a user has traded, leaderboard rankings
- market price history and order books

That covers the large majority of the "Trader/Wallet Features", "Trade Features", "Market Features" and "Outcome Features" lists in the project brief §11 — **without touching Polygon at all**. **[INFERENCE from CONFIRMED-DOC endpoints]**

**Recommendation:** treat blockchain analysis as an *extension*, not a core requirement. The only feature list that genuinely requires on-chain work is "Blockchain Features" (funding source, connected wallets, wallet clusters). See §1.3 for why that is now expensive.

### 1.3 The finding that changes our plan: Polymarket migrated to V2 on 28 April 2026

Polymarket cut over to a new exchange stack on **28 April 2026, ~11:00 UTC**. **[CONFIRMED-DOC]** Specifically:

- New CTF Exchange V2 contracts; **legacy V1 exchange contracts are no longer functional**. **[CONFIRMED-DOC]**
- Collateral changed from USDC.e to **pUSD**, a new ERC-20 on Polygon. **[CONFIRMED-DOC]**
- Order struct redesigned (`nonce`, `feeRateBps`, `taker` removed; `timestamp`, `metadata`, `builder` added); EIP-712 domain version moved 1 → 2. **[CONFIRMED-DOC]**
- Goldsky has **discontinued subgraph support** for Polymarket. Their documentation states that existing public subgraph endpoints "will return incomplete or incorrect data" post-migration. Their replacement (Turbo Pipelines) requires a Goldsky account, an API key, and your own destination database — and they flag user-positions backfill at up to ~1.2 billion entities. **[CONFIRMED-DOC]**

**Why this matters enormously for us:** our seed cases (Venezuela, Nobel Prize, Google search rankings) all pre-date April 2026 and therefore sit on **V1 contracts with USDC.e collateral**. Current and future markets sit on **V2 with pUSD**. Any on-chain pipeline must handle two contract eras, two collateral tokens, and an indexing layer that has been withdrawn from public access.

**[INFERENCE]** This roughly doubles the engineering cost of the blockchain workstream and introduces a real risk of a team member burning four weeks on infrastructure that produces no analytical output. Combined with §1.2, this is a strong argument for keeping WS-blockchain optional and time-boxed.

**[UNVERIFIED]** — and this is the single most important open question — whether the Data API's `/trades` and `/activity` endpoints return a **continuous history spanning the V1→V2 boundary**, or whether pre-migration trades are missing/altered. The migration documentation does not address historical API data access. If the Data API is continuous across the boundary, our core pipeline is unaffected and this is merely an on-chain problem. If it is not, our case studies are in serious trouble. **Test this first.** See Appendix B, test 6.

### 1.4 Historical depth is adequate, but pagination is capped and needs windowing

Data API endpoints default to a window covering roughly the **most recent 3 years**. User-scoped requests can retrieve full history by setting `start=1`. **[CONFIRMED-DOC]** A 3-year floor from August 2026 reaches back to ~August 2023, which comfortably covers the 2024–2025 seed cases.

However, `offset` is capped — 10,000 on `/trades`, 5,000 on `/activity`. **[CONFIRMED-DOC]** For any high-activity wallet or market we must paginate by **time windows** (`start`/`end`), each with its own independent offset budget, rather than by offset alone. This needs to be built into the collector from day one; retrofitting it later is painful.

---

## 2. Source-by-source assessment

| Source | Base URL | Auth | Trader identity? | Historical depth | Verdict |
|---|---|---|---|---|---|
| Polymarket Data API | `https://data-api.polymarket.com` | **None** | **Yes** (`proxyWallet`) | ~3y default; full via `start=1` for user-scoped | **Primary source. Build here first.** |
| Polymarket Gamma API | `https://gamma-api.polymarket.com` | None | n/a (market metadata) | n/a | Market/event catalogue, tags, resolution dates. |
| Polymarket CLOB API | `https://clob.polymarket.com` | Mixed | Own account only | n/a | Order books and price history are public. **`/data/trades` requires readonly-or-L2 HMAC auth and returns only the authenticated user's own trades** (filtered by a required `maker_address`) — do not confuse it with the public Data API `/trades` route. This distinction has misled other projects. **[CONFIRMED-DOC]** |
| Kalshi Trade API v2 | `https://external-api.kalshi.com/trade-api/v2` | None for public market data | **No** | Not documented | Market-level only. |
| Polygon on-chain (RPC / explorer) | various | RPC key typically | Address-level | Full chain | Extension only. Two contract eras post-April 2026. |
| Goldsky subgraphs | — | — | — | — | **Deprecated for Polymarket. Do not build on this.** |
| Goldsky Turbo Pipelines | — | API key + own DB | Yes | Full | Paid, heavy infrastructure. Out of scope for a capstone. |

---

## 3. Polymarket — detail

### 3.1 The endpoint that carries the project

`GET https://data-api.polymarket.com/trades` — **no authentication** (`security: []` in the spec). **[CONFIRMED-DOC]**

**Parameters:** `user` (0x address), `market` (condition IDs, CSV), `eventId` (CSV, mutually exclusive with `market`), `limit` (default 100, max 10,000), `offset` (max 10,000), `side` (BUY/SELL), `start`/`end` (Unix ts), `takerOnly` (bool), `filterType`/`filterAmount` (CASH or TOKENS).

**Response fields:** `proxyWallet`, `side`, `asset`, `conditionId`, `size`, `price`, `timestamp`, `title`, `slug`, `icon`, `eventSlug`, `outcome`, `outcomeIndex`, `name`, `pseudonym`, `bio`, `profileImage`, `profileImageOptimized`, `transactionHash`.

**Two traps worth flagging to the team now:**

1. **`takerOnly` defaults to `true`.** **[CONFIRMED-DOC]** If we leave the default in place we silently drop maker-side fills. That will systematically bias position reconstruction, volume totals and any "percentage of market liquidity" feature. Every collector call must set this parameter explicitly and the choice must be documented in the data dictionary. **[INFERENCE]** This is exactly the kind of undocumented default that produces a wrong result nobody notices until the viva.

2. **`name`, `pseudonym`, `bio`, `profileImage` are self-declared public profile data.** These are legitimately public, but they are identity-adjacent. Per brief §11 and §17, we should hash or pseudonymise these in all stored datasets and every output artefact, and record that decision in the ethics section. Do not put them in a figure.

### 3.2 Other confirmed Data API endpoints of interest

| Purpose | Endpoint |
|---|---|
| Wallet activity incl. funding | `/activity?user=` — types: TRADE, SPLIT, MERGE, REDEEM, REWARD, CONVERSION, DEPOSIT, WITHDRAWAL, YIELD, MAKER_REBATE, TAKER_REBATE, REFERRAL_REWARD |
| Realised P&L per closed position | `/closed-positions?user=` — returns `realizedPnl`, `avgPrice`, `curPrice`, `totalBought` |
| Open positions | `/positions?user=` — returns `size`, `avgPrice`, `currentValue`, `cashPnl`, `percentPnl`, `curPrice`, `redeemable`, `conditionId` |
| Market concentration | `/holders` (top holders for markets) |
| Trader breadth | total markets a user has traded |
| Control-group sampling frame | trader leaderboard rankings |
| Market price series | `/prices-history` (CLOB) |

**[INFERENCE]** `/activity` with `excludeDepositsWithdrawals=false` and `start=1` is our route to **wallet age / first-activity timestamp** and **funding-then-immediately-trading behaviour**, entirely off-chain. Two of the brief's headline heuristics ("unusually new wallet", "wallet funding behaviour") are therefore obtainable without any blockchain work. This is a significant finding for the scope conversation.

### 3.3 Rate limits **[CONFIRMED-DOC]**

IP-based, throttled (queued) rather than rejected. Global cap 15,000 req/10s.

- Data API: 1,000 req/10s general; **`/trades` 200 req/10s**; `/positions` and `/closed-positions` 150 req/10s each.
- Gamma: `/events` 500 req/10s, `/markets` 300 req/10s, `/comments` and `/tags` 200 req/10s.
- CLOB market data: price/book 1,500 req/10s; historical pricing 1,000 req/10s.

**[INFERENCE]** These are generous for our purposes. A polite 5 req/s collector with local caching will never approach them. Cache aggressively anyway — reproducibility, not rate limits, is the reason.

### 3.4 Contract addresses (Polygon, chain ID 137) **[CONFIRMED-DOC]**

Current (V2 era):

- CTF Exchange: `0xE111180000d2663C0091e4f400237545B87B996B`
- Neg Risk CTF Exchange: `0xe2222d279d744050d28e00520010520000310F59`
- Neg Risk Adapter: `0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296`
- Conditional Tokens (CTF): `0x4D97DCd97eC945f40cF65F87097ACe5EA0476045`
- pUSD (proxy): `0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB`
- Gnosis Safe Factory: `0xaacfeea03eb1561c4e67d661e40682bd20e3541b`
- Polymarket Proxy Factory: `0xaB45c5A4B0c941a2F231C04C3f49182e1A254052`

**[UNVERIFIED]** The V1 CTF Exchange address (`0x4bfb41d5...`, seen on Polygonscan) is no longer listed in current documentation. If we do any pre-April-2026 on-chain work we must source and verify V1 addresses separately — they are not in the live contracts page.

**[CONFIRMED-DOC]** Two distinct wallet factories exist (Gnosis Safe for email/Magic users, Polymarket Proxy for EOA users). **[INFERENCE]** This means "wallet address" is not one thing on Polymarket — the `proxyWallet` in the API is a contract account, not the user's signing key. Any wallet-clustering work must account for this indirection, which is a further argument for treating clustering as an extension.

---

## 4. Kalshi — detail

`GET https://external-api.kalshi.com/trade-api/v2/markets/trades` — no authentication for this endpoint (`security: []`). **[CONFIRMED-DOC]**

Parameters: `limit` (1–1000, default 100), `cursor`, `ticker`, `min_ts`, `max_ts`, `is_block_trade`. Cursor-based pagination; **no historical depth limit documented [UNVERIFIED — test it]**.

Response fields: `trade_id`, `ticker`, `count_fp`, `yes_price_dollars`, `no_price_dollars`, `taker_outcome_side`, `taker_book_side`, `created_time`, `is_block_trade`, plus deprecated `taker_side`.

**No buyer, seller, user or account field exists in the schema.** **[CONFIRMED-DOC]**

Rate limiting is a token-bucket system, tiered (Basic 200 read tokens/s up to Prestige 10,000), most requests costing 10 tokens; 429 on exhaustion with no penalty. **[CONFIRMED-DOC]** The rate-limit documentation discusses authenticated requests and does not state limits for unauthenticated public access — **[UNVERIFIED]**, test empirically.

### What Kalshi *can* still contribute

**[INFERENCE]** Despite the identity gap, Kalshi is analytically valuable, and I would argue against dropping it:

1. **`is_block_trade` is a genuinely interesting flag** — large negotiated trades, explicitly labelled. Worth a look as a market-level indicator.
2. **Cross-platform validation.** If a real-world information leak occurred, abnormal pre-announcement volume should appear on *both* platforms. A market-level anomaly detected on Polymarket that also appears on Kalshi is far more defensible than one that does not. This turns Kalshi from a limitation into an **independent validation channel** — which directly serves RQ5 (distinguishing information advantage from noise).
3. **Regulated-venue contrast.** Kalshi is CFTC-regulated; Polymarket is not regulated the same way. Comparing anomaly rates across the two is an interesting, defensible research angle that costs us little.

**Recommended framing for Mark:** we are not "dropping Kalshi" — we are using it for the two things public Kalshi data can actually support, one of which strengthens our validation strategy.

---

## 5. What I recommend we propose

**Recommendation**

Polymarket Data API is the primary and near-sole data source for trader-level work. Kalshi is market-level and serves as a cross-platform validation channel. On-chain Polygon analysis is a **time-boxed optional extension**, explicitly descoped from the minimum viable deliverable.

**Why**

The Data API supplies wallet identity, full trade history, funding activity, realised P&L and market context, unauthenticated and rate-limit-generous. Blockchain work adds a two-contract-era problem (post-April-2026 migration), a withdrawn public indexing layer, and a proxy-wallet indirection — for features that are largely already available off-chain.

**What we should do**

1. Run the smoke test (Appendix B) **before writing any collector code**. Nothing in this document is runtime-confirmed.
2. Answer the V1→V2 historical continuity question (Appendix B, test 6). This is the highest-value unknown in the project right now.
3. Build the Data API collector with time-window pagination and explicit `takerOnly` handling from the first commit.
4. Freeze the on-chain workstream until the collector is delivering data.

**Team allocation**

- Member 3 (APIs/Data Engineering) — owns Appendix B, then the Data API collector. Critical path.
- Member 2 (Blockchain) — **reassign temporarily**. Blockchain work is now blocked on a scope decision; put them on the control-group sampling frame (leaderboard + random market sampling), which is on the critical path and currently unowned.
- Member 5 (Research) — case-study verification, which now has a dependency: confirm each seed case's date sits inside the retrievable window.
- Member 4 (Analytics) — cannot start until data exists; meanwhile, define the feature dictionary against the confirmed field lists in §3.

**Risks**

- V1→V2 API discontinuity would invalidate our case-study data (highest impact, unknown probability).
- `takerOnly` default silently biasing every downstream feature.
- Member 2's workstream having no defensible deliverable if blockchain is descoped — needs an explicit reallocation conversation, not a quiet drift.

**Next step**

Run Appendix B. Report results back before the next supervisor meeting.

---

## 6. Open questions raised by this study

**For Mark (decisions):**

1. Given that Kalshi public data contains no counterparty identifier at all, do you accept trader-level analysis being Polymarket-only?
2. Is blockchain analysis a hard requirement? If so, we need to discuss the post-migration cost, because it changes what else we can deliver.
3. Does cross-platform market-level validation (Kalshi as a confirmation channel) satisfy what you had in mind for Kalshi's role?

**For us (investigate, don't ask):**

4. V1→V2 historical continuity in the Data API. *(Appendix B, test 6)*
5. Actual retrievable depth of Kalshi `/markets/trades` via cursor. *(Appendix B, test 5)*
6. Whether unauthenticated Kalshi requests are rate-limited differently from authenticated ones.
7. Whether `proxyWallet` values are stable across the V2 migration for the same user.

---

## Appendix A — Sources

All accessed 16 August 2026.

- [Polymarket — Get trades for a user or markets](https://docs.polymarket.com/api-reference/core/get-trades-for-a-user-or-markets)
- [Polymarket — Get user activity](https://docs.polymarket.com/api-reference/core/get-user-activity)
- [Polymarket — Get closed positions for a user](https://docs.polymarket.com/api-reference/core/get-closed-positions-for-a-user)
- [Polymarket — API documentation index](https://docs.polymarket.com/llms.txt)
- [Polymarket — Rate limits](https://docs.polymarket.com/quickstart/introduction/rate-limits)
- [Polymarket — Contracts](https://docs.polymarket.com/resources/contracts)
- [Polymarket — Migrating to CLOB V2](https://docs.polymarket.com/v2-migration)
- [Polymarket Help Centre — Exchange Upgrade, 28 April 2026](https://help.polymarket.com/en/articles/14762452-polymarket-exchange-upgrade-april-28-2026)
- [Polymarket — Get trades (CLOB, authenticated)](https://docs.polymarket.com/api-reference/trade/get-trades)
- [Polymarket — Get current positions for a user](https://docs.polymarket.com/api-reference/core/get-current-positions-for-a-user)
- [Kalshi — Get Trades](https://docs.kalshi.com/api-reference/market/get-trades)
- [Kalshi — Rate limits](https://docs.kalshi.com/getting_started/rate_limits)
- [Goldsky — Indexing Polymarket](https://docs.goldsky.com/chains/polymarket)
- [Polymarket subgraph repository](https://github.com/Polymarket/polymarket-subgraph)

---

## Appendix B — Verification protocol

See `verify_apis.py`. Run it from a normal network connection, save the JSON output to `data/external/feasibility_check_<date>.json`, and commit it. That file is our evidence that the API behaved as documented on a specific date — which is exactly what the methodology section will need to cite.

Tests performed:

1. Polymarket `/trades` unauthenticated reachability and field presence
2. Polymarket `/activity` activity types actually observed
3. Polymarket `/closed-positions` P&L field presence
4. Kalshi `/markets/trades` field list — confirm absence of any identity field
5. Kalshi cursor pagination depth
6. **Polymarket V1→V2 historical continuity across 28 April 2026** ← highest priority
7. `takerOnly` true vs false record-count differential
