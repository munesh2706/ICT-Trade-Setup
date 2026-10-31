"""Diagnose Angel One historical intraday session-range behaviour.

This is a read-only authenticated probe. It compares one full NSE session
request with two aligned sub-session requests for one current NIFTY 50 member.
It records provider-returned timestamps only; it never fills or alters candles.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.reconcile_nifty50_history import load_calendar
from ict_engine.stock_feed import INTERVAL_MINUTES, AngelOneStockFeed
from ict_engine.stock_universe import download_nse_universe

TIMEFRAMES = ("1m", "5m", "15m")


def describe(rows):
    stamps = [row.timestamp.isoformat() for row in rows]
    return {
        "count": len(stamps),
        "first": stamps[0] if stamps else None,
        "last": stamps[-1] if stamps else None,
        "timestamps": stamps,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--calendar", type=Path, required=True)
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pace-seconds", type=float, default=1.0)
    args = parser.parse_args()

    calendar = load_calendar(args.calendar)
    session = calendar.session_for(args.date)
    if session is None:
        raise SystemExit(f"{args.date} is explicitly a closed NSE date")
    universe = download_nse_universe()
    feed = AngelOneStockFeed.connect_from_env(universe, pace_seconds=args.pace_seconds)
    members = {member.symbol for member in universe.constituents}
    nfo_stock_futures = set(feed.cas_eligible_symbols)
    symbol = universe.constituents[0].symbol
    cas_eligible = symbol in nfo_stock_futures
    open_at = session.open_at
    close_at = session.close_at
    continuous_close = session.continuous_close_at if cas_eligible and session.continuous_close_at else close_at
    split_at = open_at.replace(hour=12, minute=15, second=0, microsecond=0)
    if not open_at < split_at < close_at:
        raise SystemExit("diagnostic split boundary is outside this session")

    report = {
        "date": args.date.isoformat(),
        "symbol": symbol,
        "token": feed.instruments[symbol].token,
        "instrument_master_sha256": feed.master_sha256,
        "derivatives_master_sha256": feed.master_sha256,
        "cas_eligibility_proxy": "Angel One NFO FUTSTK rows for current NIFTY 50 membership",
        "symbol_cas_eligible": cas_eligible,
        "continuous_close": continuous_close.isoformat(),
        "nifty50_stock_futures_symbols": sorted(nfo_stock_futures),
        "nifty50_without_stock_futures": sorted(members - nfo_stock_futures),
        "session_open": open_at.isoformat(),
        "session_close": close_at.isoformat(),
        "split_at": split_at.isoformat(),
        "timeframes": {},
    }
    for timeframe in TIMEFRAMES:
        full = feed.fetch_candles(symbol, timeframe, open_at, close_at)
        first = feed.fetch_candles(symbol, timeframe, open_at, split_at)
        second = feed.fetch_candles(symbol, timeframe, split_at, close_at)
        expected = {
            stamp.isoformat()
            for stamp in calendar.expected_candle_starts(
                args.date, INTERVAL_MINUTES[timeframe], cas_eligible=cas_eligible,
            )
        }
        full_continuous = [row for row in full if row.timestamp < continuous_close]
        split_rows = first + second
        split_continuous = [row for row in split_rows if row.timestamp < continuous_close]
        full_continuous_stamps = {row.timestamp.isoformat() for row in full_continuous}
        split_continuous_stamps = {row.timestamp.isoformat() for row in split_continuous}
        auction_rows = [row for row in full if row.timestamp >= continuous_close]
        report["timeframes"][timeframe] = {
            "expected_continuous_count": len(expected),
            "missing_from_continuous_session": sorted(expected - full_continuous_stamps),
            "unexpected_in_continuous_session": sorted(full_continuous_stamps - expected),
            "missing_from_split_continuous_union": sorted(expected - split_continuous_stamps),
            "full_session_raw": describe(full),
            "continuous_session_from_full_request": describe(full_continuous),
            "auction_period_rows_from_full_request": describe(auction_rows),
            "first_segment": describe(first),
            "second_segment": describe(second),
            "split_continuous_union_count": len(split_continuous_stamps),
            "full_only_continuous_count": len(full_continuous_stamps - split_continuous_stamps),
            "split_only_continuous_count": len(split_continuous_stamps - full_continuous_stamps),
            "split_recovers_continuous_timestamps_absent_from_full": bool(split_continuous_stamps - full_continuous_stamps),
            "raw_request_params": [
                feed.raw_responses[-3]["request_params"],
                feed.raw_responses[-2]["request_params"],
                feed.raw_responses[-1]["request_params"],
            ],
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
