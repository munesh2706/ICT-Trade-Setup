"""Broker-free risk sizing and conservative paper-fill primitives.

All monetary inputs are explicit. No broker API is imported or called.
The module operates on generic units; index point value, quantity step,
fees and slippage must be supplied by the caller.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR

from .models import Candle

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class RiskSizing:
    quantity: Decimal
    planned_risk: Decimal
    risk_per_unit: Decimal


@dataclass(frozen=True, slots=True)
class ExitDecision:
    reason: str  # stop_loss or take_profit or none
    price: Decimal | None
    ambiguous_bar: bool
    gap_through_stop: bool


def calculate_position_size(
    *,
    risk_budget: Decimal,
    entry: Decimal,
    stop: Decimal,
    point_value: Decimal,
    quantity_step: Decimal,
    round_trip_fees_per_unit: Decimal = ZERO,
    round_trip_slippage_points: Decimal = ZERO,
) -> RiskSizing:
    """Size a paper position so planned stop loss plus modeled costs fit budget."""
    if risk_budget <= ZERO or point_value <= ZERO or quantity_step <= ZERO:
        raise ValueError("risk_budget, point_value and quantity_step must be positive")
    if round_trip_fees_per_unit < ZERO or round_trip_slippage_points < ZERO:
        raise ValueError("fees and slippage cannot be negative")
    distance = abs(entry - stop)
    if distance == ZERO:
        raise ValueError("entry and stop cannot be equal")
    risk_per_unit = (
        distance * point_value
        + round_trip_fees_per_unit
        + round_trip_slippage_points * point_value
    )
    raw_quantity = risk_budget / risk_per_unit
    quantity = (raw_quantity / quantity_step).to_integral_value(rounding=ROUND_FLOOR) * quantity_step
    if quantity <= ZERO:
        raise ValueError("risk budget is too small for one quantity step")
    return RiskSizing(quantity, quantity * risk_per_unit, risk_per_unit)


def resolve_barrier_exit(
    candle: Candle,
    *,
    direction: str,
    stop: Decimal,
    target: Decimal,
) -> ExitDecision:
    """Resolve a single OHLC bar with conservative stop-first ambiguity handling.

    If both barriers are touched in one bar, chronology is unknowable from OHLC;
    stop is assumed first. A gap through a stop is filled at the worse opening
    price, not at the requested stop. Targets are limit-like and receive the
    target price unless the bar opens beyond it in the favourable direction.
    """
    if direction not in {"long", "short"}:
        raise ValueError("direction must be long or short")
    if direction == "long" and stop >= target:
        raise ValueError("long trade requires stop below target")
    if direction == "short" and stop <= target:
        raise ValueError("short trade requires stop above target")
    if direction == "long":
        stop_hit = candle.low <= stop
        target_hit = candle.high >= target
        gap_stop = candle.open <= stop
        if stop_hit:
            return ExitDecision("stop_loss", min(candle.open, stop) if gap_stop else stop, stop_hit and target_hit, gap_stop)
        if target_hit:
            return ExitDecision("take_profit", max(candle.open, target) if candle.open >= target else target, False, False)
    else:
        stop_hit = candle.high >= stop
        target_hit = candle.low <= target
        gap_stop = candle.open >= stop
        if stop_hit:
            return ExitDecision("stop_loss", max(candle.open, stop) if gap_stop else stop, stop_hit and target_hit, gap_stop)
        if target_hit:
            return ExitDecision("take_profit", min(candle.open, target) if candle.open <= target else target, False, False)
    return ExitDecision("none", None, False, False)
