from decimal import Decimal as D
import pytest
from ict_engine.performance import TradeResult, summarize_trades

def test_performance_metrics_are_net_of_fees_and_slippage():
    trades = [TradeResult(D("120"), D("10"), D("5"), D("2"), 30), TradeResult(D("-60"), D("10"), D("5"), D("-1"), 15), TradeResult(D("40"), D("5"), D("0"), D("1"), 10)]
    s = summarize_trades(trades)
    assert s.trade_count == 3
    assert s.wins == 2
    assert s.losses == 1
    assert s.net_pnl == D("65")
    assert s.total_fees == D("25")
    assert s.total_slippage == D("10")
    assert s.expectancy == D("65") / D("3")
    assert s.profit_factor == D("140") / D("75")
    assert s.max_drawdown == D("75")
    assert s.max_consecutive_losses == 1

def test_empty_trade_set_returns_empty_metrics_without_division_error():
    s = summarize_trades([])
    assert s.trade_count == 0
    assert s.win_rate is None
    assert s.expectancy is None
    assert s.net_pnl == D("0")

def test_all_winning_trades_has_undefined_profit_factor():
    s = summarize_trades([TradeResult(D("10"), D("0"), D("0"))])
    assert s.wins == 1
    assert s.profit_factor is None

def test_negative_fees_rejected():
    with pytest.raises(ValueError):
        TradeResult(D("10"), D("-1"), D("0"))

def test_consecutive_loss_streak_resets_after_win():
    s = summarize_trades([TradeResult(D("-10"), D("0"), D("0")), TradeResult(D("-5"), D("0"), D("0")), TradeResult(D("20"), D("0"), D("0")), TradeResult(D("-2"), D("0"), D("0"))])
    assert s.max_consecutive_losses == 2