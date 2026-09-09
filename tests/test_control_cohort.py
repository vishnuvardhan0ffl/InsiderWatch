"""
Control cohort sampling (processing/control_cohort.py).

The cohort decides what "normal" means, so a bug here does not produce an
error - it produces a plausible baseline that is quietly wrong, and every
threshold calibrated against it inherits the mistake. Hence the emphasis on
the properties that have to hold: the draw repeats, candidates never leak in,
and no single market dominates.
"""

import pytest

from processing.control_cohort import (
    CALLS_PER_WALLET,
    MARKET_MAKER,
    ORDINARY,
    build_frame,
    draw_cohort,
    estimate_api_calls,
    looks_like_a_market_maker,
    summarise_wallets,
)


def trade(wallet, side="BUY", size=100, price=0.5, timestamp=1_700_000_000):
    return {
        "proxyWallet": wallet, "side": side, "size": size,
        "price": price, "timestamp": timestamp,
    }


def many_trades(wallet, count, alternate_sides=False):
    return [
        trade(wallet,
              side="SELL" if alternate_sides and i % 2 else "BUY",
              timestamp=1_700_000_000 + i)
        for i in range(count)
    ]


# ===========================================================================
# Summarising one market
# ===========================================================================

def test_each_wallet_becomes_one_row():
    rows = summarise_wallets(
        [trade("0xa"), trade("0xa"), trade("0xb")], market="m1"
    )

    assert {row.wallet for row in rows} == {"0xa", "0xb"}
    assert {row.trade_count for row in rows} == {2, 1}


def test_cash_traded_is_size_times_price_not_size():
    """size is outcome shares. 100 shares at $0.30 is $30, not $100."""

    row = summarise_wallets([trade("0xa", size=100, price=0.3)], "m1")[0]

    assert row.cash_traded == pytest.approx(30.0)


def test_first_and_last_seen_bracket_the_wallet_activity():
    rows = summarise_wallets([
        trade("0xa", timestamp=200),
        trade("0xa", timestamp=100),
        trade("0xa", timestamp=300),
    ], "m1")

    assert (rows[0].first_seen, rows[0].last_seen) == (100, 300)
    assert rows[0].active_seconds == 200


def test_the_largest_trade_is_kept():
    """The size of a trader's biggest bet is a headline feature."""

    row = summarise_wallets([
        trade("0xa", size=10, price=0.5),
        trade("0xa", size=1000, price=0.9),
    ], "m1")[0]

    assert row.largest_trade == pytest.approx(900.0)


# ===========================================================================
# Market makers
# ===========================================================================

def test_a_two_sided_high_volume_wallet_is_flagged():
    row = summarise_wallets(many_trades("0xmm", 40, alternate_sides=True), "m1")[0]

    assert looks_like_a_market_maker(row)


def test_a_one_sided_wallet_is_not_flagged_however_busy():
    """Buying 500 times is a view, not a quote. It may even be the signal."""

    row = summarise_wallets(many_trades("0xbull", 500), "m1")[0]

    assert not looks_like_a_market_maker(row)


def test_a_wallet_that_bought_then_sold_once_is_not_a_market_maker():
    """Entering and exiting is ordinary. Only sustained two-sided activity counts."""

    rows = summarise_wallets(
        [trade("0xa", side="BUY"), trade("0xa", side="SELL")], "m1"
    )

    assert not looks_like_a_market_maker(rows[0])


def test_market_makers_are_kept_in_their_own_stratum_not_deleted():
    """They are normal market behaviour. A detector flagging all of them is useless."""

    frame = build_frame({"m1": many_trades("0xmm", 40, alternate_sides=True)})

    assert [row.stratum for row in frame] == [MARKET_MAKER]


# ===========================================================================
# The frame
# ===========================================================================

def test_one_wallet_in_two_markets_gives_two_rows():
    """The unit is a wallet in a market - "unusual" is judged inside a market."""

    frame = build_frame({"m1": [trade("0xa")], "m2": [trade("0xa")]})

    assert len(frame) == 2
    assert {row.market for row in frame} == {"m1", "m2"}


def test_candidate_wallets_are_marked_excluded():
    """A control group containing the cases is not a control group."""

    frame = build_frame({"m1": [trade("0xcase"), trade("0xother")]},
                        exclude_wallets=["0xcase"])

    by_wallet = {row.wallet: row for row in frame}
    assert by_wallet["0xcase"].stratum == "excluded"
    assert by_wallet["0xcase"].excluded_because
    assert by_wallet["0xother"].stratum == ORDINARY


def test_exclusion_ignores_address_case():
    """0xABC and 0xabc are one wallet. Missing that leaks a case into the controls."""

    frame = build_frame({"m1": [trade("0xABC")]}, exclude_wallets=["0xabc"])

    assert frame[0].stratum == "excluded"


def test_low_activity_wallets_are_kept():
    """39% of wallets in the Maduro market made exactly one trade, and "new
    wallet, one large trade" is the signature we are hunting. Excluding them
    would remove the population the study is about."""

    frame = build_frame({"m1": [trade("0xa")]})

    assert frame[0].stratum == ORDINARY


# ===========================================================================
# The draw
# ===========================================================================

@pytest.fixture
def frame():
    trades = {
        "busy": [t for w in range(200) for t in [trade(f"0xbusy{w}")]],
        "quiet": [t for w in range(50) for t in [trade(f"0xquiet{w}")]],
    }
    trades["busy"] += many_trades("0xmm", 40, alternate_sides=True)
    return build_frame(trades)


def test_the_same_seed_draws_the_same_cohort(frame):
    """Without this the cohort is not reproducible, and nor is the baseline."""

    first = draw_cohort(frame, size=100, seed=42)
    second = draw_cohort(frame, size=100, seed=42)

    assert [r.wallet for r in first.wallets] == [r.wallet for r in second.wallets]


def test_a_different_seed_draws_a_different_cohort(frame):
    first = draw_cohort(frame, size=100, seed=42)
    other = draw_cohort(frame, size=100, seed=43)

    assert [r.wallet for r in first.wallets] != [r.wallet for r in other.wallets]


def test_the_cohort_records_the_seed_it_was_drawn_with(frame):
    assert draw_cohort(frame, size=100, seed=42).seed == 42


def test_excluded_wallets_never_appear_in_the_cohort():
    trades = {"m1": [trade(f"0xw{i}") for i in range(100)] + [trade("0xcase")]}
    frame = build_frame(trades, exclude_wallets=["0xcase"])

    cohort = draw_cohort(frame, size=101, seed=1)

    assert "0xcase" not in {row.wallet for row in cohort.wallets}
    assert len(cohort.excluded) == 1


def test_a_busy_market_does_not_swamp_a_quiet_one(frame):
    """Markets contribute in proportion, so the baseline is not one market's."""

    cohort = draw_cohort(frame, size=100, seed=7)
    per_market = {}
    for row in cohort.wallets:
        per_market[row.market] = per_market.get(row.market, 0) + 1

    # 200 busy wallets to 50 quiet ones, so roughly 4:1, not 100:0.
    assert per_market["quiet"] > 0
    assert per_market["busy"] / per_market["quiet"] == pytest.approx(4, abs=1.5)


def test_market_makers_are_capped_rather_than_filling_the_cohort(frame):
    cohort = draw_cohort(frame, size=100, seed=7, market_maker_share=0.1)

    assert cohort.counts_by_stratum[MARKET_MAKER] <= 10


def test_asking_for_more_than_exists_returns_everything_available():
    """No crash, no silent duplicates - just the whole frame."""

    frame = build_frame({"m1": [trade(f"0xw{i}") for i in range(10)]})

    cohort = draw_cohort(frame, size=500, seed=1)

    assert len(cohort) == 10
    assert len({row.wallet for row in cohort.wallets}) == 10


# ===========================================================================
# The API budget
# ===========================================================================

def test_the_budget_counts_distinct_wallets_not_rows():
    """A wallet in three markets is collected once, not three times."""

    frame = build_frame({"m1": [trade("0xa")], "m2": [trade("0xa")]})
    cohort = draw_cohort(frame, size=2, seed=1)

    estimate = estimate_api_calls(cohort)

    assert estimate["cohort_rows"] == 2
    assert estimate["distinct_wallets"] == 1


def test_the_budget_includes_the_market_collection_and_reports_time():
    frame = build_frame({"m1": [trade(f"0xw{i}") for i in range(100)]})
    cohort = draw_cohort(frame, size=100, seed=1)

    estimate = estimate_api_calls(cohort, market_collection_calls=810)

    per_wallet = sum(CALLS_PER_WALLET.values())
    assert estimate["total_calls"] == 100 * per_wallet + 810
    assert estimate["estimated_minutes"] > 0
    assert all("under the limit" in v for v in estimate["headroom"].values())
