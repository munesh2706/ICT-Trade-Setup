"""Pre-market entry point: reconcile all configured history before scanner startup.

Set ICT_HISTORY_START_DATE once to the first date required by the ICT models.
The explicit calendar determines the latest completed session and all expected
timestamps. The script exits non-zero unless the historical data gate passes.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.reconcile_nifty50_history import load_calendar, main as reconcile_main

IST = ZoneInfo("Asia/Kolkata")

def main() -> int:
    parser = argparse.ArgumentParser(description="Run the mandatory NIFTY 50 stock pre-session data gate")
    parser.add_argument("--calendar", type=Path, required=True)
    parser.add_argument("--history-start", type=date.fromisoformat,
                        default=date.fromisoformat(os.environ["ICT_HISTORY_START_DATE"])
                        if os.getenv("ICT_HISTORY_START_DATE") else None)
    parser.add_argument("--timeframes", nargs="+",
                        default=os.getenv("ICT_TIMEFRAMES", "1m 5m 15m 1h").split())
    parser.add_argument("--database", type=Path, default=Path("data/nifty50_stocks.sqlite"))
    parser.add_argument("--universe-dir", type=Path, default=Path("data/universe"))
    parser.add_argument("--daily-anchor", choices=["session_open", "local_midnight"],
                        default=os.getenv("ICT_DAILY_ANCHOR"))
    parser.add_argument("--pace-seconds", type=float, default=1.0)
    parser.add_argument("--max-passes", type=int, default=2)
    args = parser.parse_args()
    if args.history_start is None:
        parser.error("provide --history-start or set ICT_HISTORY_START_DATE")
    if "1d" in args.timeframes and not args.daily_anchor:
        parser.error("1d requires ICT_DAILY_ANCHOR or --daily-anchor")

    now = datetime.now(IST)
    calendar = load_calendar(args.calendar)
    if args.history_start < calendar.coverage_start or now.date() > calendar.coverage_end:
        if now.date() > calendar.coverage_end:
            raise SystemExit("NSE calendar coverage does not extend through today; update the calendar before starting")
        raise SystemExit("history start is outside NSE calendar coverage")

    completed_dates = []
    cursor = args.history_start
    while cursor <= now.date():
        session = calendar.session_for(cursor)
        if session is not None and session.close_at.astimezone(IST) < now:
            completed_dates.append(cursor)
        cursor = date.fromordinal(cursor.toordinal() + 1)
    if not completed_dates:
        raise SystemExit("No completed NSE session exists in the configured reconciliation range")
    through_date = completed_dates[-1]

    # Reuse the tested CLI implementation; no alternate acquisition path.
    sys.argv = [
        sys.argv[0],
        "--calendar", str(args.calendar),
        "--database", str(args.database),
        "--universe-dir", str(args.universe_dir),
        "--start-date", args.history_start.isoformat(),
        "--through-date", through_date.isoformat(),
        "--timeframes", *args.timeframes,
        "--pace-seconds", str(args.pace_seconds),
        "--max-passes", str(args.max_passes),
    ]
    if args.daily_anchor:
        sys.argv.extend(["--daily-anchor", args.daily_anchor])
    return reconcile_main()

if __name__ == "__main__":
    raise SystemExit(main())
