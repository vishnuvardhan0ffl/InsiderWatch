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

## Polymarket Gamma API — `/markets` (raw response)

Used to resolve seed cases to condition IDs, to find markets live across a given
date, and to supply the market context every WS7 feature needs. Confirmed to
serve pre-migration market metadata *(obs)*.

Collected by `collectors/gamma.py`. Rows marked *(obs)* were seen in a live
response on 20 August 2026. **Everything else here is documentation-only** —
taken from the published Gamma reference and never seen from the live API. Run
`python verify_gamma.py` from a normal connection to settle them, commit the
evidence file it writes to `data/external/`, and only then add *(obs)*.

| Field | Type | Units | Nullable | Notes |
|---|---|---|---|---|
| question | string *(obs)* | | No | The market question — the title field |
| slug | string *(obs)* | | No | Human-readable identifier; the by-name lookup key |
| conditionId | string *(obs)* | 0x hash | No | **The join key to the Data API.** A Gamma market and a `/trades` record meet here and nowhere else |
| startDate | string *(obs)* | ISO 8601 | Yes | |
| endDate | string *(obs)* | ISO 8601 | No | Resolution date — feeds every time-before-event feature |
| volumeNum | float *(obs)* | USD | No | Arrives as a JSON number or a numeric string; the collector coerces both |
| id | string | | No | Gamma's own market id. The key the keyset walk orders and de-duplicates on |
| liquidityNum | float | USD | Yes | `liquidity` observed as an alternative key name on some records; the collector reads either |
| createdAt | string | ISO 8601 | Yes | Market creation date |
| closed | bool | | Yes | May arrive as a bool or as the string "true"/"false" |
| active | bool | | Yes | |
| archived | bool | | Yes | |
| outcomes | list | | Yes | May arrive JSON-encoded as a string, `"[\"Yes\", \"No\"]"`, rather than as a list |
| clobTokenIds | list | | Yes | Same encoding quirk as `outcomes` |
| eventSlug | string | | Yes | Not present on every record; the collector falls back to `events[0].slug` |
| events | list of objects | | Yes | Parent event(s). Each may carry its own `tags` |
| tags | list | | Yes | Objects `{id, label, slug}` or bare strings. Attached to the market, its parent event, or both |

**Request parameters.** Confirmed *(obs, 20 Aug 2026)*: `closed`, `end_date_min`,
`end_date_max`, `order`, `ascending`, `limit`. Documentation-only, and named as
module constants in `collectors/gamma.py` so a disagreement is a one-line fix:
`slug`, `condition_ids`, `offset`, `tag_id`, `start_date_min`, `start_date_max`,
`liquidity_num_min`, `volume_num_min`.

**Pagination.** Gamma exposes `limit`/`offset`, not a cursor. The collector pins
the ordering (`order=id`, `ascending=true`), advances `offset` by rows actually
received, and drops any key it has already returned — so a market created
mid-walk cannot cause a duplicate record. It cannot defend against a market
*removed* from the result set below the cursor, which would skip one record;
that limitation is written into every collection's metadata. Collect a
catalogue in one sitting rather than resuming a walk hours later.

## Gamma collector output — market record

What `collectors.gamma.normalise_market()` emits, and what
`fetch_market_by_slug`, `fetch_market_by_condition_id`, `fetch_markets` and
`collect_markets` all return. This table **is** the schema:
`tests/test_gamma_collector.py` asserts that these field names and the
collector's output match exactly, so the two cannot drift apart.

Types below are what the collector guarantees after coercion, not what the API
sent. `_ts` fields are derived, not returned by Gamma: they are the same instant
in Unix seconds, carried because the Data API works in Unix seconds and
converting at the call site is how off-by-a-timezone bugs get in.

| Field | Type | Units | Nullable | Derived from |
|---|---|---|---|---|
| condition_id | string | 0x hash | Yes | `conditionId` |
| market_id | string | | Yes | `id` |
| question | string | | Yes | `question` |
| slug | string | | Yes | `slug` |
| event_slug | string | | Yes | `eventSlug`, else the first `events[].slug` |
| tags | list of string | tag slugs | No — `[]` when absent | `tags[]` and `events[].tags[]`, de-duplicated, API order preserved. Slug preferred, then label, then id |
| liquidity_num | float | USD | Yes | `liquidityNum`, else `liquidity` |
| volume_num | float | USD | Yes | `volumeNum`, else `volume` |
| start_date | string | ISO 8601 UTC | Yes | `startDate`, normalised to UTC. An unparsable value is passed through unchanged rather than dropped |
| end_date | string | ISO 8601 UTC | Yes | `endDate` |
| created_at | string | ISO 8601 UTC | Yes | `createdAt` |
| start_date_ts | int | Unix seconds | Yes | Derived from `startDate` |
| end_date_ts | int | Unix seconds | Yes | Derived from `endDate` |
| created_at_ts | int | Unix seconds | Yes | Derived from `createdAt` |
| closed | bool | | Yes | `closed` |
| active | bool | | Yes | `active` |
| archived | bool | | Yes | `archived` |
| outcomes | list of string | | No — `[]` when absent | `outcomes`, JSON-decoded if it arrived as a string |
| clob_token_ids | list of string | | No — `[]` when absent | `clobTokenIds`, same decoding |

Every field is nullable because Gamma omits fields per record rather than
returning nulls, and a collector that raised on a missing `liquidityNum` would
be unusable against the real catalogue. Nulls are a fact about the market to be
reported in the dataset validation report — not something to fill in.

## Gamma collector output — event record

What `collectors.gamma.normalise_event()` emits. Events are how Gamma groups
related markets, and `market_condition_ids` is the join back to both the market
records above and the Data API.

| Field | Type | Units | Nullable | Derived from |
|---|---|---|---|---|
| event_id | string | | Yes | `id` |
| title | string | | Yes | `title` |
| slug | string | | Yes | `slug` |
| tags | list of string | tag slugs | No — `[]` when absent | As the market record |
| liquidity_num | float | USD | Yes | `liquidityNum`, else `liquidity` |
| volume_num | float | USD | Yes | `volumeNum`, else `volume` |
| start_date | string | ISO 8601 UTC | Yes | `startDate` |
| end_date | string | ISO 8601 UTC | Yes | `endDate` |
| created_at | string | ISO 8601 UTC | Yes | `createdAt` |
| start_date_ts | int | Unix seconds | Yes | Derived from `startDate` |
| end_date_ts | int | Unix seconds | Yes | Derived from `endDate` |
| created_at_ts | int | Unix seconds | Yes | Derived from `createdAt` |
| closed | bool | | Yes | `closed` |
| active | bool | | Yes | `active` |
| archived | bool | | Yes | `archived` |
| market_condition_ids | list of string | 0x hashes | No — `[]` when absent | `markets[].conditionId`, de-duplicated, order preserved |
| market_count | int | | No | Length of `market_condition_ids` |

**A caution on `market_count`.** It counts the markets Gamma returned inside
this event record, which is not necessarily every market the event has ever
had — a filtered or paginated event response may carry a subset. Do not use it
as a denominator without checking that against a live response first.

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
