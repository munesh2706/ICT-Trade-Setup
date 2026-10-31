from datetime import datetime, timezone
from decimal import Decimal as D

import pytest

from ict_engine.context import (
    classify_premium_discount, dealing_range, equal_high_low_pools,
    fvg_pd_array, previous_period_levels, directional_target_candidates, LiquidityLevel,
)
from ict_engine.ict_2022_episode6 import fair_value_gaps
from ict_engine.models import Candle


def candle(i, high, low):
    return Candle(datetime(2026, 1, i + 1, 9, 15, tzinfo=timezone.utc), D(str(low)), D(str(high)), D(str(low)), D(str(high)))


def test_dealing_range_premium_discount_and_equilibrium():
    dr = dealing_range(D("200"), D("100"))
    assert dr.equilibrium == D("150")
    assert classify_premium_discount(D("175"), dr) == "premium"
    assert classify_premium_discount(D("125"), dr) == "discount"
    assert classify_premium_discount(D("150"), dr) == "equilibrium"


def test_previous_period_high_low_are_based_on_completed_candles():
    levels = previous_period_levels([candle(0, 110, 95), candle(1, 120, 90)], period_name="Day")
    assert levels[0].price == D("120")
    assert levels[0].side == "buy_side"
    assert levels[1].price == D("90")
    assert levels[1].side == "sell_side"


def test_equal_highs_cluster_only_with_explicit_tolerance():
    pools = equal_high_low_pools(
        [candle(0, 100, 90), candle(1, 100.2, 89.8), candle(2, 110, 80)],
        tolerance=D("0.25"),
    )
    bsl = next(p for p in pools if p.side == "buy_side")
    assert len(bsl.member_prices) == 2
    assert bsl.level == D("100.1")


def test_fvg_consequent_encroachment_is_midpoint():
    candles = [
        Candle(datetime(2026,1,1,9,15,tzinfo=timezone.utc),D("10"),D("12"),D("9"),D("11")),
        Candle(datetime(2026,1,1,9,16,tzinfo=timezone.utc),D("11"),D("11"),D("8"),D("8.5")),
        Candle(datetime(2026,1,1,9,17,tzinfo=timezone.utc),D("8"),D("8.5"),D("7"),D("7.5")),
    ]
    gap = fair_value_gaps(candles)[0]
    pd = fvg_pd_array(gap)
    assert pd.consequent_encroachment == D("8.75")


def test_invalid_dealing_range_rejected():
    with pytest.raises(ValueError):
        dealing_range(D("10"), D("10"))

def test_equal_high_pool_does_not_chain_beyond_total_tolerance():
    pools = equal_high_low_pools(
        [candle(0, 100, 90), candle(1, 100.2, 89.8), candle(2, 100.4, 89.6)],
        tolerance=D("0.25"),
    )
    bsl = [p for p in pools if p.side == "buy_side"]
    assert len(bsl) == 1
    assert len(bsl[0].member_prices) == 2
    assert max(bsl[0].member_prices) - min(bsl[0].member_prices) <= D("0.25")

def test_directional_target_candidates_keep_all_valid_levels_nearest_first():
    levels = [
        LiquidityLevel("PDH", D("110"), "buy_side", "previous_day_high"),
        LiquidityLevel("PWH", D("120"), "buy_side", "previous_week_high"),
        LiquidityLevel("PDL", D("90"), "sell_side", "previous_day_low"),
    ]
    bullish = directional_target_candidates("bullish", D("100"), levels)
    bearish = directional_target_candidates("bearish", D("100"), levels)
    assert [x.name for x in bullish] == ["PDH", "PWH"]
    assert [x.name for x in bearish] == ["PDL"]

def test_market_context_combines_day_week_and_equal_liquidity_without_bias():
    from ict_engine.context import LiquidityPool, build_market_context
    day = [candle(0, 110, 90)]
    week = [candle(1, 120, 80)]
    pools = [
        LiquidityPool("buy_side", D("115"), (D("114.9"), D("115.1")), "relative_equal_highs_lows", D("0.2")),
        LiquidityPool("sell_side", D("85"), (D("84.9"), D("85.1")), "relative_equal_highs_lows", D("0.2")),
    ]
    context = build_market_context(
        current_price=D("100"), dealing_range_high=D("120"), dealing_range_low=D("80"),
        previous_day_candles=day, previous_week_candles=week, relative_equal_pools=pools,
    )
    assert context.price_location == "equilibrium"
    assert [x.price for x in context.draws_above] == [D("110"), D("115"), D("120")]
    assert [x.price for x in context.draws_below] == [D("90"), D("85")]
