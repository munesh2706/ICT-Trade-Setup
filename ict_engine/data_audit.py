"""Calendar-based data coverage audit and snapshot verification."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, timezone
from typing import Mapping, Sequence
from .market_calendar import ExchangeCalendar
from .models import Candle
from .storage import CandleStore

TIMEFRAME_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "10m": 10, "15m": 15, "30m": 30, "1h": 60, "1d": 1440}

@dataclass(frozen=True, slots=True)
class CoverageAudit:
    expected_count: int
    observed_count: int
    missing: tuple[str, ...]
    unexpected: tuple[str, ...]
    @property
    def passed(self) -> bool:
        return not self.missing and not self.unexpected and self.expected_count == self.observed_count

def audit_candle_grid(candles: Sequence[Candle], *, calendar: ExchangeCalendar, trading_dates: Sequence[date], interval_minutes: int) -> CoverageAudit:
    if not trading_dates:
        raise ValueError("trading_dates cannot be empty")
    expected = []
    for day in trading_dates:
        if interval_minutes == 1440:
            session = calendar.session_for(day)
            if session is not None:
                expected.append(session.open_at)
        else:
            expected.extend(calendar.expected_candle_starts(day, interval_minutes))
    expected_utc = {x.astimezone(timezone.utc).isoformat(timespec="microseconds") for x in expected}
    observed_utc = [c.timestamp.astimezone(timezone.utc).isoformat(timespec="microseconds") for c in candles]
    if any(observed_utc[i] >= observed_utc[i + 1] for i in range(len(observed_utc) - 1)):
        raise ValueError("observed candles must be chronological and duplicate-free")
    observed_set = set(observed_utc)
    missing = tuple(sorted(expected_utc - observed_set))
    unexpected = tuple(sorted(observed_set - expected_utc))
    return CoverageAudit(len(expected_utc), len(observed_utc), missing, unexpected)

def verify_snapshot(store: CandleStore, snapshot_id: str, requirements: Mapping[tuple[str, str], tuple[ExchangeCalendar, Sequence[date]]]) -> dict[tuple[str, str], CoverageAudit]:
    """Promote ACQUIRED snapshot to VERIFIED only if every requested series passes."""
    if store.snapshot_status(snapshot_id) != "ACQUIRED":
        raise ValueError("only an ACQUIRED snapshot can be verified")
    if not requirements:
        raise ValueError("at least one instrument/timeframe requirement is required")
    audits = {}
    for (instrument_id, timeframe), (calendar, dates) in requirements.items():
        if timeframe not in TIMEFRAME_MINUTES:
            raise ValueError(f"unsupported timeframe: {timeframe}")
        candles = store.load_candles(instrument_id, timeframe, snapshot_id, allow_incomplete=True)
        audits[(instrument_id, timeframe)] = audit_candle_grid(candles, calendar=calendar, trading_dates=dates, interval_minutes=TIMEFRAME_MINUTES[timeframe])
    if all(audit.passed for audit in audits.values()):
        store.finalize_snapshot(snapshot_id, status="VERIFIED")
    return audits