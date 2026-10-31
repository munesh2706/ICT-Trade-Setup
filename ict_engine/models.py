"""Typed domain objects used by the ICT detection engine."""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

@dataclass(frozen=True, slots=True)
class Candle:
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ValueError("Candle timestamp must be timezone-aware")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("Candle high is inconsistent with OHLC")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("Candle low is inconsistent with OHLC")
        if self.volume < 0:
            raise ValueError("Candle volume cannot be negative")

@dataclass(frozen=True, slots=True)
class SwingPoint:
    pivot_index: int
    confirmed_at_index: int
    price: Decimal
    kind: str

@dataclass(frozen=True, slots=True)
class FairValueGap:
    first_candle_index: int
    middle_candle_index: int
    third_candle_index: int
    lower: Decimal
    upper: Decimal
    direction: str

@dataclass(frozen=True, slots=True)
class LiquiditySweep:
    candle_index: int
    reference_swing: SwingPoint
    extreme: Decimal
    direction: str

@dataclass(frozen=True, slots=True)
class MarketStructureShift:
    candle_index: int
    broken_swing: SwingPoint
    direction: str
    body_to_range: Decimal

@dataclass(frozen=True, slots=True)
class ICT2022SetupCandidate:
    model: str
    direction: str
    sweep: LiquiditySweep
    mss: MarketStructureShift
    fvg: FairValueGap
    entry_reference: Decimal
    invalidation_references: tuple[Decimal, Decimal]
    source_id: str
    assumptions: tuple[str, ...]
