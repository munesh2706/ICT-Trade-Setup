"""Download historical spot-index candles into an immutable ACQUIRED snapshot.

Run from the repository root. This script never places broker orders.
"""
from __future__ import annotations
import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ict_engine.angelone_feed import AngelOneHistoricalFeed
from ict_engine.instruments import INDEX_INSTRUMENTS
from ict_engine.storage import CandleStore

ROOT = Path(__file__).resolve().parents[1]
IST = ZoneInfo("Asia/Kolkata")

def parse_local(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=IST)
    except ValueError:
        raise argparse.ArgumentTypeError("Use YYYY-MM-DD HH:MM in India local time") from None

def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Angel One historical index candles; read-only")
    parser.add_argument("--start", required=True, type=parse_local, help="India local time, YYYY-MM-DD HH:MM")
    parser.add_argument("--end", required=True, type=parse_local, help="Exclusive India local time, YYYY-MM-DD HH:MM")
    parser.add_argument("--timeframe", choices=("1m", "3m", "5m", "10m", "15m", "30m", "1h", "1d"), required=True)
    parser.add_argument("--instruments", nargs="+", choices=tuple(INDEX_INSTRUMENTS), default=list(INDEX_INSTRUMENTS))
    parser.add_argument("--snapshot-id", help="Optional immutable dataset ID; generated if omitted")
    parser.add_argument("--database", type=Path, default=ROOT / "data" / "ict_market.sqlite")
    parser.add_argument("--pace-seconds", type=float, default=1.0)
    args = parser.parse_args()
    if args.end <= args.start:
        parser.error("--end must be later than --start")
    snapshot_id = args.snapshot_id or datetime.now(ZoneInfo("UTC")).strftime("angel_%Y%m%dT%H%M%SZ")
    args.database.parent.mkdir(parents=True, exist_ok=True)
    store = CandleStore(args.database)
    store.create_snapshot(snapshot_id, description=f"Angel One {args.timeframe} {args.start.isoformat()} to {args.end.isoformat()}")
    counts = {}
    feed = None
    raw_index = 0
    try:
        feed = AngelOneHistoricalFeed.connect_from_env(pace_seconds=args.pace_seconds)
        for instrument_id in args.instruments:
            candles = feed.fetch_range(instrument_id, args.timeframe, args.start, args.end)
            for raw in feed.raw_responses[raw_index:]:
                store.store_raw_batch(snapshot_id, raw_index, raw["instrument_id"], raw["timeframe"], raw["fetched_at"], raw["request_params"], raw["payload"])
                raw_index += 1
            if not candles:
                raise RuntimeError(f"No candles returned for {instrument_id}; snapshot will not be marked ACQUIRED")
            counts[instrument_id] = len(candles)
            store.store_candles(instrument_id, args.timeframe, snapshot_id, "ANGEL_HISTORICAL", candles)
        store.finalize_snapshot(snapshot_id, status="ACQUIRED")
    except Exception as exc:
        try:
            if feed is not None:
                for raw in feed.raw_responses[raw_index:]:
                    store.store_raw_batch(snapshot_id, raw_index, raw["instrument_id"], raw["timeframe"], raw["fetched_at"], raw["request_params"], raw["payload"])
                    raw_index += 1
        except Exception:
            pass
        try:
            if store.snapshot_status(snapshot_id) == "OPEN":
                store.finalize_snapshot(snapshot_id, status="FAILED", description=f"FAILED: {type(exc).__name__}")
        except Exception:
            pass
        print(json.dumps({"status": "FAILED", "snapshot_id": snapshot_id, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps({"status": "ACQUIRED", "snapshot_id": snapshot_id, "database": str(args.database), "timeframe": args.timeframe, "counts": counts, "note": "Calendar coverage audit is still required before the snapshot can be used for backtesting."}, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())