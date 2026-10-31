from datetime import date

from scripts.backtest_nifty50_ict import _by_entry_date, _summary

def test_backtest_metrics_are_net_of_fees_and_slippage():
    rows = [
        {"gross_pnl":"100","fees":"10","slippage_cost":"5","r_multiple":"2","duration_minutes":30},
        {"gross_pnl":"-50","fees":"10","slippage_cost":"5","r_multiple":"-1","duration_minutes":20},
    ]
    result = _summary(rows)
    assert result["trade_count"] == 2
    assert result["net_pnl"] == "20"
    assert result["wins"] == 1
    assert result["losses"] == 1
    assert result["profit_factor"] == "1.307692307692307692307692308"

def test_backtest_out_of_sample_split_uses_trade_entry_date():
    rows = [
        {"entry_time":"2026-10-29T10:00:00+05:30"},
        {"entry_time":"2026-10-30T10:00:00+05:30"},
    ]
    assert len(_by_entry_date(rows,date(2026,10,30),True)) == 1
    assert len(_by_entry_date(rows,date(2026,10,30),False)) == 1
