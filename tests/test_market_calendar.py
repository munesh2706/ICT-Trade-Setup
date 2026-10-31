from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
import pytest
from ict_engine.market_calendar import CalendarCoverageError, ExchangeCalendar, TradingSession

IST = ZoneInfo("Asia/Kolkata")
DAY = date(2026,1,2)

def regular_session(day=DAY):
    return TradingSession("NSE", day, datetime.combine(day, datetime.min.time(), IST).replace(hour=9, minute=15), datetime.combine(day, datetime.min.time(), IST).replace(hour=15, minute=30), "official exchange calendar")

def calendar(sessions=None, closed=None):
    return ExchangeCalendar("NSE", "Asia/Kolkata", date(2026,1,1), date(2026,12,31), sessions if sessions is not None else [regular_session()], closed if closed is not None else [date(2026,1,1)], "official calendar snapshot")

def test_regular_session_expected_grids():
    cal = calendar()
    assert len(cal.expected_candle_starts(DAY, 1)) == 375
    assert len(cal.expected_candle_starts(DAY, 5)) == 75
    assert len(cal.expected_candle_starts(DAY, 15)) == 25
    assert len(cal.expected_candle_starts(DAY, 30)) == 12

def test_closed_date_has_no_expected_candles():
    assert calendar().expected_candle_starts(date(2026,1,1), 1) == []

def test_unlisted_date_is_unknown_not_assumed_holiday_or_weekday():
    with pytest.raises(CalendarCoverageError):
        calendar().session_for(date(2026,1,3))

def test_timezone_aware_utc_timestamp_checked_in_exchange_timezone():
    cal = calendar()
    at = datetime(2026,1,2,4,0,tzinfo=timezone.utc)
    assert cal.is_open_at(at)
    assert not cal.is_open_at(datetime(2026,1,2,10,0,tzinfo=timezone.utc))

def test_special_shortened_session_has_shorter_grid():
    short = TradingSession("NSE", DAY, datetime(2026,1,2,9,15,tzinfo=IST), datetime(2026,1,2,12,30,tzinfo=IST), "official special session")
    assert len(calendar([short]).expected_candle_starts(DAY, 1)) == 195

def test_duplicate_session_dates_rejected():
    with pytest.raises(ValueError):
        calendar([regular_session(), regular_session()])

def test_date_cannot_be_both_open_and_closed():
    with pytest.raises(ValueError):
        calendar([regular_session()], [DAY])

def test_cas_eligible_cash_equity_uses_continuous_close_not_auction_close():
    continuous_close = datetime(2026, 10, 30, 15, 15, tzinfo=IST)
    session = TradingSession(
        "NSE", date(2026, 10, 30),
        datetime(2026, 10, 30, 9, 15, tzinfo=IST),
        datetime(2026, 10, 30, 15, 30, tzinfo=IST),
        "official NSE session",
        continuous_close,
        "NSE CAS effective 2026-08-03; F&O cash equities continuous session ends 15:15 IST",
    )
    cal = ExchangeCalendar(
        "NSE", "Asia/Kolkata", date(2026, 10, 30), date(2026, 10, 30),
        [session], [], "NSE calendar with CAS boundary",
    )
    assert len(cal.expected_candle_starts(date(2026, 10, 30), 1)) == 375
    assert len(cal.expected_candle_starts(date(2026, 10, 30), 5)) == 75
    assert len(cal.expected_candle_starts(date(2026, 10, 30), 15)) == 25
    assert len(cal.expected_candle_starts(date(2026, 10, 30), 1, cas_eligible=True)) == 360
    assert len(cal.expected_candle_starts(date(2026, 10, 30), 5, cas_eligible=True)) == 72
    assert len(cal.expected_candle_starts(date(2026, 10, 30), 15, cas_eligible=True)) == 24
    assert cal.expected_candle_starts(date(2026, 10, 30), 1, cas_eligible=True)[-1] == continuous_close.replace(minute=14)
    assert cal.is_continuous_trading_at(datetime(2026, 10, 30, 15, 14, tzinfo=IST), cas_eligible=True)
    assert not cal.is_continuous_trading_at(datetime(2026, 10, 30, 15, 15, tzinfo=IST), cas_eligible=True)
    assert cal.is_continuous_trading_at(datetime(2026, 10, 30, 15, 28, tzinfo=IST), cas_eligible=False)


def test_cas_boundary_requires_timezone_aware_source_and_valid_order():
    with pytest.raises(ValueError, match="continuous close must be timezone-aware"):
        TradingSession(
            "NSE", date(2026, 10, 30),
            datetime(2026, 10, 30, 9, 15, tzinfo=IST),
            datetime(2026, 10, 30, 15, 30, tzinfo=IST),
            "official",
            datetime(2026, 10, 30, 15, 15),
            "CAS source",
        )
