import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from dashboard import app as dashboard_app
from ict_engine.paper_store import StockPaperStore
from ict_engine.trade_simulator import PaperPosition


def test_dashboard_marks_old_reports_stale_and_does_not_value_positions_from_stale_quotes(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    db = tmp_path / "stocks.sqlite"
    monkeypatch.setattr(dashboard_app, "REPORTS", reports)
    monkeypatch.setattr(dashboard_app, "DATABASE", db)
    monkeypatch.setenv("ICT_REPORT_STALE_SECONDS", "30")

    now = datetime.now(timezone.utc)
    old = (now - timedelta(minutes=10)).isoformat()
    report = {
        "as_of": old, "scan_date": now.date().isoformat(),
        "total_stocks": 50, "ready_stocks": 50, "stock_status": [],
        "signals": [], "live_stream": {"quotes": {"RELIANCE": {
            "ltp": "1500", "stale": True, "received_at": now.isoformat()
        }}},
        "paper_trading": {},
    }
    (reports / "stock_scan_stale.json").write_text(json.dumps(report), encoding="utf-8")
    journal = StockPaperStore(db)
    signal = SimpleNamespace(
        signal_id="s1", symbol="RELIANCE", model_id="m", direction="long",
        available_at=now, source_id="src", status="ENTRY_ARMED",
    )
    journal.register_signal(signal, evidence={}, observed_at=now)
    position = PaperPosition(
        "p1", "RELIANCE", "m", "long", now, Decimal("1400"),
        Decimal("1350"), Decimal("1600"), Decimal("1"),
        Decimal("1"), Decimal("0"), Decimal("0"),
    )
    journal.open_position(position, "s1")

    payload = dashboard_app.state_payload()
    assert payload["status"] == "STALE"
    assert payload["report_stale"] is True
    assert payload["open_positions"][0]["ltp"] == "1500"
    assert payload["open_positions"][0]["quote_stale"] is True
    assert payload["open_positions"][0]["unrealized_gross_pnl"] is None
