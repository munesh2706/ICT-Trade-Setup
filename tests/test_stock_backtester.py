from datetime import date, datetime
from zoneinfo import ZoneInfo

from scripts.backtest_nifty50_ict import _first_scan_time, _split_trades, _summary

IST = ZoneInfo("Asia/Kolkata")


def test_backtest_starts_after_first_completed_15m_context_bar():
    session = type("Session", (), {
        "open_at": datetime(2026, 10, 30, 9, 15, tzinfo=IST),
    })()
    assert _first_scan_time(session) == datetime(2026, 10, 30, 9, 30, tzinfo=IST)


def test_backtest_first_scan_time_respects_session_timezone():
    session = type("Session", (), {
        "open_at": datetime(2026, 10, 30, 3, 45, tzinfo=ZoneInfo("UTC")),
    })()
    assert _first_scan_time(session) == datetime(2026, 10, 30, 9, 30, tzinfo=IST)


def test_backtest_metrics_are_net_of_fees_and_slippage():
    rows = [
        {"exit_time":"2026-10-30T10:30:00+05:30","gross_pnl":"100","fees":"10","slippage_cost":"5","r_multiple":"2","duration_minutes":30},
        {"exit_time":"2026-10-30T11:00:00+05:30","gross_pnl":"-50","fees":"10","slippage_cost":"5","r_multiple":"-1","duration_minutes":20},
    ]
    result = _summary(rows)
    assert result["trade_count"] == 2
    assert result["net_pnl"] == "20"
    assert result["wins"] == 1
    assert result["losses"] == 1
    assert result["profit_factor"] == "1.307692307692307692307692308"


def test_backtest_out_of_sample_split_excludes_boundary_crossing_trades():
    rows = [
        {"entry_time":"2026-10-29T10:00:00+05:30","exit_time":"2026-10-29T11:00:00+05:30"},
        {"entry_time":"2026-10-29T14:00:00+05:30","exit_time":"2026-10-30T09:30:00+05:30"},
        {"entry_time":"2026-10-30T10:00:00+05:30","exit_time":"2026-10-30T11:00:00+05:30"},
    ]
    in_sample, out_of_sample, boundary = _split_trades(rows, date(2026, 10, 30))
    assert len(in_sample) == 1
    assert len(out_of_sample) == 1
    assert len(boundary) == 1


def test_out_of_sample_metrics_use_split_trades_and_exclude_boundary_trade():
    rows = [
        {"entry_time":"2026-10-29T10:00:00+05:30","exit_time":"2026-10-29T11:00:00+05:30",
         "gross_pnl":"100","fees":"10","slippage_cost":"5","r_multiple":"2","duration_minutes":60},
        {"entry_time":"2026-10-29T14:00:00+05:30","exit_time":"2026-10-30T09:30:00+05:30",
         "gross_pnl":"500","fees":"0","slippage_cost":"0","r_multiple":"10","duration_minutes":60},
        {"entry_time":"2026-10-30T10:00:00+05:30","exit_time":"2026-10-30T11:00:00+05:30",
         "gross_pnl":"-50","fees":"10","slippage_cost":"5","r_multiple":"-1","duration_minutes":60},
    ]
    in_sample, out_of_sample, boundary = _split_trades(rows, date(2026, 10, 30))
    assert _summary(in_sample)["net_pnl"] == "85"
    assert _summary(out_of_sample)["net_pnl"] == "-65"
    assert len(boundary) == 1
