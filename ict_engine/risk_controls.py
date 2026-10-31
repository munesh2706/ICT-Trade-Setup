"""Configurable daily portfolio risk guards for paper-trade entries."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

ZERO = Decimal("0")

@dataclass(frozen=True, slots=True)
class RiskLimits:
    max_daily_loss: Decimal
    max_risk_per_trade: Decimal
    max_open_positions: int
    max_trades_per_day: int
    max_consecutive_losses: int
    def __post_init__(self):
        if self.max_daily_loss <= ZERO or self.max_risk_per_trade <= ZERO:
            raise ValueError("daily loss and per-trade risk limits must be positive")
        if min(self.max_open_positions, self.max_trades_per_day, self.max_consecutive_losses) < 1:
            raise ValueError("count-based risk limits must be at least one")

@dataclass(frozen=True, slots=True)
class RiskDecision:
    allowed: bool
    reasons: tuple[str, ...]

@dataclass(slots=True)
class DailyRiskState:
    risk_date: date
    realized_pnl: Decimal = ZERO
    open_positions: int = 0
    trades_today: int = 0
    consecutive_losses: int = 0

    def __post_init__(self):
        if self.open_positions < 0 or self.trades_today < 0 or self.consecutive_losses < 0:
            raise ValueError("risk state counters cannot be negative")

    def evaluate_entry(self, limits: RiskLimits, proposed_risk: Decimal) -> RiskDecision:
        reasons = []
        if self.realized_pnl <= -limits.max_daily_loss:
            reasons.append("daily_loss_limit_reached")
        if self.open_positions >= limits.max_open_positions:
            reasons.append("max_open_positions_reached")
        if self.trades_today >= limits.max_trades_per_day:
            reasons.append("max_trades_per_day_reached")
        if self.consecutive_losses >= limits.max_consecutive_losses:
            reasons.append("max_consecutive_losses_reached")
        if proposed_risk <= ZERO:
            reasons.append("proposed_risk_not_positive")
        elif proposed_risk > limits.max_risk_per_trade:
            reasons.append("per_trade_risk_limit_exceeded")
        return RiskDecision(not reasons, tuple(reasons))

    def record_entry(self, limits: RiskLimits, proposed_risk: Decimal) -> None:
        decision = self.evaluate_entry(limits, proposed_risk)
        if not decision.allowed:
            raise ValueError("entry blocked: " + ",".join(decision.reasons))
        self.open_positions += 1
        self.trades_today += 1

    def record_close(self, net_pnl: Decimal) -> None:
        if self.open_positions < 1:
            raise ValueError("cannot close a position when none is open")
        self.open_positions -= 1
        self.realized_pnl += net_pnl
        if net_pnl < ZERO:
            self.consecutive_losses += 1
        elif net_pnl > ZERO:
            self.consecutive_losses = 0

    def rollover(self, new_risk_date: date) -> None:
        if new_risk_date <= self.risk_date:
            raise ValueError("risk date must advance")
        self.risk_date = new_risk_date
        self.realized_pnl = ZERO
        self.trades_today = 0
        self.consecutive_losses = 0
        # Open positions carry across the date boundary and remain counted.