"""Incremental completed-candle refresh during the NSE cash session.

The live WebSocket is used for quote monitoring only. This module obtains
completed 1m/5m/15m candles from Angel One Historical API and verifies each
stock/timeframe independently against the explicit NSE session grid.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Sequence
from uuid import uuid4

from .market_calendar import ExchangeCalendar
from .stock_feed import INTERVAL_MINUTES, AngelOneStockFeed
from .stock_reconciliation import _contiguous_groups, _split_group
from .stock_storage import StockCandleStore
from .stock_universe import UniverseSnapshot

@dataclass(frozen=True, slots=True)
class LiveSeriesRefresh:
    symbol: str
    timeframe: str
    expected_completed: int
    present_before: int
    inserted: int
    missing_after: int
    status: str

@dataclass(frozen=True, slots=True)
class LiveRefreshReport:
    scan_date: date
    as_of: datetime
    series: tuple[LiveSeriesRefresh, ...]

    @property
    def ready_series(self) -> int:
        return sum(x.status == "READY" for x in self.series)

    @property
    def total_series(self) -> int:
        return len(self.series)

def refresh_current_session(
    *,
    universe: UniverseSnapshot,
    feed: AngelOneStockFeed,
    store: StockCandleStore,
    calendar: ExchangeCalendar,
    as_of: datetime,
    timeframes: Sequence[str] = ("1m", "5m", "15m"),
) -> LiveRefreshReport:
    """Fetch missing completed bars for the current NSE session.

    Each stock/timeframe is verified independently. A stock with incomplete
    current-session data is not eligible for scanning, while other fully
    reconciled stocks can continue. Historical snapshots remain immutable.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    scan_date = as_of.astimezone(calendar.timezone).date()
    if calendar.exchange != "NSE":
        raise ValueError("NIFTY 50 stocks require NSE calendar")
    session = calendar.session_for(scan_date)
    if session is None:
        raise ValueError("as_of date is not an NSE trading session")
    if len(universe.constituents) != 50 or set(feed.instruments) != {x.symbol for x in universe.constituents}:
        raise ValueError("feed instruments must exactly match all 50 NIFTY 50 constituents")
    if not timeframes or len(set(timeframes)) != len(timeframes):
        raise ValueError("timeframes must be non-empty and unique")
    allowed = {"1m", "3m", "5m", "10m", "15m", "30m", "1h"}
    if set(timeframes) - allowed:
        raise ValueError("live refresh supports intraday intervals only; daily bars use separate timestamp-anchor verification")
    if as_of.astimezone(calendar.timezone) <= session.open_at.astimezone(calendar.timezone):
        return LiveRefreshReport(scan_date, as_of, ())

    reports = []
    cas_eligible_symbols = getattr(feed, "cas_eligible_symbols", set())
    for timeframe in timeframes:
        interval = INTERVAL_MINUTES[timeframe]
        for member in universe.constituents:
            cas_eligible = member.symbol in cas_eligible_symbols
            expected_all = calendar.expected_candle_starts(
                scan_date, interval, cas_eligible=cas_eligible,
            )
            expected = [stamp for stamp in expected_all if stamp + timedelta(minutes=interval) <= as_of.astimezone(calendar.timezone)]
            if not expected:
                continue
            range_start = expected[0]
            range_end = expected[-1] + timedelta(minutes=interval)
            existing = store.load_reconciliation_candles(
                member.symbol, timeframe, range_start, range_end, universe.snapshot_id,
            )
            present = {c.timestamp.astimezone(calendar.timezone) for c in existing}
            missing = [stamp for stamp in expected if stamp not in present]
            present_before = len(expected) - len(missing)
            inserted = 0

            if missing:
                snapshot_id = (
                    f"live_{scan_date.isoformat()}_{member.symbol}_{timeframe}_"
                    f"{uuid4().hex[:8]}"
                )
                store.create_snapshot(snapshot_id, universe.snapshot_id, "Incremental live-session candle refresh")
                batch_no = 0
                try:
                    for group in _contiguous_groups(missing, expected):
                        for chunk in _split_group(group, timeframe):
                            start = chunk[0]
                            end = chunk[-1] + timedelta(minutes=interval)
                            raw_before = len(feed.raw_responses)
                            try:
                                candles = feed.fetch_candles(member.symbol, timeframe, start, end)
                            except Exception:
                                if len(feed.raw_responses) > raw_before:
                                    raw = feed.raw_responses[-1]
                                    store.store_raw(
                                        snapshot_id, batch_no, member.symbol, timeframe,
                                        feed.instruments[member.symbol].token,
                                        raw["fetched_at"], raw["request_params"], raw["payload"],
                                    )
                                    batch_no += 1
                                continue
                            raw = feed.raw_responses[-1]
                            store.store_raw(
                                snapshot_id, batch_no, member.symbol, timeframe,
                                feed.instruments[member.symbol].token,
                                raw["fetched_at"], raw["request_params"], raw["payload"],
                            )
                            batch_no += 1
                            wanted = set(chunk)
                            exact = [c for c in candles if c.timestamp.astimezone(calendar.timezone) in wanted]
                            exact.sort(key=lambda c: c.timestamp)
                            if exact:
                                inserted += store.store_candles(
                                    snapshot_id, member.symbol, timeframe,
                                    feed.instruments[member.symbol].token, exact,
                                )
                    store.finalize(snapshot_id, "ACQUIRED")
                except Exception as exc:
                    try:
                        if store.snapshot_status(snapshot_id) == "OPEN":
                            store.finalize(snapshot_id, "FAILED", f"FAILED: {type(exc).__name__}")
                    except Exception:
                        pass
                    raise

                refreshed = store.load_reconciliation_candles(
                    member.symbol, timeframe, range_start, range_end, universe.snapshot_id,
                )
                present = {c.timestamp.astimezone(calendar.timezone) for c in refreshed}
                missing = [stamp for stamp in expected if stamp not in present]
                if not missing:
                    store.mark_series_snapshots_verified(universe.snapshot_id, member.symbol, timeframe)

            reports.append(LiveSeriesRefresh(
                member.symbol, timeframe, len(expected), present_before,
                inserted, len(missing), "READY" if not missing else "INCOMPLETE",
            ))
    return LiveRefreshReport(scan_date, as_of, tuple(reports))
