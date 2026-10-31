"""Explicit exchange-session calendar; no weekday/holiday guessing."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable

class CalendarCoverageError(RuntimeError):
    pass

@dataclass(frozen=True, slots=True)
class TradingSession:
    exchange: str
    trading_date: date
    open_at: datetime
    close_at: datetime
    source: str

    def __post_init__(self):
        if self.open_at.tzinfo is None or self.close_at.tzinfo is None:
            raise ValueError("session boundaries must be timezone-aware")
        if self.open_at.date() != self.trading_date or self.close_at.date() != self.trading_date:
            raise ValueError("session boundaries must use the trading date's local calendar date")
        if self.close_at <= self.open_at:
            raise ValueError("session close must be after open")
        if not self.source.strip():
            raise ValueError("session source is required")

class ExchangeCalendar:
    def __init__(self, exchange: str, coverage_start: date, coverage_end: date,
                 sessions: Iterable[TradingSession], closed_dates: Iterable[date], source: str):
        if coverage_end < coverage_start:
            raise ValueError("calendar coverage end precedes start")
        if not source.strip():
            raise ValueError("calendar source is required")
        self.exchange = exchange.upper()
        self.coverage_start = coverage_start
        self.coverage_end = coverage_end
        self.source = source
        self._sessions = {s.trading_date: s for s in sessions}
        self._closed = set(closed_dates)
        if len(self._sessions) != len(list(sessions)) if not isinstance(sessions, (list, tuple)) else False:
            raise ValueError("duplicate session dates")
        if set(self._sessions) & self._closed:
            raise ValueError("date cannot be both open and closed")
        for day, session in self._sessions.items():
            if session.exchange.upper() != self.exchange:
                raise ValueError("session exchange mismatch")
            if not coverage_start <= day <= coverage_end:
                raise ValueError("session outside calendar coverage")
        if any(not coverage_start <= day <= coverage_end for day in self._closed):
            raise ValueError("closed date outside calendar coverage")

    def session_for(self, trading_date: date) -> TradingSession | None:
        if not self.coverage_start <= trading_date <= self.coverage_end:
            raise CalendarCoverageError(f"{self.exchange} calendar does not cover {trading_date}")
        if trading_date in self._closed:
            return None
        if trading_date not in self._sessions:
            raise CalendarCoverageError(f"{self.exchange} calendar has no explicit entry for {trading_date}")
        return self._sessions[trading_date]

    def expected_candle_starts(self, trading_date: date, interval_minutes: int) -> list[datetime]:
        if interval_minutes < 1:
            raise ValueError("interval_minutes must be positive")
        session = self.session_for(trading_date)
        if session is None:
            return []
        step = timedelta(minutes=interval_minutes)
        starts = []
        cursor = session.open_at
        while cursor + step <= session.close_at:
            starts.append(cursor)
            cursor += step
        return starts

    def is_open_at(self, timestamp: datetime) -> bool:
        if timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        session = self.session_for(timestamp.date())
        return bool(session and session.open_at <= timestamp < session.close_at)