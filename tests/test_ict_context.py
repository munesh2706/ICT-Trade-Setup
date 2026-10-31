from datetime import datetime, timezone
from decimal import Decimal as D

import pytest

from ict_engine.context import (
    classify_premium_discount, dealing_range, equal_high_low_pools,
    fvg_pd_array, previous_period_levels,
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
