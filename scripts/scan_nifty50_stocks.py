"""Run the explainable NIFTY 50 stock ICT scanner on verified Angel One data."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.reconcile_nifty50_history import load_calendar
from ict_engine.stock_scanner import StockICTScanConfig, StockICTScanner
from ict_engine.stock_storage import StockCandleStore
from ict_engine.stock_universe import download_nse_universe, save_universe_snapshot

IST = ZoneInfo("Asia/Kolkata")

def encode(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime,)):
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

def main() -> int:
    parser = argparse.ArgumentParser(description="Scan NIFTY 50 stocks for source-backed ICT candidates")
    parser.add_argument("--calendar", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=ROOT / "data" / "nifty50_stocks.sqlite")
    parser.add_argument("--universe-dir", type=Path, default=ROOT / "data" / "universe")
    parser.add_argument("--as-of", help="Timezone-aware ISO timestamp; defaults to current India time")
    parser.add_argument("--disable-silver-bullet", action="store_true")
    parser.add_argument("--pivot-left", type=int, default=2)
    parser.add_argument("--pivot-right", type=int, default=2)
    parser.add_argument("--displacement-threshold", type=Decimal, default=Decimal("0.65"))
    parser.add_argument("--max-bars-after-sweep", type=int, default=6)
    parser.add_argument("--max-bars-after-mss", type=int, default=3)
    args = parser.parse_args()
    try:
        as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00")) if args.as_of else datetime.now(IST)
        if as_of.tzinfo is None:
            raise ValueError("--as-of must include timezone offset")
        calendar = load_calendar(args.calendar)
        universe = download_nse_universe()
        universe_path = save_universe_snapshot(universe, args.universe_dir)
        store = StockCandleStore(args.database)
        config = StockICTScanConfig(
            enable_silver_bullet=not args.disable_silver_bullet,
            pivot_left=args.pivot_left, pivot_right=args.pivot_right,
            displacement_min_body_to_range=args.displacement_threshold,
            max_bars_after_sweep=args.max_bars_after_sweep,
            max_bars_after_mss=args.max_bars_after_mss,
        )
        report = StockICTScanner(config).scan_universe(
            universe=universe, store=store, calendar=calendar,
            scan_date=as_of.astimezone(IST).date(), as_of=as_of,
        )
        payload = encode(report)
        payload["universe_file"] = str(universe_path)
        print(json.dumps(payload, indent=2))
        return 0 if report.ready_stocks == 50 else 2
    except Exception as exc:
        print(json.dumps({"status": "FAILED", "error": f"{type(exc).__name__}: {exc}"}, indent=2))
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
