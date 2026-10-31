"""Broker-free filled-position manager using completed OHLC bars."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from .models import Candle
from .paper_execution import resolve_barrier_exit
from .performance import TradeResult

ZERO = Decimal("0")

@dataclass(frozen=True, slots=True)
class PaperPosition:
    position_id: str
    instrument_id: str
    model_id: str
    direction: str
    entry_time: datetime
    entry_price: Decimal
    stop: Decimal
    target: Decimal
    quantity: Decimal
    point_value: Decimal
    round_trip_fees_per_unit: Decimal
    round_trip_slippage_points: Decimal
    def __post_init__(self):
        if self.direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        if self.entry_time.tzinfo is None:
            raise ValueError("entry_time must be timezone-aware")
        if self.quantity <= ZERO or self.point_value <= ZERO:
            raise ValueError("quantity and point_value must be positive")
        if self.round_trip_fees_per_unit < ZERO or self.round_trip_slippage_points < ZERO:
            raise ValueError("fees and slippage cannot be negative")
        if self.direction == "long" and not self.stop < self.entry_price < self.target:
            raise ValueError("long position requires stop < entry < target")
        if self.direction == "short" and not self.target < self.entry_price < self.stop:
            raise ValueError("short position requires target < entry < stop")

@dataclass(frozen=True, slots=True)
class PaperExit:
    position_id: str
    exit_time: datetime
    reason: str
    exit_price: Decimal
    gross_pnl: Decimal
    fees: Decimal
    slippage_cost: Decimal
    net_pnl: Decimal
    ambiguous_bar: bool
    gap_through_stop: bool
    def as_trade_result(self) -> TradeResult:
        return TradeResult(self.gross_pnl, self.fees, self.slippage_cost)

def process_position_bar(position: PaperPosition, candle: Candle, *, bar_duration: timedelta) -> PaperExit | None:
    """Return an exit only for bars strictly after the entry bar.

    The entry bar is skipped because OHLC cannot establish whether a limit
    entry occurred before or after a stop/target touch within that same bar.
    This conservative policy avoids inventing intrabar chronology.
    """
    if bar_duration <= timedelta(0):
        raise ValueError("bar_duration must be positive")
    if candle.timestamp <= position.entry_time:
        return None
    direction = position.direction
    barrier = resolve_barrier_exit(candle, direction=direction, stop=position.stop, target=position.target)
    if barrier.reason == "none":
        return None
    points = barrier.price - position.entry_price if direction == "long" else position.entry_price - barrier.price
    gross = points * position.quantity * position.point_value
    fees = position.round_trip_fees_per_unit * position.quantity
    slippage = position.round_trip_slippage_points * position.quantity * position.point_value
    return PaperExit(position.position_id, candle.timestamp + bar_duration, barrier.reason, barrier.price, gross, fees, slippage, gross - fees - slippage, barrier.ambiguous_bar, barrier.gap_through_stop)