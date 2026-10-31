from datetime import datetime, timezone
from decimal import Decimal as D

import pytest

from ict_engine.models import Candle
from ict_engine.paper_execution import calculate_position_size, resolve_barrier_exit


def bar(o, h, l, c):
    return Candle(datetime(2026, 1, 1, 9, 15, tzinfo=timezone.utc), D(str(o)), D(str(h)), D(str(l)), D(str(c)))


def test_position_size_respects_risk_budget_and_costs():
    result = calculate_position_size(
        risk_budget=D("1000"), entry=D("100"), stop=D("90"),
        point_value=D("1"), quantity_step=D("1"),
        round_trip_fees_per_unit=D("2"), round_trip_slippage_points=D("1"),
    )
    assert result.risk_per_unit == D("13")
    assert result.quantity == D("76")
    assert result.planned_risk == D("988")


def test_too_small_budget_rejected():
    with pytest.raises(ValueError):
        calculate_position_size(
            risk_budget=D("5"), entry=D("100"), stop=D("90"),
            point_value=D("1"), quantity_step=D("1"),
        )


def test_long_stop_gap_fills_at_open_not_stop():
    result = resolve_barrier_exit(bar(85, 90, 80, 88), direction="long", stop=D("90"), target=D("120"))
    assert result.reason == "stop_loss"
    assert result.price == D("85")
    assert result.gap_through_stop


def test_same_bar_stop_and_target_uses_conservative_stop():
    result = resolve_barrier_exit(bar(100, 125, 85, 110), direction="long", stop=D("90"), target=D("120"))
    assert result.reason == "stop_loss"
    assert result.price == D("90")
    assert result.ambiguous_bar


def test_short_target_gap_gets_favourable_open_fill():
    result = resolve_barrier_exit(bar(85, 90, 80, 88), direction="short", stop=D("110"), target=D("90"))
    assert result.reason == "take_profit"
    assert result.price == D("85")
