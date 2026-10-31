from datetime import date
from decimal import Decimal as D
import pytest
from ict_engine.risk_controls import DailyRiskState, RiskLimits

def limits():
    return RiskLimits(D("1000"), D("300"), 2, 3, 2)

def test_entry_allowed_within_all_limits():
    state = DailyRiskState(date(2026,1,1))
    assert state.evaluate_entry(limits(), D("250")).allowed
    state.record_entry(limits(), D("250"))
    assert state.open_positions == 1
    assert state.trades_today == 1

def test_per_trade_risk_limit_blocks_entry():
    state = DailyRiskState(date(2026,1,1))
    decision = state.evaluate_entry(limits(), D("301"))
    assert not decision.allowed
    assert "per_trade_risk_limit_exceeded" in decision.reasons

def test_daily_loss_limit_blocks_new_entry():
    state = DailyRiskState(date(2026,1,1), realized_pnl=D("-1000"))
    decision = state.evaluate_entry(limits(), D("100"))
    assert "daily_loss_limit_reached" in decision.reasons

def test_max_positions_trades_and_consecutive_losses_block():
    state = DailyRiskState(date(2026,1,1), open_positions=2, trades_today=3, consecutive_losses=2)
    reasons = state.evaluate_entry(limits(), D("100")).reasons
    assert set(reasons) == {"max_open_positions_reached", "max_trades_per_day_reached", "max_consecutive_losses_reached"}

def test_closing_trade_updates_daily_pnl_and_loss_streak():
    state = DailyRiskState(date(2026,1,1), open_positions=2)
    state.record_close(D("-100"))
    state.record_close(D("-50"))
    assert state.open_positions == 0
    assert state.realized_pnl == D("-150")
    assert state.consecutive_losses == 2
    state.open_positions = 1
    state.record_close(D("200"))
    assert state.consecutive_losses == 0

def test_daily_rollover_resets_day_limits_but_keeps_open_positions():
    state = DailyRiskState(date(2026,1,1), D("-500"), 1, 2, 1)
    state.rollover(date(2026,1,2))
    assert state.realized_pnl == D("0")
    assert state.trades_today == 0
    assert state.consecutive_losses == 0
    assert state.open_positions == 1

def test_out_of_order_risk_rollover_rejected():
    state = DailyRiskState(date(2026,1,2))
    with pytest.raises(ValueError):
        state.rollover(date(2026,1,1))

def test_cannot_close_without_open_position():
    with pytest.raises(ValueError):
        DailyRiskState(date(2026,1,1)).record_close(D("10"))
def test_negative_risk_state_counters_rejected():
    with pytest.raises(ValueError):
        DailyRiskState(date(2026,1,1), open_positions=-1)
