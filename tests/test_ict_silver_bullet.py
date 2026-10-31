from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import pytest
from ict_engine.context import LiquidityLevel
from ict_engine.models import Candle
from ict_engine.sessions import SessionWindow
from ict_engine.ict_silver_bullet_2023 import detect_silver_bullet_candidate

def candle(i, o, h, l, close):
    return Candle(datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc) + timedelta(minutes=i), D(str(o)), D(str(h)), D(str(l)), D(str(close)))

def window(end_minute=60):
    start = datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc)
    return SessionWindow("test_window", start, start + timedelta(minutes=end_minute))

def bullish_draw():
    return LiquidityLevel("Prior high", D("105"), "buy_side", "previous_day_high")

def test_silver_bullet_requires_first_fvg_and_retest_inside_window():
    candles = [
        candle(0, 99, 100, 98, 99),
        candle(1, 100, 102, 99, 101),
        candle(2, 102, 103, 100.5, 102.5),
        candle(3, 101, 101.2, 100.2, 100.8),
    ]
    candidate = detect_silver_bullet_candidate(candles, window=window(), direction="bullish", draw_on_liquidity=bullish_draw(), bar_duration=timedelta(minutes=1), timestamp_role="start")
    assert candidate is not None
    assert candidate.fvg.lower == D("100")
    assert candidate.fvg.upper == D("100.5")
    assert candidate.retest_candle_index == 3
    assert candidate.fvg_completed_at == datetime(2026, 1, 15, 10, 3, tzinfo=timezone.utc)

def test_silver_bullet_rejects_retest_after_window_end():
    candles = [
        candle(0, 99, 100, 98, 99),
        candle(1, 100, 102, 99, 101),
        candle(2, 102, 103, 100.5, 102.5),
        candle(3, 101, 102, 100.8, 101.5),
        candle(4, 101, 101.2, 100.2, 100.8),
    ]
    candidate = detect_silver_bullet_candidate(candles, window=window(4), direction="bullish", draw_on_liquidity=bullish_draw(), bar_duration=timedelta(minutes=1), timestamp_role="start")
    assert candidate is None

def test_silver_bullet_rejects_wrong_side_draw():
    candles = [candle(0, 99, 100, 98, 99), candle(1, 100, 102, 99, 101), candle(2, 102, 103, 100.5, 102.5), candle(3, 101, 101.2, 100.2, 100.8)]
    wrong_draw = LiquidityLevel("Prior low", D("95"), "sell_side", "previous_day_low")
    with pytest.raises(ValueError):
        detect_silver_bullet_candidate(candles, window=window(), direction="bullish", draw_on_liquidity=wrong_draw, bar_duration=timedelta(minutes=1), timestamp_role="start")

def test_silver_bullet_rejects_naive_window():
    candles = [candle(0, 99, 100, 98, 99)]
    bad_window = SessionWindow("bad", datetime(2026,1,15,10,0), datetime(2026,1,15,11,0))
    with pytest.raises(ValueError):
        detect_silver_bullet_candidate(candles, window=bad_window, direction="bullish", draw_on_liquidity=bullish_draw(), bar_duration=timedelta(minutes=1), timestamp_role="start")