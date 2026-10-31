"""One-shot incremental current-session refresh for all NIFTY 50 stocks."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.reconcile_nifty50_history import load_calendar
from ict_engine.stock_feed import AngelOneStockFeed
from ict_engine.stock_live_refresh import refresh_current_session
from ict_engine.stock_storage import StockCandleStore
from ict_engine.stock_universe import download_nse_universe, save_universe_snapshot

IST = ZoneInfo("Asia/Kolkata")

def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh completed current-session NIFTY 50 stock candles from Angel One")
    parser.add_argument("--calendar", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=ROOT / "data" / "nifty50_stocks.sqlite")
    parser.add_argument("--universe-dir", type=Path, default=ROOT / "data" / "universe")
    parser.add_argument("--timeframes", nargs="+", default=["1m", "5m", "15m"],
                        choices=["1m", "3m", "5m", "10m", "15m", "30m", "1h"])
    parser.add_argument("--as-of", help="Timezone-aware ISO timestamp; defaults to current India time")
    parser.add_argument("--pace-seconds", type=float, default=0.4)
    args = parser.parse_args()
    try:
        as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00")) if args.as_of else datetime.now(IST)
        if as_of.tzinfo is None:
            raise ValueError("--as-of must include timezone offset")
        calendar = load_calendar(args.calendar)
        universe = download_nse_universe()
        universe_path = save_universe_snapshot(universe, args.universe_dir)
        feed = AngelOneStockFeed.connect_from_env(universe, pace_seconds=args.pace_seconds)
        args.database.parent.mkdir(parents=True, exist_ok=True)
        store = StockCandleStore(args.database)
        report = refresh_current_session(
            universe=universe, feed=feed, store=store, calendar=calendar,
            as_of=as_of, timeframes=args.timeframes,
        )
        payload = {
            "scan_date": report.scan_date.isoformat(),
            "as_of": report.as_of.isoformat(),
            "universe_snapshot_id": universe.snapshot_id,
            "universe_file": str(universe_path),
            "instrument_master_sha256": feed.master_sha256,
            "ready_series": report.ready_series,
            "total_series": report.total_series,
            "series": [{
                "symbol": x.symbol, "timeframe": x.timeframe,
                "expected_completed": x.expected_completed,
                "present_before": x.present_before, "inserted": x.inserted,
                "missing_after": x.missing_after, "status": x.status,
            } for x in report.series],
        }
        print(json.dumps(payload, indent=2))
        return 0 if report.total_series == 0 or report.ready_series == report.total_series else 2
    except Exception as exc:
        print(json.dumps({"status": "FAILED", "error": f"{type(exc).__name__}: {exc}"}, indent=2))
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
