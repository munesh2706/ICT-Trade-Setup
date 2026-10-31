"""Event-driven historical replay for the NIFTY 50 stock ICT paper engine.

The current NSE constituent snapshot is not a point-in-time historical universe.
For dates before the snapshot's as_of_date, an explicit survivorship-bias
opt-in is required. All candles are reconciled from Angel One before replay.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from scripts.reconcile_nifty50_history import load_calendar
from ict_engine.stock_feed import AngelOneStockFeed
from ict_engine.stock_reconciliation import reconcile_universe
from ict_engine.stock_scanner import StockICTScanConfig, StockICTScanner
from ict_engine.stock_storage import StockCandleStore
from ict_engine.stock_universe import (
    download_nse_universe, load_universe_snapshot, save_universe_snapshot,
)
from ict_engine.paper_store import StockPaperStore
from ict_engine.paper_trading import StockPaperTradingEngine, load_paper_trading_config
from ict_engine.performance import TradeResult, summarize_trades

IST = ZoneInfo("Asia/Kolkata")
ROOT = Path(__file__).resolve().parents[1]

def encode(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return encode(asdict(value))
    if isinstance(value, dict):
        return {str(k): encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode(v) for v in value]
    return value

def _summary(rows):
    trades = [TradeResult(
        gross_pnl=Decimal(row["gross_pnl"]),
        fees=Decimal(row["fees"]),
        slippage_cost=Decimal(row["slippage_cost"]),
        r_multiple=Decimal(row["r_multiple"]) if row.get("r_multiple") is not None else None,
        duration_minutes=int(row["duration_minutes"]) if row.get("duration_minutes") is not None else None,
    ) for row in rows]
    return encode(summarize_trades(trades))

def _by_entry_date(rows, cutoff: date, in_sample: bool):
    selected = []
    for row in rows:
        entry_date = datetime.fromisoformat(row["entry_time"]).astimezone(IST).date()
        if (entry_date < cutoff) == in_sample:
            selected.append(row)
    return selected

def run_backtest(args) -> dict:
    if not args.source_db.is_file():
        raise ValueError(f"verified source database does not exist: {args.source_db}")
    if args.output_db.exists():
        raise ValueError(f"output journal already exists; refusing to overwrite: {args.output_db}")
    if args.end < args.start:
        raise ValueError("--end must be on or after --start")
    if args.out_of_sample_start and not (args.start < args.out_of_sample_start <= args.end):
        raise ValueError("out-of-sample start must be after --start and no later than --end")

    calendar = load_calendar(args.calendar)
    if args.start < calendar.coverage_start or args.end > calendar.coverage_end:
        raise ValueError("requested backtest range is outside the explicit NSE calendar coverage")
    paper_config = load_paper_trading_config(args.paper_config)
    universe = load_universe_snapshot(args.universe_file) if args.universe_file else download_nse_universe()
    universe_path = save_universe_snapshot(universe, args.universe_dir)
    universe_as_of = date.fromisoformat(universe.as_of_date)
    survivorship_warning = None
    if args.start < universe_as_of:
        if not args.allow_current_universe_survivorship_bias:
            raise ValueError(
                f"current NIFTY 50 snapshot is dated {universe_as_of}; "
                "historical replay requires point-in-time membership snapshots. "
                "Use --allow-current-universe-survivorship-bias only for exploratory analysis."
            )
        survivorship_warning = (
            "Current constituent membership was applied to historical dates. "
            "Results contain survivorship/constituent-selection bias and are not point-in-time valid."
        )

    warmup_start = max(calendar.coverage_start, args.start - timedelta(days=14))
    warmup_sessions = calendar.sessions_between(warmup_start, args.end)
    replay_sessions = [s for s in warmup_sessions if args.start <= s.trading_date <= args.end]
    if not replay_sessions:
        raise ValueError("no explicit NSE trading sessions exist in the requested backtest range")

    feed = AngelOneStockFeed.connect_from_env(universe, pace_seconds=args.pace_seconds)
    source = StockCandleStore(args.source_db)
    reconciliation = reconcile_universe(
        universe=universe, feed=feed, store=source, calendar=calendar,
        trading_dates=[s.trading_date for s in warmup_sessions],
        timeframes=["1m", "5m", "15m"], max_passes=args.max_passes,
    )
    if not reconciliation.verified:
        raise RuntimeError(
            f"historical reconciliation failed; {reconciliation.total_missing} expected bars remain missing"
        )

    args.output_db.parent.mkdir(parents=True, exist_ok=True)
    journal = StockPaperStore(args.output_db)
    engine = StockPaperTradingEngine(paper_config, feed.instruments)
    scanner = StockICTScanner(StockICTScanConfig(enable_silver_bullet=not args.disable_silver_bullet))
    scan_count = 0
    skipped = []
    try:
        for session in replay_sessions:
            as_of = session.open_at.astimezone(IST) + timedelta(minutes=1)
            close_at = session.close_at.astimezone(IST)
            while as_of <= close_at:
                report = scanner.scan_universe(
                    universe=universe, store=source, calendar=calendar,
                    scan_date=session.trading_date, as_of=as_of,
                )
                if report.ready_stocks != 50:
                    raise RuntimeError(
                        f"DATA GATE CLOSED at {as_of.isoformat()}: "
                        f"{report.ready_stocks}/50 stocks passed verified candle readiness"
                    )
                engine.process_scan_report(report, candles=source, journal=journal)
                scan_count += 1
                as_of += timedelta(minutes=1)
            engine.expire_pending_signals(journal, close_at)

        closed_rows = journal.closed_trade_rows()
        metrics = {"all": _summary(closed_rows)}
        if args.out_of_sample_start:
            metrics["in_sample"] = _summary(_by_entry_date(closed_rows, args.out_of_sample_start, True))
            metrics["out_of_sample"] = _summary(_by_entry_date(closed_rows, args.out_of_sample_start, False))
        open_positions = journal.load_open_positions()
        run_id = "stock_ict_backtest_" + datetime.now(IST).strftime("%Y%m%dT%H%M%S") + "_" + uuid4().hex[:8]
        result = {
            "run_id": run_id,
            "status": "COMPLETED",
            "universe_snapshot_id": universe.snapshot_id,
            "universe_as_of_date": universe.as_of_date,
            "universe_source_sha256": universe.source_sha256,
            "instrument_master_sha256": feed.master_sha256,
            "historical_reconciliation_snapshot_id": reconciliation.snapshot_id,
            "calendar_file": str(args.calendar),
            "start_date": args.start.isoformat(),
            "end_date": args.end.isoformat(),
            "warmup_start": warmup_start.isoformat(),
            "scan_count": scan_count,
            "scan_frequency": "1 minute",
            "survivorship_bias_warning": survivorship_warning,
            "cost_and_risk_config": {
                "starting_equity": str(paper_config.starting_equity),
                "round_trip_fees_per_share": str(paper_config.round_trip_fees_per_share),
                "round_trip_slippage_points": str(paper_config.round_trip_slippage_points),
                "risk_per_trade_fraction": str(paper_config.risk_per_trade_fraction),
                "max_daily_loss_fraction": str(paper_config.max_daily_loss_fraction),
                "entry_variant": paper_config.entry_variant,
                "stop_reference_index": paper_config.stop_reference_index,
                "target_selection": paper_config.target_selection,
                "max_entry_wait_minutes": paper_config.max_entry_wait_minutes,
            },
            "performance": metrics,
            "open_positions_at_end": len(open_positions),
            "open_positions": [{
                "symbol": p.instrument_id, "direction": p.direction,
                "entry_time": p.entry_time.isoformat(), "entry_price": str(p.entry_price),
                "stop": str(p.stop), "target": str(p.target), "quantity": str(p.quantity),
            } for p in open_positions],
            "limitations": [
                "Current membership is not point-in-time unless historical universe snapshots are supplied.",
                "Silver Bullet is alert-only in the paper engine.",
                "Paper costs use configured flat per-share estimates, not a complete Angel One statutory charge model.",
                "Entry bars are excluded from exit evaluation; same-bar barrier ambiguity is resolved conservatively.",
                "Open positions at the end of the range are reported, not force-closed.",
            ],
            "paper_journal_database": str(args.output_db),
        }
        report_path = args.report or (ROOT / "data" / "reports" / f"{run_id}.json")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        result["report_path"] = str(report_path)
        return result
    finally:
        feed.logout()

def main() -> int:
    parser = argparse.ArgumentParser(description="Angel One NIFTY 50 stock ICT historical paper backtest")
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    parser.add_argument("--calendar", type=Path, required=True)
    parser.add_argument("--paper-config", type=Path, required=True)
    parser.add_argument("--source-db", type=Path, default=ROOT / "data" / "nifty50_stocks.sqlite")
    parser.add_argument("--output-db", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--universe-file", type=Path)
    parser.add_argument("--universe-dir", type=Path, default=ROOT / "data" / "universe")
    parser.add_argument("--out-of-sample-start", type=date.fromisoformat)
    parser.add_argument("--allow-current-universe-survivorship-bias", action="store_true")
    parser.add_argument("--pace-seconds", type=float, default=0.4)
    parser.add_argument("--max-passes", type=int, default=2)
    parser.add_argument("--disable-silver-bullet", action="store_true")
    args = parser.parse_args()
    try:
        result = run_backtest(args)
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "FAILED", "error": f"{type(exc).__name__}: {exc}"}, indent=2))
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
