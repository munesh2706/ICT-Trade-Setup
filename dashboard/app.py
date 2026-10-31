"""Local-only FastAPI dashboard for the NIFTY 50 stock ICT platform."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse

from ict_engine.paper_store import StockPaperStore
from ict_engine.stock_storage import StockCandleStore

ROOT = Path(__file__).resolve().parents[1]
DATABASE = Path(os.getenv("ICT_DATABASE_PATH", ROOT / "data" / "nifty50_stocks.sqlite"))
REPORTS = Path(os.getenv("ICT_REPORTS_DIR", ROOT / "data" / "reports"))
INDEX_HTML = Path(__file__).with_name("index.html")
ALLOWED_TIMEFRAMES = {"1m", "3m", "5m", "10m", "15m", "30m", "1h", "1d"}
SYMBOL_RE = re.compile(r"^[A-Z0-9&._-]{1,30}$")

app = FastAPI(title="NIFTY 50 Stock ICT Dashboard", docs_url=None, redoc_url=None)

def latest_report() -> dict | None:
    if not REPORTS.exists():
        return None
    files = sorted(REPORTS.glob("stock_scan_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
    return None

def paper_store() -> StockPaperStore:
    return StockPaperStore(DATABASE)

def candle_store() -> StockCandleStore:
    return StockCandleStore(DATABASE)

def state_payload() -> dict:
    report = latest_report()
    if report is None:
        return {"status": "NO_REPORT", "message": "No session report exists yet. Start the NIFTY 50 session runner.",
                "as_of": None, "stocks": [], "signals": [], "open_positions": [], "closed_trades": []}
    now_utc = datetime.now(timezone.utc)
    report_age_seconds = None
    try:
        report_time = datetime.fromisoformat(str(report.get("as_of", "")).replace("Z", "+00:00"))
        if report_time.tzinfo is not None:
            report_age_seconds = max(0, int((now_utc - report_time.astimezone(timezone.utc)).total_seconds()))
    except (TypeError, ValueError):
        pass
    stale_after = max(1, int(os.getenv("ICT_REPORT_STALE_SECONDS", "120")))
    report_stale = report_age_seconds is None or report_age_seconds > stale_after
    paper = report.get("paper_trading") or {}
    live = report.get("live_stream") or {}
    quotes = live.get("quotes") or {}
    signals_by_symbol: dict[str, list] = {}
    for signal in report.get("signals") or []:
        signals_by_symbol.setdefault(signal.get("symbol", ""), []).append(signal)
    stocks = []
    for row in report.get("stock_status") or []:
        symbol = row.get("symbol", "")
        quote = quotes.get(symbol)
        tick_age = None
        if quote and (quote.get("exchange_timestamp") or quote.get("received_at")):
            try:
                quote_time = datetime.fromisoformat(quote.get("exchange_timestamp") or quote["received_at"])
                tick_age = max(0, int((datetime.now(timezone.utc) - quote_time.astimezone(timezone.utc)).total_seconds()))
            except ValueError:
                pass
        quote_stale = bool(quote.get("stale", True)) if quote else True
        stocks.append({**row, "quote": quote, "tick_age_seconds": tick_age,
                       "quote_stale": quote_stale,
                       "quote_source": quote.get("source") if quote else None,
                       "signals_count": len(signals_by_symbol.get(symbol, []))})
    journal = paper_store()
    open_positions = []
    for position in journal.load_open_positions():
        position_quote = quotes.get(position.instrument_id)
        position_quote_fresh = bool(position_quote) and not bool(position_quote.get("stale", True))
        open_positions.append({
            "position_id": position.position_id,
            "signal_id": journal.position_signal_id(position.position_id),
            "symbol": position.instrument_id, "model_id": position.model_id,
            "direction": position.direction, "entry_time": position.entry_time.isoformat(),
            "entry_price": str(position.entry_price), "stop": str(position.stop),
            "target": str(position.target), "quantity": str(position.quantity),
            "ltp": position_quote.get("ltp") if position_quote else None,
            "quote_received_at": position_quote.get("received_at") if position_quote else None,
            "quote_stale": not position_quote_fresh,
            "unrealized_gross_pnl": (
                str((Decimal(position_quote["ltp"]) - position.entry_price) * position.quantity
                    if position.direction == "long" else
                    (position.entry_price - Decimal(position_quote["ltp"])) * position.quantity)
                if position_quote_fresh and position_quote.get("ltp") is not None else None
            ),
        })
    closed_trades = journal.closed_trade_rows()
    closed_today = [row for row in closed_trades
                    if str(row.get("exit_time", ""))[:10] == str(report.get("scan_date", ""))]
    return {
        "status": "STALE" if report_stale else "OK", "as_of": report.get("as_of"),
        "report_age_seconds": report_age_seconds, "report_stale": report_stale,
        "scan_date": report.get("scan_date"),
        "universe_snapshot_id": report.get("universe_snapshot_id"),
        "overview": {
            "total_stocks": report.get("total_stocks", 50), "ready_stocks": report.get("ready_stocks", 0),
            "signals": len(report.get("signals") or []), "live_ticks": live.get("symbols_with_tick", 0),
            "ticks_received": live.get("ticks_received", 0), "open_positions": len(open_positions),
            "paper_trades_opened": paper.get("positions_opened", 0),
            "paper_trades_closed": len(closed_today),
            "paper_realized_pnl": paper.get("realized_pnl_today", "0"),
            "stream_errors": live.get("recent_errors", []), "quote_api": live.get("quote_api", {}),
        },
        "stocks": stocks, "signals": report.get("signals") or [],
        "open_positions": open_positions, "closed_trades": closed_trades[-200:],
        "paper_actions": paper.get("actions", []),
    }

@app.get("/", response_class=HTMLResponse)
def home():
    if not INDEX_HTML.is_file():
        raise HTTPException(500, "Dashboard HTML is missing")
    return HTMLResponse(INDEX_HTML.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})

@app.get("/api/state")
def api_state():
    return JSONResponse(state_payload(), headers={"Cache-Control": "no-store"})

@app.get("/api/signals/{signal_id}")
def api_signal(signal_id: str):
    report = latest_report()
    if report is None:
        raise HTTPException(404, "No session report exists")
    signal = next((x for x in report.get("signals", []) if x.get("signal_id") == signal_id), None)
    if signal is None:
        raise HTTPException(404, "Signal is not in the latest scan report")
    journal = paper_store()
    try:
        status, events = journal.signal_status(signal_id).value, journal.signal_events(signal_id)
    except ValueError:
        status, events = "not_persisted", []
    return {"signal": signal, "paper_status": status, "events": events}

@app.get("/api/candles/{symbol}")
def api_candles(symbol: str, timeframe: str = Query("5m"),
                limit: int = Query(150, ge=20, le=500)):
    symbol = symbol.upper()
    if not SYMBOL_RE.fullmatch(symbol):
        raise HTTPException(400, "Invalid stock symbol")
    if timeframe not in ALLOWED_TIMEFRAMES:
        raise HTTPException(400, "Unsupported timeframe")
    candles = candle_store().load_verified_candles(symbol, timeframe, limit=limit)
    return {"symbol": symbol, "timeframe": timeframe, "count": len(candles), "candles": [{
        "timestamp": c.timestamp.isoformat(), "open": str(c.open), "high": str(c.high),
        "low": str(c.low), "close": str(c.close), "volume": str(c.volume),
    } for c in candles]}

@app.get("/api/paper/closed")
def api_closed_trades(limit: int = Query(100, ge=1, le=1000)):
    return {"trades": paper_store().closed_trade_rows()[-limit:]}

@app.get("/api/health")
def api_health():
    report = latest_report()
    report_age_seconds = None
    if report:
        try:
            report_time = datetime.fromisoformat(str(report.get("as_of", "")).replace("Z", "+00:00"))
            if report_time.tzinfo is not None:
                report_age_seconds = max(0, int((datetime.now(timezone.utc) - report_time.astimezone(timezone.utc)).total_seconds()))
        except (TypeError, ValueError):
            pass
    stale_after = max(1, int(os.getenv("ICT_REPORT_STALE_SECONDS", "120")))
    report_stale = report_age_seconds is None or report_age_seconds > stale_after if report else False
    return {"status": "WAITING" if not report else ("STALE" if report_stale else "OK"),
            "database_exists": DATABASE.exists(), "reports_directory_exists": REPORTS.exists(),
            "latest_report_as_of": report.get("as_of") if report else None,
            "report_age_seconds": report_age_seconds, "report_stale": report_stale,
            "stale_after_seconds": stale_after, "generated_at": datetime.now(timezone.utc).isoformat()}
