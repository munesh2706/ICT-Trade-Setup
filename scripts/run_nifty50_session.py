"""Single-process NIFTY 50 stock session runner.

Authenticates once, performs pre-session historical reconciliation, starts one
Angel One WebSocket V2 quote stream, incrementally refreshes completed candles
from Angel One Historical API, and runs the stock ICT scanner. No order APIs.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.reconcile_nifty50_history import load_calendar
from ict_engine.stock_feed import AngelOneStockFeed
from ict_engine.stock_live_refresh import refresh_current_session
from ict_engine.stock_reconciliation import reconcile_universe
from ict_engine.stock_scanner import StockICTScanConfig, StockICTScanner
from ict_engine.paper_store import StockPaperStore
from ict_engine.paper_trading import StockPaperTradingEngine, load_paper_trading_config
from ict_engine.stock_storage import StockCandleStore
from ict_engine.stock_universe import download_nse_universe, save_universe_snapshot

IST = ZoneInfo("Asia/Kolkata")

def encode(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "isoformat") and not isinstance(value, str):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return encode(asdict(value))
    if isinstance(value, dict):
        return {str(k): encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [encode(v) for v in value]
    return value

def write_report(report, directory: Path, *, tick_count: int, stream_errors: list[str], latest_ticks=None, paper_report=None):
    directory.mkdir(parents=True, exist_ok=True)
    payload = encode(report)
    quotes = latest_ticks or {}
    payload["live_stream"] = {
        "ticks_received": tick_count,
        "symbols_with_tick": len(quotes),
        "quotes": {
            symbol: {
                "ltp": str(tick.ltp),
                "exchange_timestamp": tick.exchange_timestamp.isoformat(),
                "received_at": tick.received_at.isoformat(),
            } for symbol, tick in quotes.items()
        },
        "recent_errors": stream_errors[-10:],
        "source": "Angel One SmartAPI WebSocket V2",
    }
    if paper_report is not None:
        payload["paper_trading"] = encode(paper_report)
    name = f"stock_scan_{report.scan_date.isoformat()}_{report.as_of.strftime('%H%M%S')}.json"
    path = directory / name
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path

def main() -> int:
    parser = argparse.ArgumentParser(description="Run the NIFTY 50 stock ICT session pipeline")
    parser.add_argument("--calendar", type=Path, required=True)
    parser.add_argument("--history-start", type=lambda x: datetime.strptime(x, "%Y-%m-%d").date(),
                        default=datetime.strptime(os.environ["ICT_HISTORY_START_DATE"], "%Y-%m-%d").date()
                        if os.getenv("ICT_HISTORY_START_DATE") else None)
    parser.add_argument("--database", type=Path, default=ROOT / "data" / "nifty50_stocks.sqlite")
    parser.add_argument("--universe-dir", type=Path, default=ROOT / "data" / "universe")
    parser.add_argument("--reports-dir", type=Path, default=ROOT / "data" / "reports")
    parser.add_argument("--paper-config", type=Path, default=ROOT / "config" / "paper_trading.json")
    parser.add_argument("--history-timeframes", nargs="+", default=["1m", "5m", "15m"],
                        choices=["1m", "3m", "5m", "10m", "15m", "30m", "1h"])
    parser.add_argument("--pace-seconds", type=float, default=0.4)
    parser.add_argument("--once", action="store_true", help="Run one refresh/scan cycle instead of the full session")
    parser.add_argument("--disable-silver-bullet", action="store_true")
    args = parser.parse_args()
    if args.history_start is None:
        parser.error("provide --history-start or set ICT_HISTORY_START_DATE")

    try:
        now = datetime.now(IST)
        calendar = load_calendar(args.calendar)
        if now.date() > calendar.coverage_end:
            raise ValueError("NSE calendar does not cover today; update it from official circulars")
        session = calendar.session_for(now.date())
        if session is None:
            raise ValueError("today is not an explicitly configured NSE trading session")
        if args.history_start < calendar.coverage_start:
            raise ValueError("history start is outside NSE calendar coverage")

        universe = download_nse_universe()
        universe_path = save_universe_snapshot(universe, args.universe_dir)
        feed = AngelOneStockFeed.connect_from_env(universe, pace_seconds=args.pace_seconds)
        paper_config = load_paper_trading_config(args.paper_config)
        paper_engine = StockPaperTradingEngine(paper_config, feed.instruments)
        args.database.parent.mkdir(parents=True, exist_ok=True)
        store = StockCandleStore(args.database)
        paper_journal = StockPaperStore(args.database)

        completed_sessions = [
            x for x in calendar.sessions_between(args.history_start, now.date())
            if x.close_at.astimezone(IST) < now
        ]
        if not completed_sessions:
            raise ValueError("no completed session exists in the configured historical warm-up range")
        historical_dates = [x.trading_date for x in completed_sessions]
        historical = reconcile_universe(
            universe=universe, feed=feed, store=store, calendar=calendar,
            trading_dates=historical_dates, timeframes=args.history_timeframes,
            max_passes=2,
        )
        print(json.dumps({
            "phase": "PRE_SESSION_RECONCILIATION",
            "verified": historical.verified,
            "total_missing": historical.total_missing,
            "universe_snapshot": str(universe_path),
            "instrument_master_sha256": feed.master_sha256,
        }, indent=2))
        if not historical.verified:
            print("DATA GATE CLOSED: scanner and paper engine will not start.")
            return 2

        now = datetime.now(IST)
        latest_ticks = {}
        stream_errors: list[str] = []
        lock = threading.Lock()
        tick_count = 0

        def on_tick(tick):
            nonlocal tick_count
            with lock:
                latest_ticks[tick.symbol] = tick
                tick_count += 1

        def on_error(error):
            with lock:
                stream_errors.append(str(error))

        def on_open():
            print("Angel One WebSocket V2 connected; 50 NSE EQ subscriptions requested.")

        def on_close():
            print("Angel One WebSocket V2 connection closed.")

        feed.start_stream(on_tick, on_error=on_error, on_open=on_open, on_close=on_close, mode=2)
        scanner = StockICTScanner(StockICTScanConfig(enable_silver_bullet=not args.disable_silver_bullet))

        if not args.once and now < session.open_at.astimezone(IST):
            wait_seconds = (session.open_at.astimezone(IST) - now).total_seconds()
            print(f"Waiting {int(wait_seconds)} seconds for NSE session open.")
            time.sleep(max(0, wait_seconds))

        while True:
            as_of = datetime.now(IST)
            if as_of >= session.close_at.astimezone(IST):
                break
            elapsed = int((as_of - session.open_at.astimezone(IST)).total_seconds() // 60)
            timeframes = ["1m"]
            if elapsed > 0 and elapsed % 5 == 0:
                timeframes.append("5m")
            if elapsed > 0 and elapsed % 15 == 0:
                timeframes.append("15m")
            refresh = refresh_current_session(
                universe=universe, feed=feed, store=store, calendar=calendar,
                as_of=as_of, timeframes=timeframes,
            )
            scan = scanner.scan_universe(
                universe=universe, store=store, calendar=calendar,
                scan_date=as_of.date(), as_of=as_of,
            )
            paper = paper_engine.process_scan_report(scan, candles=store, journal=paper_journal)
            with lock:
                count = tick_count
                errors = list(stream_errors)
                quotes = dict(latest_ticks)
            report_path = write_report(scan, args.reports_dir, tick_count=count, stream_errors=errors, latest_ticks=quotes, paper_report=paper)
            print(json.dumps({
                "as_of": as_of.isoformat(),
                "refreshed_series_ready": refresh.ready_series,
                "refreshed_series_total": refresh.total_series,
                "stocks_ready": scan.ready_stocks,
                "signals": len(scan.signals),
                "paper_positions_open": paper.open_positions,
                "paper_positions_opened": paper.positions_opened,
                "paper_positions_closed": paper.positions_closed,
                "ticks_received": count,
                "report": str(report_path),
            }))
            if args.once:
                feed.stop_stream()
                return 0 if scan.ready_stocks == 50 else 2
            next_minute = as_of.replace(second=0, microsecond=0) + timedelta(minutes=1)
            time.sleep(max(0.0, (next_minute - datetime.now(IST)).total_seconds()))

        # Bounded post-close reconciliation for final completed session bars.
        final_as_of = session.close_at.astimezone(IST)
        final_refresh = None
        for attempt in range(3):
            final_refresh = refresh_current_session(
                universe=universe, feed=feed, store=store, calendar=calendar,
                as_of=final_as_of, timeframes=args.history_timeframes,
            )
            if final_refresh.ready_series == final_refresh.total_series:
                break
            if attempt < 2:
                time.sleep(5)
        final_scan = scanner.scan_universe(
            universe=universe, store=store, calendar=calendar,
            scan_date=final_as_of.date(), as_of=final_as_of,
        )
        final_paper = paper_engine.process_scan_report(final_scan, candles=store, journal=paper_journal)
        with lock:
            count = tick_count
            errors = list(stream_errors)
            quotes = dict(latest_ticks)
        report_path = write_report(final_scan, args.reports_dir, tick_count=count, stream_errors=errors, latest_ticks=quotes, paper_report=final_paper)
        print(json.dumps({
            "phase": "POST_SESSION",
            "ready_series": final_refresh.ready_series,
            "total_series": final_refresh.total_series,
            "stocks_ready": final_scan.ready_stocks,
            "signals": len(final_scan.signals),
            "paper_positions_open": final_paper.open_positions,
            "paper_positions_opened": final_paper.positions_opened,
            "paper_positions_closed": final_paper.positions_closed,
            "report": str(report_path),
        }, indent=2))
        feed.stop_stream()
        return 0 if final_scan.ready_stocks == 50 else 2
    except KeyboardInterrupt:
        try:
            feed.stop_stream()
        except Exception:
            pass
        return 130
    except Exception as exc:
        print(json.dumps({"status": "FAILED", "error": f"{type(exc).__name__}: {exc}"}, indent=2))
        try:
            feed.stop_stream()
        except Exception:
            pass
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
