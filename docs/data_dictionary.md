# Data Dictionary

One row per field the project stores. Seeded from the confirmed field
lists in `WS4_data_feasibility.md` §3. Fill in `Type`, `Units`,
`Nullable` and `Notes` as each collector is built and run against real
data — do not guess ahead of the collector's actual output.

**Status of this file:** field lists and types below marked *(obs)* were observed
in live responses on 20 August 2026 and recorded in
`data/external/feasibility_check_2026-08-20_manual.json`. Unmarked rows are still
documentation-only. Do not mark a row *(obs)* without a committed evidence file
behind it.

---

## Request-level traps — read before writing any collector call

**1. `start` / `end` are ignored on an unscoped `/trades` call.** *(obs, 20 Aug 2026)*

A `/trades` request carrying `start` and `end` but **no** `user=` or `market=`
returns *current* trades, not the requested window. Two different historical
windows (Oct 2024 and Apr 2026) both came back with same-minute trades; the
identical window with `market=` attached was honoured correctly.

There is no error, no empty array and no warning — a collector walking the
global feed by time window silently produces a dataset of today's data wearing
the wrong timestamps in its metadata.

> **Rule: every historical `/trades` or `/activity` call MUST carry `user=` or
> `market=`.** Enforce in code review. `verify_apis.py` test 8 re-checks it on
> every run and will flag if the behaviour ever changes.

**2. `takerOnly` defaults to `true`.** The API silently drops maker-side fills
when the parameter is absent, which biases position reconstruction, volume
totals and any liquidity-share feature (risk R4). `TradeQuery` forces the caller
to set it explicitly. Record the value used in every output artefact's metadata.

**3. Offset caps, and the page-limit trap.** `/trades` caps `offset` at 10,000,
`/activity` at 5,000. Paginate by time window, not offset alone.

`limit` **is** honoured above 100 — probed at 100/500/1000 and each returned
exactly that many *(obs, 20 Aug 2026)*. Which creates the trap: a response whose
length equals the requested `limit` is a censored count, not a count. Two such
responses can compare "equal" while the underlying totals differ by an order of
magnitude. Before comparing record counts anywhere in the pipeline, confirm
neither side filled its page — shrink the window and re-count if it did.

**4. Kalshi's global feed cannot be cursor-walked.** *(obs, 19 Aug 2026)* Ten
pages of 1,000 records reached back roughly two minutes. Historical Kalshi
collection must filter by `ticker` and `min_ts`.

---

## Historical coverage across the V1→V2 migration

Confirmed 20 August 2026 — see `docs/WS4_test6_V1V2_continuity_finding.md`.

| Endpoint | Pre-migration coverage | Evidence |
|---|---|---|
| `/trades` | **Yes**, to at least 2024-10-28 | Seed markets + 2024 election market |
| `/activity` | **Yes**, to at least 2025-10-10 | Seed-case wallet |
| `/closed-positions` | **Yes**, to at least 2024-11-06 | Realised P&L on a 2024 election position |

`proxyWallet` values are **stable across the migration** — the same address
returns trades in both contract eras, so no identity join is needed for
cross-boundary trader features. Record schema is identical either side of the
cutover, `transactionHash` included.

---

## Polymarket Data API — `/trades`

| Field | Type | Units | Nullable | Notes |
|---|---|---|---|---|
| proxyWallet | string *(obs)* | 0x address | No | Contract account, not the user's signing key — see WS4 §3.4 on wallet-factory indirection. Stable across the V2 migration *(obs)* |
| side | string *(obs)* | BUY / SELL | No | |
| asset | string *(obs)* | uint256 token id | No | ERC-1155 position token; identifies the outcome leg |
| conditionId | string *(obs)* | 0x hash | No | Join key to Gamma market metadata. Unchanged across the migration *(obs)* |
| size | float *(obs)* | outcome shares | No | Not USD — multiply by `price` for cash value |
| price | float *(obs)* | USD per share, 0–1 | No | Also read as implied probability |
| timestamp | int *(obs)* | Unix seconds | No | UTC. Responses observed newest-first |
| title | string *(obs)* | | No | Market question text |
| slug | string *(obs)* | | No | |
| icon | string *(obs)* | URL | Yes | |
| eventSlug | string *(obs)* | | Yes | Empty string observed on some markets — treat as nullable |
| outcome | string *(obs)* | e.g. Yes / No / Up | No | |
| outcomeIndex | int *(obs)* | | No | `999` observed on some series markets — do not assume 0/1 |
| name | string *(obs)* | | Yes | Self-declared, identity-adjacent — pseudonymise before storing (WS4 §3.1) |
| pseudonym | string *(obs)* | | Yes | Self-declared, identity-adjacent — pseudonymise before storing |
| bio | string *(obs)* | | Yes | Self-declared, identity-adjacent — pseudonymise before storing |
| profileImage | string *(obs)* | URL | Yes | Self-declared, identity-adjacent — do not put in a figure |
| profileImageOptimized | string *(obs)* | URL | Yes | |
| transactionHash | string *(obs)* | 0x hash | No | Present on pre-migration records too, so V1-era trades remain cross-referenceable on Polygon *(obs)* |

**takerOnly**: request parameter, not a response field, but record its value in output metadata every time — the API defaults it to `true`, which silently drops maker-side fills (WS4 §3.1, risk R4).

## Polymarket Data API — `/activity`

Full field list observed 20 Aug 2026. Shares most of the `/trades` schema, plus:

| Field | Type | Units | Nullable | Notes |
|---|---|---|---|---|
| type | string *(obs)* | | No | Documented: TRADE / SPLIT / MERGE / REDEEM / REWARD / CONVERSION / DEPOSIT / WITHDRAWAL / YIELD / MAKER_REBATE / TAKER_REBATE / REFERRAL_REWARD. Observed so far: TRADE, REDEEM, YIELD, DEPOSIT, TAKER_REBATE |
| usdcSize | float *(obs)* | USD | No | Cash value — the field to use for position size, not `size` |
| timestamp | int *(obs)* | Unix seconds | No | |
| proxyWallet, conditionId, size, transactionHash, price, asset, side, outcomeIndex, title, slug, icon, eventSlug, outcome, name, pseudonym, bio, profileImage, profileImageOptimized | *(obs)* | | | As `/trades` |

Set `excludeDepositsWithdrawals=false` explicitly — DEPOSIT/WITHDRAWAL records are the route to wallet-funding features and the wallet-age proxy (WS4 §3.2).

## Polymarket Data API — `/closed-positions`

| Field | Type | Units | Nullable | Notes |
|---|---|---|---|---|
| realizedPnl | float *(obs)* | USD | No | |
| avgPrice | float *(obs)* | USD per share, 0–1 | No | Entry price — feeds the "unusual confidence" feature |
| curPrice | float *(obs)* | USD per share, 0–1 | No | `1` or `0` once resolved |
| totalBought | float *(obs)* | USD | No | |
| proxyWallet, asset, conditionId, title, slug, icon, eventSlug, outcome, outcomeIndex | *(obs)* | | | |
| oppositeOutcome | string *(obs)* | | No | |
| oppositeAsset | string *(obs)* | uint256 token id | No | |
| endDate | string *(obs)* | YYYY-MM-DD | No | Market resolution date |
| timestamp | int *(obs)* | Unix seconds | No | Position close time |

An **empty array is not an API limitation** — it means the wallet has no closed
positions, which is common for wallets whose bets resolved worthless. Do not
record an empty response as missing history.

## Polymarket Data API — `/positions`

| Field | Type | Units | Nullable | Notes |
|---|---|---|---|---|
| size | | | | |
| avgPrice | | | | |
| currentValue | | | | |
| cashPnl | | | | |
| percentPnl | | | | |
| curPrice | | | | |
| redeemable | | | | |
| conditionId | | | | |

## Polymarket Gamma API — `/markets`

Used to resolve seed cases to condition IDs and to find markets live across a
given date. Confirmed to serve pre-migration market metadata *(obs)*.

| Field | Type | Units | Nullable | Notes |
|---|---|---|---|---|
| question | string *(obs)* | | No | |
| slug | string *(obs)* | | No | |
| conditionId | string *(obs)* | 0x hash | No | Join key to the Data API |
| startDate | string *(obs)* | ISO 8601 | Yes | |
| endDate | string *(obs)* | ISO 8601 | No | |
| volumeNum | float *(obs)* | USD | No | |

Useful parameters *(obs)*: `closed`, `end_date_min`, `end_date_max`, `order`,
`ascending`, `limit`.

## Kalshi Trade API v2 — `/markets/trades`

| Field | Type | Units | Nullable | Notes |
|---|---|---|---|---|
| trade_id | string *(obs)* | | No | |
| ticker | string *(obs)* | | No | |
| count_fp | *(obs)* | contracts | No | |
| yes_price_dollars | *(obs)* | USD | No | |
| no_price_dollars | *(obs)* | USD | No | |
| taker_outcome_side | *(obs)* | | No | |
| taker_book_side | *(obs)* | | No | |
| created_time | string *(obs)* | ISO 8601 | No | Note: ISO string, not Unix seconds as on Polymarket |
| is_block_trade | bool *(obs)* | | No | Market-level indicator of interest — WS4 §4 |
| taker_side | *(obs)* | | | Deprecated |

**No buyer, seller, user or account field exists in this schema (confirmed, WS4 §4). Trader-level analysis is not possible on Kalshi public data — this is a property of the data, not a scoping choice.**
