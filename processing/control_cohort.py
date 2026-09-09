"""
Draw the control cohort: the "ordinary traders" everything anomalous is
measured against.

The one idea
------------
We do not sample the platform. We sample the same markets our seed cases
traded in.

"Is this trader unusual?" has no answer on its own. Unusual compared to whom?
A cohort drawn from Polymarket at large is mostly people betting five dollars
on whether Bitcoin ticks up in the next five minutes, and telling you that a
Nobel Prize bettor does not look like them is not a finding. Matching on the
market removes the biggest confounder, so what is left to explain is the
trader.

See docs/control_cohort_spec.md for the design, the biases it does and does
not fix, and the API-call budget. This module is that specification, executable.

Using it
--------
    frame  = build_frame({"maduro": maduro_trades, "nobel": nobel_trades})
    cohort = draw_cohort(frame, size=1000, seed=20260913)
    print(estimate_api_calls(cohort))

Sampling is seeded, so the same seed gives the same cohort on any machine.
Record the seed with the frozen dataset; without it the cohort is not
reproducible and neither is anything computed from it.
"""

import random
from collections import defaultdict
from dataclasses import dataclass, field

# A wallet quoting both sides of a market, many times, is doing a different
# job from someone taking a view. Left in the frame but kept in its own
# stratum, because market makers would otherwise dominate the trade-count and
# position-size distributions and make ordinary traders look like outliers.
MARKET_MAKER_MIN_TRADES = 20

# Sampling strata, in the order they are reported.
ORDINARY = "ordinary"
MARKET_MAKER = "market_maker"
EXCLUDED = "excluded"


@dataclass
class WalletInMarket:
    """What one wallet did in one market. The unit we sample."""

    wallet: str
    market: str
    trade_count: int = 0
    buy_count: int = 0
    sell_count: int = 0
    cash_traded: float = 0.0          # USD, sum of size * price
    largest_trade: float = 0.0        # USD
    first_seen: int = 0               # Unix seconds
    last_seen: int = 0

    stratum: str = ORDINARY
    excluded_because: str = ""

    @property
    def trades_both_sides(self):
        return self.buy_count > 0 and self.sell_count > 0

    @property
    def active_seconds(self):
        return self.last_seen - self.first_seen


@dataclass
class Cohort:
    """A drawn cohort, plus everything needed to defend how it was drawn."""

    wallets: list = field(default_factory=list)
    seed: int = 0
    frame_size: int = 0
    counts_by_stratum: dict = field(default_factory=dict)
    excluded: list = field(default_factory=list)

    def __len__(self):
        return len(self.wallets)


# ---------------------------------------------------------------------------
# Step 1 - who traded in this market
# ---------------------------------------------------------------------------

def summarise_wallets(trades, market):
    """Roll a market's trades up into one row per wallet.

    Takes the trade records the collector returns and gives back a
    WalletInMarket for each distinct proxyWallet.
    """

    summaries = {}

    for trade in trades:
        wallet = trade["proxyWallet"]

        if wallet not in summaries:
            summaries[wallet] = WalletInMarket(
                wallet=wallet,
                market=market,
                first_seen=trade["timestamp"],
                last_seen=trade["timestamp"],
            )

        row = summaries[wallet]
        cash = float(trade["size"]) * float(trade["price"])

        row.trade_count += 1
        row.cash_traded += cash
        row.largest_trade = max(row.largest_trade, cash)
        row.first_seen = min(row.first_seen, trade["timestamp"])
        row.last_seen = max(row.last_seen, trade["timestamp"])

        if trade["side"] == "BUY":
            row.buy_count += 1
        else:
            row.sell_count += 1

    return list(summaries.values())


def looks_like_a_market_maker(row):
    """Quoting both sides, many times. A different job, not a suspicious one.

    Deliberately crude, and deliberately not a deletion - see the spec. The
    point is to keep this population identifiable, not to decide who is
    genuinely a market maker, which we cannot know.
    """

    return row.trades_both_sides and row.trade_count >= MARKET_MAKER_MIN_TRADES


# ---------------------------------------------------------------------------
# Step 2 - the sampling frame
# ---------------------------------------------------------------------------

def build_frame(trades_by_market, exclude_wallets=()):
    """Every wallet that traded in the given markets, labelled by stratum.

    trades_by_market:  {"maduro": [trade, ...], "nobel": [...]}
    exclude_wallets:   the candidate wallets under investigation. A control
                       group containing the cases it is meant to be compared
                       against is not a control group.

    A wallet appearing in three markets produces three rows. That is
    intentional: the unit is a wallet *in a market*, because "unusual" is
    judged inside a market.
    """

    excluded_set = {w.lower() for w in exclude_wallets}
    frame = []

    for market, trades in trades_by_market.items():
        for row in summarise_wallets(trades, market):

            if row.wallet.lower() in excluded_set:
                row.stratum = EXCLUDED
                row.excluded_because = "candidate wallet under investigation"
            elif looks_like_a_market_maker(row):
                row.stratum = MARKET_MAKER

            frame.append(row)

    return frame


# ---------------------------------------------------------------------------
# Step 3 - draw the sample
# ---------------------------------------------------------------------------

def draw_cohort(frame, size, seed, market_maker_share=0.1):
    """Draw `size` wallet-market rows, proportionally across markets.

    Two rules, both to stop one thing swamping the baseline:

      * Markets contribute in proportion to how many wallets they have, so a
        busy market does not drown a quiet one.
      * Market makers are capped at market_maker_share of the cohort. They are
        included because they are part of normal market behaviour and a
        detector that flags all of them is useless; they are capped because
        they trade orders of magnitude more than anyone else.

    Returns a Cohort carrying the seed and the counts, so the draw can be
    reported and repeated.
    """

    rng = random.Random(seed)

    eligible = [row for row in frame if row.stratum != EXCLUDED]
    excluded = [row for row in frame if row.stratum == EXCLUDED]

    makers = [row for row in eligible if row.stratum == MARKET_MAKER]
    ordinary = [row for row in eligible if row.stratum == ORDINARY]

    maker_target = min(len(makers), int(size * market_maker_share))
    ordinary_target = min(len(ordinary), size - maker_target)

    drawn = (
        _draw_proportionally(ordinary, ordinary_target, rng)
        + rng.sample(makers, maker_target)
    )
    rng.shuffle(drawn)

    return Cohort(
        wallets=drawn,
        seed=seed,
        frame_size=len(eligible),
        counts_by_stratum={
            ORDINARY: sum(1 for r in drawn if r.stratum == ORDINARY),
            MARKET_MAKER: sum(1 for r in drawn if r.stratum == MARKET_MAKER),
        },
        excluded=excluded,
    )


def _draw_proportionally(rows, target, rng):
    """Split `target` across markets in proportion to each market's size."""

    if target <= 0 or not rows:
        return []

    by_market = defaultdict(list)
    for row in rows:
        by_market[row.market].append(row)

    total = len(rows)
    drawn = []

    for market, market_rows in sorted(by_market.items()):
        share = int(round(target * len(market_rows) / total))
        drawn += rng.sample(market_rows, min(share, len(market_rows)))

    # Rounding can leave us a few short or a few over.
    if len(drawn) > target:
        drawn = rng.sample(drawn, target)
    elif len(drawn) < target:
        remaining = [r for r in rows if r not in drawn]
        drawn += rng.sample(remaining, min(target - len(drawn), len(remaining)))

    return drawn


# ---------------------------------------------------------------------------
# Step 4 - what will this cost us
# ---------------------------------------------------------------------------

# Requests per wallet, from the WS4 endpoint list. Each endpoint pages at 500
# records, and most wallets fit in one or two pages; the averages below are
# rounded up so the estimate is a ceiling rather than a hope.
CALLS_PER_WALLET = {
    # Full history from start=1, collected as one window that splits when the
    # 5,000-record cap is hit. Measured at ~20 requests for an active wallet.
    # This was 3 until 9 Sep, when the first live run showed a wallet costing
    # 2,969 requests: 7-day windows against start=1 walk 1970 to today one
    # week at a time. See docs/control_cohort_spec.md 5.
    "/activity": 20,
    "/closed-positions": 2,   # realised P&L
    "/positions": 1,          # open positions
}

# Requests per second the collector actually makes (collectors/session.py
# paces at one every 0.3s). The documented ceilings are far higher: /trades
# 200 req/10s, /positions and /closed-positions 150 req/10s each (WS4 3.3).
REQUESTS_PER_SECOND = 1 / 0.3

RATE_LIMITS_PER_SECOND = {
    "/trades": 20.0,
    "/activity": 100.0,
    "/positions": 15.0,
    "/closed-positions": 15.0,
}


def estimate_api_calls(cohort, market_collection_calls=0):
    """How many requests the cohort costs, and how long that takes.

    market_collection_calls: requests already spent pulling the markets' trades
    (the Maduro market took 90). Pass it in to get a whole-job total.
    """

    distinct_wallets = len({row.wallet for row in cohort.wallets})
    per_endpoint = {
        endpoint: distinct_wallets * calls
        for endpoint, calls in CALLS_PER_WALLET.items()
    }

    total = sum(per_endpoint.values()) + market_collection_calls
    seconds = total / REQUESTS_PER_SECOND

    return {
        "cohort_rows": len(cohort),
        "distinct_wallets": distinct_wallets,
        "calls_per_endpoint": per_endpoint,
        "market_collection_calls": market_collection_calls,
        "total_calls": total,
        "estimated_minutes": round(seconds / 60, 1),
        "our_requests_per_second": round(REQUESTS_PER_SECOND, 2),
        "headroom": {
            endpoint: "{:.0f}x under the limit".format(limit / REQUESTS_PER_SECOND)
            for endpoint, limit in RATE_LIMITS_PER_SECOND.items()
        },
    }
