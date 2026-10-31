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