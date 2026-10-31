"""Pre-session Angel One historical gap detection, repair and verification."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from hashlib import sha256
from typing import Iterable, Sequence
from uuid import uuid4
from zoneinfo import ZoneInfo

from .market_calendar import ExchangeCalendar
from .stock_feed import INTERVAL_MINUTES, MAX_REQUEST_DAYS, AngelOneStockFeed
from .stock_storage import StockCandleStore
from .stock_universe import UniverseSnapshot

IST = ZoneInfo("Asia/Kolkata")

@dataclass(frozen=True, slots=True)
class SeriesRepair:
    symbol: str
    timeframe: str
    expected: int
    present_before: int
    fetched: int
    missing_after: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    snapshot_id: str
    universe_snapshot_id: str
    verified: bool
    series: tuple[SeriesRepair, ...]

    @property
    def total_missing(self) -> int:
        return sum(len(x.missing_after) for x in self.series)

def _expected(calendar: ExchangeCalendar, dates: Sequence[date], timeframe: str) -> list[datetime]:
    if timeframe not in INTERVAL_MINUTES:
        raise ValueError(f"unsupported timeframe {timeframe}")
    minutes = INTERVAL_MINUTES[timeframe]
    result = []
    for day in dates:
        if minutes == 1440:
            session = calendar.session_for(day)
            if session:
                result.append(session.open_at.astimezone(calendar.timezone))
        else:
            result.extend(calendar.expected_candle_starts(day, minutes))
    return result

def _contiguous_groups(missing: Sequence[datetime], expected: Sequence[datetime]) -> list[list[datetime]]:
    """Group missing expected bars by adjacency in the expected session grid."""
    expected_positions = {stamp: index for index, stamp in enumerate(expected)}
    ordered = sorted(set(missing))
    groups: list[list[datetime]] = []
    for stamp in ordered:
        position = expected_positions[stamp]
        if not groups or position != expected_positions[groups[-1][-1]] + 1:
            groups.append([stamp])
        else:
            groups[-1].append(stamp)
    return groups

def _split_group(group: Sequence[datetime], timeframe: str) -> list[list[datetime]]:
    max_span = timedelta(days=MAX_REQUEST_DAYS[timeframe])
    chunks: list[list[datetime]] = []
    current: list[datetime] = []
    for stamp in group:
        if current and stamp - current[0] >= max_span:
            chunks.append(current)
            current = []
        current.append(stamp)
    if current:
        chunks.append(current)
    return chunks

def reconcile_universe(
    *,
    universe: UniverseSnapshot,
    feed: AngelOneStockFeed,
    store: StockCandleStore,
    calendar: ExchangeCalendar,
    trading_dates: Sequence[date],
    timeframes: Sequence[str],
    max_passes: int = 2,
) -> ReconciliationResult:
    """Backfill all expected missing timestamps before releasing data to strategy.

    Historical responses are stored raw. Only exact expected timestamps are
    persisted as candles. The audit is over the union of previously verified
    and acquired snapshots for this same membership snapshot. Any remaining
    gap keeps all acquired snapshots unverified and blocks downstream signals.
    """
    if not trading_dates:
        raise ValueError("trading_dates cannot be empty")
    if calendar.exchange != "NSE":
        raise ValueError("NIFTY 50 stocks require the NSE trading calendar")
    if max_passes < 1 or max_passes > 5:
        raise ValueError("max_passes must be between 1 and 5")
    if len(feed.instruments) != 50:
        raise ValueError("all 50 Angel One instruments must be resolved before reconciliation")
    unknown = set(timeframes) - set(INTERVAL_MINUTES)
    if unknown:
        raise ValueError(f"unsupported timeframes: {sorted(unknown)}")

    snapshot_id = "stock_repair_" + datetime.now(IST).strftime("%Y%m%dT%H%M%S") + "_" + uuid4().hex[:8]
    store.create_snapshot(snapshot_id, universe.snapshot_id, "Pre-session historical gap repair")
    batch_no = 0
    fetched_counts: dict[tuple[str, str], int] = {}
    before_counts: dict[tuple[str, str], int] = {}
    expected_by_series: dict[tuple[str, str], list[datetime]] = {}

    try:
        for timeframe in timeframes:
            for member in universe.constituents:
                symbol = member.symbol
                key = (symbol, timeframe)
                expected = _expected(calendar, trading_dates, timeframe)
                expected_by_series[key] = expected
                existing = store.load_reconciliation_candles(symbol, timeframe)
                present = {c.timestamp.astimezone(IST) for c in existing}
                missing = [x for x in expected if x not in present]
                before_counts[key] = len(expected) - len(missing)
                fetched_counts[key] = 0

                for pass_no in range(max_passes):
                    if not missing:
                        break
                    for group in _contiguous_groups(missing, expected):
                        for chunk in _split_group(group, timeframe):
                            start = chunk[0]
                            end = chunk[-1] + timedelta(minutes=INTERVAL_MINUTES[timeframe])
                            # API bounds are widened to minute precision; returned
                            # rows are filtered to the exact expected grid below.
                            try:
                                candles = feed.fetch_candles(symbol, timeframe, start, end)
                            except Exception:
                                # Preserve already fetched ranges; final audit records
                                # the unresolved expected timestamps without fabricating.
                                continue
                            raw = feed.raw_responses[-1]
                            store.store_raw(
                                snapshot_id, batch_no, symbol, timeframe,
                                feed.instruments[symbol].token, raw["fetched_at"],
                                raw["request_params"], raw["payload"],
                            )
                            batch_no += 1
                            wanted = set(chunk)
                            exact = [c for c in candles if c.timestamp.astimezone(IST) in wanted]
                            exact.sort(key=lambda c: c.timestamp)
                            if exact:
                                inserted = store.store_candles(
                                    snapshot_id, symbol, timeframe,
                                    feed.instruments[symbol].token, exact,
                                )
                                fetched_counts[key] += inserted
                    current = store.load_reconciliation_candles(symbol, timeframe)
                    present = {c.timestamp.astimezone(IST) for c in current}
                    missing = [x for x in expected if x not in present]

        store.finalize(snapshot_id, "ACQUIRED")
    except Exception as exc:
        try:
            if store.snapshot_status(snapshot_id) == "OPEN":
                store.finalize(snapshot_id, "FAILED", f"FAILED: {type(exc).__name__}")
        except Exception:
            pass
        raise

    repairs = []
    all_passed = True
    for key, expected in expected_by_series.items():
        symbol, timeframe = key
        candles = store.load_reconciliation_candles(symbol, timeframe)
        present = {c.timestamp.astimezone(IST) for c in candles}
        missing = tuple(sorted(x.isoformat() for x in expected if x not in present))
        unexpected = tuple(sorted(c.timestamp.isoformat() for c in candles if c.timestamp.astimezone(IST) not in set(expected)))
        if unexpected:
            missing = missing + tuple("UNEXPECTED:" + x for x in unexpected)
        if missing:
            all_passed = False
        repairs.append(SeriesRepair(
            symbol, timeframe, len(expected), before_counts[key],
            fetched_counts[key], missing,
        ))
    if all_passed:
        store.mark_universe_snapshots_verified(universe.snapshot_id)
    return ReconciliationResult(snapshot_id, universe.snapshot_id, all_passed, tuple(repairs))
