"""Explicit exchange-session calendar; no weekday/holiday guessing."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable
from zoneinfo import ZoneInfo

class CalendarCoverageError(RuntimeError):
    pass

@dataclass(frozen=True, slots=True)
class TradingSession:
    exchange: str
    trading_date: date
    open_at: datetime
    close_at: datetime
    source: str
    continuous_close_at: datetime | None = None
    continuous_close_source: str | None = None
    def __post_init__(self):
        if self.open_at.tzinfo is None or self.close_at.tzinfo is None:
            raise ValueError("session boundaries must be timezone-aware")
        if self.close_at <= self.open_at:
            raise ValueError("session close must be after open")
        if not self.source.strip():
            raise ValueError("session source is required")
        if self.continuous_close_at is not None:
            if self.continuous_close_at.tzinfo is None:
                raise ValueError("continuous close must be timezone-aware")
            if not self.open_at < self.continuous_close_at <= self.close_at:
                raise ValueError("continuous close must be after open and no later than session close")
            if not self.continuous_close_source or not self.continuous_close_source.strip():
                raise ValueError("continuous close source is required when configured")
        elif self.continuous_close_source is not None:
            raise ValueError("continuous close source cannot be set without a continuous close")

class ExchangeCalendar:
    def __init__(self, exchange: str, timezone_name: str, coverage_start: date, coverage_end: date, sessions: Iterable[TradingSession], closed_dates: Iterable[date], source: str):
        if coverage_end < coverage_start:
            raise ValueError("calendar coverage end precedes start")
        if not source.strip():
            raise ValueError("calendar source is required")
        self.exchange = exchange.upper()
        self.timezone = ZoneInfo(timezone_name)
        self.coverage_start = coverage_start
        self.coverage_end = coverage_end
        self.source = source
        session_list = list(sessions)
        self._sessions = {s.trading_date: s for s in session_list}
        self._closed = set(closed_dates)
        if len(self._sessions) != len(session_list):
            raise ValueError("duplicate session dates")
        if set(self._sessions) & self._closed:
            raise ValueError("date cannot be both open and closed")
        for day, session in self._sessions.items():
            if session.exchange.upper() != self.exchange:
                raise ValueError("session exchange mismatch")
            if session.open_at.astimezone(self.timezone).date() != day or session.close_at.astimezone(self.timezone).date() != day:
                raise ValueError("session boundaries do not map to trading date in calendar timezone")
            if session.continuous_close_at is not None and session.continuous_close_at.astimezone(self.timezone).date() != day:
                raise ValueError("continuous close does not map to trading date in calendar timezone")
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

    def expected_candle_starts(self, trading_date: date, interval_minutes: int, *, cas_eligible: bool = False) -> list[datetime]:
        if interval_minutes < 1:
            raise ValueError("interval_minutes must be positive")
        session = self.session_for(trading_date)
        if session is None:
            return []
        step = timedelta(minutes=interval_minutes)
        starts = []
        cursor = session.open_at.astimezone(self.timezone)
        close_boundary = session.continuous_close_at if cas_eligible and session.continuous_close_at is not None else session.close_at
        close = close_boundary.astimezone(self.timezone)
        while cursor + step <= close:
            starts.append(cursor)
            cursor += step
        return starts


    def sessions_between(self, start: date, end: date) -> tuple[TradingSession, ...]:
        """Return explicitly configured sessions in an inclusive date range.

        Both bounds must be inside calendar coverage. Closed dates are omitted;
        unknown dates raise through session_for rather than being inferred.
        """
        if end < start:
            raise ValueError("end date must not precede start date")
        if start < self.coverage_start or end > self.coverage_end:
            raise CalendarCoverageError("requested range is outside calendar coverage")
        result = []
        cursor = start
        while cursor <= end:
            session = self.session_for(cursor)
            if session is not None:
                result.append(session)
            cursor += timedelta(days=1)
        return tuple(result)

    def trading_dates_between(self, start: date, end: date) -> tuple[date, ...]:
        """Return open-session dates in an inclusive, fully covered range."""
        return tuple(session.trading_date for session in self.sessions_between(start, end))

    def is_open_at(self, timestamp: datetime) -> bool:
        if timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        local_timestamp = timestamp.astimezone(self.timezone)
        session = self.session_for(local_timestamp.date())
        return bool(session and session.open_at.astimezone(self.timezone) <= local_timestamp < session.close_at.astimezone(self.timezone))

    def is_continuous_trading_at(self, timestamp: datetime, *, cas_eligible: bool = False) -> bool:
        """Return whether a timestamp falls inside continuous trading, excluding CAS."""
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        local = timestamp.astimezone(self.timezone)
        session = self.session_for(local.date())
        if session is None:
            return False
        close_boundary = session.continuous_close_at if cas_eligible and session.continuous_close_at is not None else session.close_at
        return session.open_at.astimezone(self.timezone) <= local < close_boundary.astimezone(self.timezone)
