"""Deterministic net-of-cost performance statistics for closed paper trades."""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

ZERO = Decimal("0")

@dataclass(frozen=True, slots=True)
class TradeResult:
    gross_pnl: Decimal
    fees: Decimal
    slippage_cost: Decimal
    r_multiple: Decimal | None = None
    duration_minutes: int | None = None
    def __post_init__(self):
        if self.fees < ZERO or self.slippage_cost < ZERO:
            raise ValueError("fees and slippage cost cannot be negative")
        if self.duration_minutes is not None and self.duration_minutes < 0:
            raise ValueError("duration_minutes cannot be negative")
    @property
    def net_pnl(self) -> Decimal:
        return self.gross_pnl - self.fees - self.slippage_cost

@dataclass(frozen=True, slots=True)
class PerformanceSummary:
    trade_count: int
    wins: int
    losses: int
    breakeven: int
    win_rate: Decimal | None
    gross_pnl: Decimal
    total_fees: Decimal
    total_slippage: Decimal
    net_pnl: Decimal
    expectancy: Decimal | None
    profit_factor: Decimal | None
    average_win: Decimal | None
    average_loss: Decimal | None
    max_drawdown: Decimal
    average_r_multiple: Decimal | None
    average_duration_minutes: Decimal | None
    max_consecutive_losses: int

def summarize_trades(trades: Sequence[TradeResult]) -> PerformanceSummary:
    net = [t.net_pnl for t in trades]
    count = len(trades)
    wins = [x for x in net if x > ZERO]
    losses = [x for x in net if x < ZERO]
    breakeven = count - len(wins) - len(losses)
    gross_profit = sum(wins, ZERO)
    gross_loss = abs(sum(losses, ZERO))
    equity = ZERO
    peak = ZERO
    max_drawdown = ZERO
    streak = 0
    max_streak = 0
    for value in net:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
        if value < ZERO:
            streak += 1
            max_streak = max(max_streak, streak)
        elif value > ZERO:
            streak = 0
    r_values = [t.r_multiple for t in trades if t.r_multiple is not None]
    durations = [Decimal(t.duration_minutes) for t in trades if t.duration_minutes is not None]
    return PerformanceSummary(
        trade_count=count, wins=len(wins), losses=len(losses), breakeven=breakeven,
        win_rate=(Decimal(len(wins)) / Decimal(count) if count else None),
        gross_pnl=sum((t.gross_pnl for t in trades), ZERO),
        total_fees=sum((t.fees for t in trades), ZERO),
        total_slippage=sum((t.slippage_cost for t in trades), ZERO),
        net_pnl=sum(net, ZERO),
        expectancy=(sum(net, ZERO) / Decimal(count) if count else None),
        profit_factor=(gross_profit / gross_loss if gross_loss else (None if not gross_profit else None)),
        average_win=(gross_profit / Decimal(len(wins)) if wins else None),
        average_loss=(sum(losses, ZERO) / Decimal(len(losses)) if losses else None),
        max_drawdown=max_drawdown,
        average_r_multiple=(sum(r_values, ZERO) / Decimal(len(r_values)) if r_values else None),
        average_duration_minutes=(sum(durations, ZERO) / Decimal(len(durations)) if durations else None),
        max_consecutive_losses=max_streak,
    )