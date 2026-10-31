import json

from dashboard import app as dashboard_app

def test_dashboard_reports_waiting_without_session_report(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard_app, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(dashboard_app, "DATABASE", tmp_path / "stocks.sqlite")
    payload = dashboard_app.state_payload()
    assert payload["status"] == "NO_REPORT"
    assert payload["stocks"] == []

def test_dashboard_state_exposes_verified_stock_and_signal_health(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    db = tmp_path / "stocks.sqlite"
    monkeypatch.setattr(dashboard_app, "REPORTS", reports)
    monkeypatch.setattr(dashboard_app, "DATABASE", db)
    report = {
        "status": "OK",
        "as_of": "2026-10-30T10:00:00+05:30",
        "scan_date": "2026-10-30",
        "universe_snapshot_id": "universe-1",
        "total_stocks": 50,
        "ready_stocks": 48,
        "stock_status": [{
            "symbol": "RELIANCE", "company_name": "Reliance Industries",
            "status": "READY", "reason": "", "missing_counts": {},
        }],
        "signals": [{
            "signal_id": "signal-1", "symbol": "RELIANCE",
            "model_id": "ICT_2022_Mentorship_Episode_6", "direction": "bullish",
        }],
        "live_stream": {
            "symbols_with_tick": 1, "ticks_received": 4,
            "quotes": {"RELIANCE": {
                "ltp": "1450.00", "exchange_timestamp": "2026-10-30T10:00:00+05:30",
                "received_at": "2026-10-30T10:00:01+05:30",
            }},
            "recent_errors": [],
        },
        "paper_trading": {
            "positions_opened": 1, "positions_closed": 0,
            "open_positions": 1, "realized_pnl_today": "0",
            "actions": [],
        },
    }
    (reports / "stock_scan_2026-10-30_100000.json").write_text(json.dumps(report), encoding="utf-8")
    payload = dashboard_app.state_payload()
    assert payload["status"] == "OK"
    assert payload["overview"]["ready_stocks"] == 48
    assert payload["overview"]["signals"] == 1
    assert payload["stocks"][0]["quote"]["ltp"] == "1450.00"
    assert payload["stocks"][0]["signals_count"] == 1
    assert payload["open_positions"] == []
    assert db.exists()
