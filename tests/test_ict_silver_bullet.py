from datetime import date, datetime, timedelta
from decimal import Decimal as D
from zoneinfo import ZoneInfo
import pytest
from ict_engine.context import LiquidityLevel
from ict_engine.models import Candle
from ict_engine.sessions import SessionWindow, silver_bullet_windows_ist
from ict_engine.ict_silver_bullet_2023 import detect_silver_bullet_candidate

WINDOW = next(w for w in silver_bullet_windows_ist(date(2026,1,15)) if w.name == "london_open")

def candle(i, o, h, l, close):
    return Candle(WINDOW.start + timedelta(minutes=i), D(str(o)), D(str(h)), D(str(l)), D(str(close)))

def bullish_draw():
    return LiquidityLevel("Prior high", D("105"), "buy_side", "previous_day_high")

def test_silver_bullet_requires_first_fvg_and_retest_inside_window():
    candles = [candle(0, 99, 100, 98, 99), candle(1, 100, 102, 99, 101), candle(2, 102, 103, 100.5, 102.5), candle(3, 101, 101.2, 100.2, 100.8)]
    candidate = detect_silver_bullet_candidate(candles, window=WINDOW, direction="bullish", draw_on_liquidity=bullish_draw(), bar_duration=timedelta(minutes=1), timestamp_role="start")
    assert candidate is not None
    assert candidate.fvg.lower == D("100")
    assert candidate.fvg.upper == D("100.5")
    assert candidate.retest_candle_index == 3
    assert candidate.fvg_completed_at == WINDOW.start + timedelta(minutes=3)

def test_silver_bullet_rejects_retest_after_window_end():
    candles = [candle(i, 100, 100.1, 99.9, 100) for i in range(61)]
    candles[56] = candle(56, 99, 100, 98, 99)
    candles[57] = candle(57, 100, 102, 99, 101)
    candles[58] = candle(58, 102, 103, 100.5, 102.5)
    candles[59] = candle(59, 101, 102, 100.8, 101.5)
    candles[60] = candle(60, 101, 101.2, 100.2, 100.8)
    candidate = detect_silver_bullet_candidate(candles, window=WINDOW, direction="bullish", draw_on_liquidity=bullish_draw(), bar_duration=timedelta(minutes=1), timestamp_role="start")
    assert candidate is None

def test_silver_bullet_rejects_wrong_side_draw():
    candles = [candle(0, 99, 100, 98, 99), candle(1, 100, 102, 99, 101), candle(2, 102, 103, 100.5, 102.5), candle(3, 101, 101.2, 100.2, 100.8)]
    wrong_draw = LiquidityLevel("Prior low", D("95"), "sell_side", "previous_day_low")
    with pytest.raises(ValueError):
        detect_silver_bullet_candidate(candles, window=WINDOW, direction="bullish", draw_on_liquidity=wrong_draw, bar_duration=timedelta(minutes=1), timestamp_role="start")

def test_silver_bullet_rejects_naive_window():
    candles = [candle(0, 99, 100, 98, 99)]
    bad_window = SessionWindow("london_open", datetime(2026,1,15,3,0), datetime(2026,1,15,4,0))
    with pytest.raises(ValueError):
        detect_silver_bullet_candidate(candles, window=bad_window, direction="bullish", draw_on_liquidity=bullish_draw(), bar_duration=timedelta(minutes=1), timestamp_role="start")

def test_silver_bullet_rejects_custom_time_window():
    bad_window = SessionWindow("custom", WINDOW.start, WINDOW.end)
    with pytest.raises(ValueError):
        detect_silver_bullet_candidate([], window=bad_window, direction="bullish", draw_on_liquidity=bullish_draw(), bar_duration=timedelta(minutes=1), timestamp_role="start")