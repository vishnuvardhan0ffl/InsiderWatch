# Data Dictionary

One row per field the project stores. Seeded from the confirmed field
lists in `WS4_data_feasibility.md` §3. Fill in `Type`, `Units`,
`Nullable` and `Notes` as each collector is built and run against real
data — do not guess ahead of the collector's actual output.

## Polymarket Data API — `/trades`

| Field | Type | Units | Nullable | Notes |
|---|---|---|---|---|
| proxyWallet | | | | Contract account, not the user's signing key — see WS4 §3.4 on wallet-factory indirection |
| side | | | | BUY / SELL |
| asset | | | | |
| conditionId | | | | |
| size | | | | |
| price | | | | |
| timestamp | | | | Unix seconds |
| title | | | | |
| slug | | | | |
| icon | | | | |
| eventSlug | | | | |
| outcome | | | | |
| outcomeIndex | | | | |
| name | | | | Self-declared, identity-adjacent — pseudonymise before storing (WS4 §3.1) |
| pseudonym | | | | Self-declared, identity-adjacent — pseudonymise before storing |
| bio | | | | Self-declared, identity-adjacent — pseudonymise before storing |
| profileImage | | | | Self-declared, identity-adjacent — do not put in a figure |
| profileImageOptimized | | | | |
| transactionHash | | | | |

**takerOnly**: request parameter, not a response field, but record its value in output metadata every time — the API defaults it to `true`, which silently drops maker-side fills (WS4 §3.1, risk R4).

## Polymarket Data API — `/activity`

| Field | Type | Units | Nullable | Notes |
|---|---|---|---|---|
| type | | | | TRADE / SPLIT / MERGE / REDEEM / REWARD / CONVERSION / DEPOSIT / WITHDRAWAL / YIELD / MAKER_REBATE / TAKER_REBATE / REFERRAL_REWARD |
| timestamp | | | | |
| (other fields TBD from live response — run verify_apis.py test 2) | | | | |

## Polymarket Data API — `/closed-positions`

| Field | Type | Units | Nullable | Notes |
|---|---|---|---|---|
| realizedPnl | | | | |
| avgPrice | | | | |
| curPrice | | | | |
| totalBought | | | | |

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

## Kalshi Trade API v2 — `/markets/trades`

| Field | Type | Units | Nullable | Notes |
|---|---|---|---|---|
| trade_id | | | | |
| ticker | | | | |
| count_fp | | | | |
| yes_price_dollars | | | | |
| no_price_dollars | | | | |
| taker_outcome_side | | | | |
| taker_book_side | | | | |
| created_time | | | | |
| is_block_trade | | | | Market-level indicator of interest — WS4 §4 |
| taker_side | | | | Deprecated |

**No buyer, seller, user or account field exists in this schema (confirmed, WS4 §4). Trader-level analysis is not possible on Kalshi public data — this is a property of the data, not a scoping choice.**
