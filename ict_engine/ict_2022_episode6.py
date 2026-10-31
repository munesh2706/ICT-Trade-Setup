"""Rule primitives for the ICT 2022 Mentorship Episode 6 model.

The qualitative source term 'energetic displacement' is operationalised by a
caller-supplied body/range threshold. That threshold is an engineering input,
not a threshold taught by ICT. No signal is emitted without it.
"""
from __future__ import annotations
from decimal import Decimal
from typing import Sequence
from .models import Candle, FairValueGap, ICT2022SetupCandidate, LiquiditySweep, MarketStructureShift, SwingPoint

ZERO = Decimal("0")

def confirmed_swings(candles: Sequence[Candle], left: int, right: int) -> list[SwingPoint]:
    """Return unique local pivots, timestamped as known only after right bars.

    Left/right widths and strict unique-extreme handling are engineering
    conventions; the source lesson does not prescribe a pivot algorithm.
    """
    if left < 1 or right < 1:
        raise ValueError("left and right must both be >= 1")
    found: list[SwingPoint] = []
    for i in range(left, len(candles) - right):
        window = candles[i-left:i+right+1]
        highs = [c.high for c in window]
        lows = [c.low for c in window]
        if candles[i].high == max(highs) and highs.count(candles[i].high) == 1:
            found.append(SwingPoint(i, i + right, candles[i].high, "high"))
        if candles[i].low == min(lows) and lows.count(candles[i].low) == 1:
            found.append(SwingPoint(i, i + right, candles[i].low, "low"))
    return sorted(found, key=lambda p: (p.confirmed_at_index, p.pivot_index, p.kind))

def fair_value_gaps(candles: Sequence[Candle]) -> list[FairValueGap]:
    """Detect three-candle ICT FVG geometry on completed candles."""
    gaps: list[FairValueGap] = []
    for i in range(2, len(candles)):
        first, middle, third = candles[i-2], candles[i-1], candles[i]
        if first.low > third.high:
            gaps.append(FairValueGap(i-2, i-1, i, third.high, first.low, "bearish"))
        if first.high < third.low:
            gaps.append(FairValueGap(i-2, i-1, i, first.high, third.low, "bullish"))
    return gaps

def liquidity_sweeps(candles: Sequence[Candle], swings: Sequence[SwingPoint]) -> list[LiquiditySweep]:
    """Detect wick-through-and-close-back events at already-confirmed swings."""
    events: list[LiquiditySweep] = []
    for i, candle in enumerate(candles):
        eligible = [s for s in swings if s.confirmed_at_index < i]
        for swing in eligible:
            if swing.kind == "high" and candle.high > swing.price and candle.close < swing.price:
                events.append(LiquiditySweep(i, swing, candle.high, "buy_side"))
            elif swing.kind == "low" and candle.low < swing.price and candle.close > swing.price:
                events.append(LiquiditySweep(i, swing, candle.low, "sell_side"))
    return events

def _body_to_range(candle: Candle) -> Decimal:
    full_range = candle.high - candle.low
    return ZERO if full_range == ZERO else abs(candle.close - candle.open) / full_range

def detect_ict_2022_episode6(candles: Sequence[Candle], *, pivot_left: int, pivot_right: int, displacement_min_body_to_range: Decimal) -> list[ICT2022SetupCandidate]:
    """Detect Episode 6 sweep -> displacement/MSS -> in-leg FVG candidates.

    Only completed candles should be passed. Pivot widths and displacement
    threshold are explicit engineering assumptions, not fixed ICT rules.
    """
    if not ZERO < displacement_min_body_to_range <= Decimal("1"):
        raise ValueError("displacement_min_body_to_range must be in (0, 1]")
    swings = confirmed_swings(candles, pivot_left, pivot_right)
    gaps = fair_value_gaps(candles)
    sweeps = liquidity_sweeps(candles, swings)
    results: list[ICT2022SetupCandidate] = []
    for sweep in sweeps:
        if sweep.direction == "buy_side":
            direction, broken_kind = "bearish", "low"
        else:
            direction, broken_kind = "bullish", "high"
        prior_structure = [s for s in swings if s.kind == broken_kind and s.confirmed_at_index < sweep.candle_index]
        if not prior_structure:
            continue
        broken = prior_structure[-1]
        for j in range(sweep.candle_index + 1, len(candles)):
            candle = candles[j]
            breaks = candle.close < broken.price if direction == "bearish" else candle.close > broken.price
            strength = _body_to_range(candle)
            if not breaks or strength < displacement_min_body_to_range:
                continue
            eligible_gaps = [g for g in gaps if g.direction == direction and g.first_candle_index >= sweep.candle_index and g.middle_candle_index <= j <= g.third_candle_index]
            if eligible_gaps:
                gap = eligible_gaps[-1]
                entry = gap.lower if direction == "bearish" else gap.upper
                # The lesson gives two stop-placement variants: beyond candle 1 or candle 2.
                # Preserve both references instead of silently selecting one.
                if direction == "bearish":
                    invalidations = (candles[gap.first_candle_index].high, candles[gap.middle_candle_index].high)
                else:
                    invalidations = (candles[gap.first_candle_index].low, candles[gap.middle_candle_index].low)
                mss = MarketStructureShift(j, broken, direction, strength)
                results.append(ICT2022SetupCandidate(
                    model="ICT_2022_Mentorship_Episode_6", direction=direction,
                    sweep=sweep, mss=mss, fvg=gap, entry_reference=entry,
                    invalidation_reference=invalidation,
                    source_id="ICT-2022-Mentorship-Episode-6-2022-02-04",
                    assumptions=(f"pivot_left={pivot_left}, pivot_right={pivot_right}", f"displacement_min_body_to_range={displacement_min_body_to_range}", "strict unique local pivots are an engineering definition", "entry/invalidation references require a selected execution variant"),
                ))
            # The MSS is the first qualifying displacement break. Continue only
            # until its three-candle FVG is complete; do not accept a later, unrelated gap.
            if j >= sweep.candle_index + 3:
                completed = [g for g in gaps if g.direction == direction and g.first_candle_index >= sweep.candle_index and g.middle_candle_index <= j <= g.third_candle_index]
                if completed:
                    break
    return results
