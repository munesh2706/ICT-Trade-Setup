"""Pre-session NIFTY 50 historical reconciliation using Angel One SmartAPI.

The script requires an explicit NSE session calendar JSON. It will not infer
trading days from weekdays or create missing candles.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ict_engine.market_calendar import ExchangeCalendar, TradingSession
from ict_engine.stock_feed import AngelOneStockFeed
from ict_engine.stock_reconciliation import reconcile_universe
from ict_engine.stock_storage import StockCandleStore
from ict_engine.stock_universe import download_nse_universe, save_universe_snapshot

IST = ZoneInfo("Asia/Kolkata")

def load_calendar(path: Path) -> ExchangeCalendar:
    payload = json.loads(path.read_text(encoding="utf-8"))
    sessions = [
        TradingSession(
            "NSE", date.fromisoformat(row["date"]),
            datetime.fromisoformat(row["open_at"]),
            datetime.fromisoformat(row["close_at"]),
            row["source"],
            datetime.fromisoformat(row["continuous_close_at"]) if row.get("continuous_close_at") else None,
            row.get("continuous_close_source"),
        ) for row in payload["sessions"]
    ]
    return ExchangeCalendar(
        "NSE", payload["timezone"],
        date.fromisoformat(payload["coverage_start"]),
        date.fromisoformat(payload["coverage_end"]),
        sessions,
        [date.fromisoformat(x) for x in payload["closed_dates"]],
        payload["source"],
    )

def main() -> int:
    parser = argparse.ArgumentParser(description="Repair and verify NIFTY 50 Angel One historical data")
    parser.add_argument("--calendar", type=Path, required=True, help="Explicit, provenance-backed NSE sessions JSON")
    parser.add_argument("--database", type=Path, default=ROOT / "data" / "nifty50_stocks.sqlite")
    parser.add_argument("--universe-dir", type=Path, default=ROOT / "data" / "universe")
    parser.add_argument("--start-date", type=date.fromisoformat, required=True, help="First date requiring complete history")
    parser.add_argument("--through-date", type=date.fromisoformat, required=True, help="Last completed trading date to reconcile")
    parser.add_argument("--timeframes", nargs="+", default=["1m", "5m", "15m", "1h", "1d"],
                        choices=["1m", "3m", "5m", "10m", "15m", "30m", "1h", "1d"])
    parser.add_argument("--pace-seconds", type=float, default=1.0)
    parser.add_argument("--max-passes", type=int, default=2)
    parser.add_argument("--daily-anchor", choices=["session_open", "local_midnight"],
                        help="Required for 1d because provider daily timestamp anchoring must be verified")
    args = parser.parse_args()
    if args.through_date < args.start_date:
        parser.error("--through-date must be on or after --start-date")
    if "1d" in args.timeframes and not args.daily_anchor:
        parser.error("--daily-anchor is required when 1d is selected")
    try:
        calendar = load_calendar(args.calendar)
        if args.start_date < calendar.coverage_start or args.through_date > calendar.coverage_end:
            raise ValueError("requested date range is outside explicit calendar coverage")
        trading_dates = []
        cursor = args.start_date
        while cursor <= args.through_date:
            # session_for raises when the calendar has no explicit date entry.
            if calendar.session_for(cursor) is not None:
                trading_dates.append(cursor)
            cursor = date.fromordinal(cursor.toordinal() + 1)
        if not trading_dates:
            raise ValueError("date range contains no explicitly configured NSE trading sessions")
        universe = download_nse_universe()
        universe_path = save_universe_snapshot(universe, args.universe_dir)
        feed = AngelOneStockFeed.connect_from_env(universe, pace_seconds=args.pace_seconds)
        args.database.parent.mkdir(parents=True, exist_ok=True)
        store = StockCandleStore(args.database)
        result = reconcile_universe(
            universe=universe, feed=feed, store=store, calendar=calendar,
            trading_dates=trading_dates, timeframes=args.timeframes,
            max_passes=args.max_passes, daily_anchor=args.daily_anchor,
        )
        summary = {
            "snapshot_id": result.snapshot_id,
            "universe_snapshot_id": result.universe_snapshot_id,
            "universe_file": str(universe_path),
            "instrument_master_sha256": feed.master_sha256,
            "verified": result.verified,
            "total_missing": result.total_missing,
            "series": [{
                "symbol": x.symbol, "timeframe": x.timeframe,
                "expected": x.expected, "present_before": x.present_before,
                "fetched": x.fetched, "missing_after": len(x.missing_after),
                "missing_timestamps": list(x.missing_after[:100]),
            } for x in result.series],
        }
        print(json.dumps(summary, indent=2))
        return 0 if result.verified else 2
    except Exception as exc:
        print(json.dumps({"status": "FAILED", "error": f"{type(exc).__name__}: {exc}"}, indent=2))
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
