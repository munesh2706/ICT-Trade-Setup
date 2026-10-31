"""Source-versioned ICT Silver Bullet 2023 candidate detection.

The detector intentionally requires an externally established directional draw
on liquidity. It does not manufacture a bias from the FVG itself.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Literal, Sequence

from .context import LiquidityLevel
from .models import Candle, FairValueGap
from .sessions import NEW_YORK, SessionWindow
from .ict_2022_episode6 import fair_value_gaps

@dataclass(frozen=True, slots=True)
class SilverBulletCandidate:
    model: str
    direction: str
    window_name: str
    window_start: datetime
    window_end: datetime
    fvg: FairValueGap
    fvg_completed_at: datetime
    retest_candle_index: int
    entry_zone_lower: Decimal
    entry_zone_upper: Decimal
    draw_on_liquidity: LiquidityLevel
    source_id: str
    assumptions: tuple[str, ...]

def detect_silver_bullet_candidate(
    candles: Sequence[Candle],
    *,
    window: SessionWindow,
    direction: Literal["bullish", "bearish"],
    draw_on_liquidity: LiquidityLevel,
    bar_duration: timedelta,
    timestamp_role: Literal["start", "close"],
) -> SilverBulletCandidate | None:
    """Return the first direction-aligned FVG that retests inside the window.

    Candle timestamps must consistently identify either interval start or
    interval close; this is mandatory because provider timestamp semantics
    vary. Only fully completed formation/retest bars inside the time window
    are considered. A missed first FVG does not silently fall through to a
    later FVG in the same window.
    """
    if direction not in {"bullish", "bearish"}:
        raise ValueError("direction must be bullish or bearish")
    if timestamp_role not in {"start", "close"}:
        raise ValueError("timestamp_role must be start or close")
    if bar_duration <= timedelta(0):
        raise ValueError("bar_duration must be positive")
    if window.start.tzinfo is None or window.end.tzinfo is None:
        raise ValueError("window boundaries must be timezone-aware")
    if window.end <= window.start:
        raise ValueError("window end must be after start")
    expected_windows = {"london_open": (time(3, 0), time(4, 0)), "new_york_am": (time(10, 0), time(11, 0)), "new_york_pm": (time(14, 0), time(15, 0))}
    if window.name not in expected_windows:
        raise ValueError("window name is not one of the source-defined Silver Bullet windows")
    start_ny = window.start.astimezone(NEW_YORK)
    end_ny = window.end.astimezone(NEW_YORK)
    expected_start, expected_end = expected_windows[window.name]
    if start_ny.date() != end_ny.date() or start_ny.time() != expected_start or end_ny.time() != expected_end:
        raise ValueError("window boundaries do not match the source-defined New York-local window")
    if not candles:
        return None
    if any(c.timestamp.tzinfo is None for c in candles):
        raise ValueError("all candle timestamps must be timezone-aware")
    if any(candles[i].timestamp >= candles[i + 1].timestamp for i in range(len(candles) - 1)):
        raise ValueError("candles must be strictly chronological")
    expected_side = "buy_side" if direction == "bullish" else "sell_side"
    if draw_on_liquidity.side != expected_side:
        raise ValueError("draw-on-liquidity side conflicts with candidate direction")

    def interval(index: int) -> tuple[datetime, datetime]:
        stamp = candles[index].timestamp
        if timestamp_role == "start":
            return stamp, stamp + bar_duration
        return stamp - bar_duration, stamp

    gaps = [g for g in fair_value_gaps(candles) if g.direction == direction]
    for gap in gaps:
        first_start, _ = interval(gap.first_candle_index)
        _, fvg_close = interval(gap.third_candle_index)
        if first_start < window.start or fvg_close > window.end:
            continue
        if direction == "bullish" and draw_on_liquidity.price <= gap.upper:
            raise ValueError("bullish draw-on-liquidity must be above the FVG")
        if direction == "bearish" and draw_on_liquidity.price >= gap.lower:
            raise ValueError("bearish draw-on-liquidity must be below the FVG")
        # This is the first qualifying directional FVG in the window.
        for index in range(gap.third_candle_index + 1, len(candles)):
            retest_start, retest_end = interval(index)
            if retest_start < fvg_close:
                continue
            if retest_start < window.start or retest_end > window.end:
                continue
            candle = candles[index]
            intersects = candle.low <= gap.upper and candle.high >= gap.lower
            if intersects:
                return SilverBulletCandidate(
                    model="ICT_SILVER_BULLET_2023",
                    direction=direction,
                    window_name=window.name,
                    window_start=window.start,
                    window_end=window.end,
                    fvg=gap,
                    fvg_completed_at=fvg_close,
                    retest_candle_index=index,
                    entry_zone_lower=gap.lower,
                    entry_zone_upper=gap.upper,
                    draw_on_liquidity=draw_on_liquidity,
                    source_id="ICT-2023-Mentorship-Silver-Bullet-2023-05-14",
                    assumptions=(
                        "direction and draw-on-liquidity are supplied by separate context analysis",
                        "first directional FVG is selected; later FVGs are not substituted if it misses",
                        "retest requires a fully completed candle inside the named window",
                        "FVG overlap identifies an entry opportunity, not an exact fill price",
                        "stop placement and target-taking variants remain separate execution choices",
                    ),
                )
        # Do not silently select a later FVG if the first one did not retest.
        return None
    return None