from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from ict_engine.ict_2022_episode6 import fair_value_gaps, confirmed_swings, liquidity_sweeps, detect_ict_2022_episode6
from ict_engine.models import Candle, SwingPoint, ExternalLiquiditySweep
from ict_engine.context import LiquidityLevel

def c(i, o, h, l, close):
    return Candle(datetime(2026, 1, 1, 9, 15, tzinfo=timezone.utc) + timedelta(minutes=i), D(str(o)), D(str(h)), D(str(l)), D(str(close)))

def test_bearish_fvg_uses_first_low_and_third_high():
    candles = [c(0, 10, 12, 9, 11), c(1, 11, 11, 8, 8.5), c(2, 8, 8.5, 7, 7.5)]
    gaps = fair_value_gaps(candles)
    assert len(gaps) == 1
    assert gaps[0].direction == "bearish"
    assert gaps[0].lower == D("8.5")
    assert gaps[0].upper == D("9")

def test_bullish_fvg_uses_first_high_and_third_low():
    candles = [c(0, 9, 10, 8, 9), c(1, 9, 12, 9, 11), c(2, 11, 13, 10.5, 12)]
    gaps = fair_value_gaps(candles)
    assert len(gaps) == 1
    assert gaps[0].direction == "bullish"
    assert gaps[0].lower == D("10")
    assert gaps[0].upper == D("10.5")

def test_swing_is_not_confirmed_until_right_bars_exist():
    candles = [c(0, 9, 10, 8, 9), c(1, 9, 12, 9, 11), c(2, 11, 11, 9, 10), c(3, 10, 10, 8, 9)]
    swings = confirmed_swings(candles, left=1, right=1)
    high = next(s for s in swings if s.kind == "high")
    assert high.pivot_index == 1
    assert high.confirmed_at_index == 2

def test_liquidity_run_does_not_require_same_bar_close_back_inside():
    candles = [c(0, 9, 10, 8, 9), c(1, 10, 12, 9.5, 11.5)]
    swing = SwingPoint(pivot_index=0, confirmed_at_index=0, price=D("10"), kind="high")
    sweeps = liquidity_sweeps(candles, [swing])
    assert len(sweeps) == 1
    assert sweeps[0].direction == "buy_side"

def test_complete_bearish_episode6_candidate_is_available_only_after_fvg_closes():
    candles = [
        c(0, 9, 10, 8, 9),
        c(1, 10, 11, 9, 10),
        c(2, 9, 10, 7, 8),
        c(3, 9, 10.5, 8, 9),
        c(4, 11, 12, 9, 11),
        c(5, 10, 11, 8, 9),
        c(6, 12, 13, 10, 12.5),
        c(7, 10, 10.5, 5.5, 6),
        c(8, 6, 9.5, 6, 8.5),
    ]
    candidates = detect_ict_2022_episode6(
        candles, pivot_left=1, pivot_right=1,
        displacement_min_body_to_range=D("0.5"),
        max_bars_after_sweep=3, max_bars_after_mss=3,
    )
    candidate = next(c for c in candidates if c.sweep.reference_swing.pivot_index == 4)
    assert candidate.direction == "bearish"
    assert candidate.sweep.candle_index == 6
    assert candidate.mss.candle_index == 7
    assert candidate.fvg.third_candle_index == 8
    assert candidate.available_at_index == 8
    assert candidate.displacement_range_high == D("13")
    assert candidate.displacement_range_low == D("5.5")
    assert candidate.invalidation_references == (D("13"), D("10.5"))

def test_episode6_accepts_previous_day_external_liquidity_sweep():
    candles = [
        c(0, 9, 10, 8, 9), c(1, 10, 11, 9, 10), c(2, 9, 10, 7, 8),
        c(3, 9, 10.5, 8, 9), c(4, 11, 12, 9, 11), c(5, 10, 11, 8, 9),
        c(6, 12, 13, 10, 12.5), c(7, 10, 10.5, 5.5, 6), c(8, 6, 9.5, 6, 8.5),
    ]
    levels = [LiquidityLevel("Previous Day High", D("12.5"), "buy_side", "previous_day_high")]
    candidates = detect_ict_2022_episode6(
        candles, pivot_left=1, pivot_right=1,
        displacement_min_body_to_range=D("0.5"),
        max_bars_after_sweep=3, max_bars_after_mss=3,
        external_liquidity_levels=levels,
    )
    candidate = next(x for x in candidates if isinstance(x.sweep, ExternalLiquiditySweep))
    assert candidate.sweep.reference_name == "Previous Day High"
    assert candidate.direction == "bearish"


def test_episode6_rejects_fvg_outside_frozen_displacement_range():
    candles = [
        c(0, 9, 10, 8, 9), c(1, 10, 11, 9, 10), c(2, 9, 10, 7, 8),
        c(3, 9, 10.5, 8, 9), c(4, 11, 12, 9, 11), c(5, 10, 11, 8, 9),
        c(6, 12, 13, 10, 12.5), c(7, 10, 10.5, 5.5, 6),
        c(8, 4, 4.5, 3, 4),
    ]
    candidates = detect_ict_2022_episode6(
        candles, pivot_left=1, pivot_right=1,
        displacement_min_body_to_range=D("0.5"),
        max_bars_after_sweep=3, max_bars_after_mss=3,
    )
    assert candidates == []
