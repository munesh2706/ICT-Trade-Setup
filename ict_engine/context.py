"""ICT context primitives: dealing ranges and externally supplied liquidity levels.

These functions calculate price references; they do not decide directional bias.
Period boundaries and source candles must be supplied by a calendar-aware data
layer. No session boundaries are inferred here.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from .models import Candle, FairValueGap

ZERO = Decimal("0")
HALF = Decimal("0.5")


@dataclass(frozen=True, slots=True)
class LiquidityLevel:
    name: str
    price: Decimal
    side: str  # buy_side or sell_side
    source: str
    reference_time: object | None = None


@dataclass(frozen=True, slots=True)
class DealingRange:
    high: Decimal
    low: Decimal
    equilibrium: Decimal
    premium_boundary: Decimal
    discount_boundary: Decimal


@dataclass(frozen=True, slots=True)
class LiquidityPool:
    side: str
    level: Decimal
    member_prices: tuple[Decimal, ...]
    source: str
    tolerance: Decimal


@dataclass(frozen=True, slots=True)
class PDArrayReference:
    array_type: str
    direction: str
    lower: Decimal
    upper: Decimal
    consequent_encroachment: Decimal
    source_indices: tuple[int, ...]


def dealing_range(high: Decimal, low: Decimal) -> DealingRange:
    """Return midpoint and halves of a user/source-defined dealing range."""
    if high <= low:
        raise ValueError("dealing range high must be greater than low")
    midpoint = (high + low) * HALF
    return DealingRange(high, low, midpoint, midpoint, midpoint)


def classify_premium_discount(price: Decimal, range_: DealingRange) -> str:
    """Classify price relative to equilibrium; equality is equilibrium."""
    if price > range_.equilibrium:
        return "premium"
    if price < range_.equilibrium:
        return "discount"
    return "equilibrium"


def previous_period_levels(
    completed_period_candles: Sequence[Candle], *, period_name: str
) -> tuple[LiquidityLevel, LiquidityLevel]:
    """Build high/low liquidity references from one completed period candle set.

    The caller is responsible for selecting the correct completed prior day,
    week, or other period using the exchange calendar and Asia/Kolkata timezone.
    """
    if not completed_period_candles:
        raise ValueError("completed period candles cannot be empty")
    high_candle = max(completed_period_candles, key=lambda c: c.high)
    low_candle = min(completed_period_candles, key=lambda c: c.low)
    high = max(c.high for c in completed_period_candles)
    low = min(c.low for c in completed_period_candles)
    return (
        LiquidityLevel(f"Previous {period_name} High", high, "buy_side", "completed_prior_period", high_candle.timestamp),
        LiquidityLevel(f"Previous {period_name} Low", low, "sell_side", "completed_prior_period", low_candle.timestamp),
    )


def equal_high_low_pools(
    candles: Sequence[Candle], *, tolerance: Decimal, min_touches: int = 2
) -> list[LiquidityPool]:
    """Cluster repeated highs/lows within explicit absolute price tolerance.

    Tolerance is an engineering parameter. It must be calibrated to instrument
    tick size/price scale and is never silently inferred.
    """
    if tolerance < ZERO:
        raise ValueError("tolerance cannot be negative")
    if min_touches < 2:
        raise ValueError("min_touches must be >= 2")
    pools: list[LiquidityPool] = []
    for side, values in (
        ("buy_side", [c.high for c in candles]),
        ("sell_side", [c.low for c in candles]),
    ):
        clusters: list[list[Decimal]] = []
        for value in sorted(values):
            if not clusters or value - clusters[-1][-1] > tolerance:
                clusters.append([value])
            else:
                clusters[-1].append(value)
        for cluster in clusters:
            if len(cluster) >= min_touches:
                pools.append(LiquidityPool(side, sum(cluster) / Decimal(len(cluster)), tuple(cluster), "relative_equal_highs_lows", tolerance))
    return pools


def fvg_pd_array(gap: FairValueGap) -> PDArrayReference:
    """Expose an FVG and its 50% consequent encroachment reference."""
    if gap.upper <= gap.lower:
        raise ValueError("FVG upper boundary must exceed lower boundary")
    ce = (gap.lower + gap.upper) * HALF
    return PDArrayReference(
        "FVG", gap.direction, gap.lower, gap.upper, ce,
        (gap.first_candle_index, gap.middle_candle_index, gap.third_candle_index),
    )
