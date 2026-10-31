from datetime import date, datetime, timedelta
from decimal import Decimal as D
from zoneinfo import ZoneInfo
import pytest
from ict_engine.data_audit import audit_candle_grid, verify_snapshot
from ict_engine.market_calendar import ExchangeCalendar, TradingSession
from ict_engine.models import Candle
from ict_engine.storage import CandleStore

IST = ZoneInfo("Asia/Kolkata")
DAY = date(2026,1,2)
OPEN = datetime(2026,1,2,9,15,tzinfo=IST)
CLOSE = datetime(2026,1,2,9,20,tzinfo=IST)

def make_calendar():
    session = TradingSession("NSE", DAY, OPEN, CLOSE, "official calendar test")
    return ExchangeCalendar("NSE", "Asia/Kolkata", DAY, DAY, [session], [], "calendar fixture")

def bars(count):
    return [Candle(OPEN+timedelta(minutes=i), D("100"), D("102"), D("99"), D("101"), D("0")) for i in range(count)]

def test_complete_grid_verifies_snapshot(tmp_path):
    store = CandleStore(tmp_path / "data.sqlite")
    store.create_snapshot("s1")
    store.store_candles("NIFTY", "1m", "s1", "ANGEL_HISTORICAL", bars(5))
    store.finalize_snapshot("s1", status="ACQUIRED")
    audits = verify_snapshot(store, "s1", {("NIFTY", "1m"): (make_calendar(), [DAY])})
    assert audits[("NIFTY", "1m")].passed
    assert store.snapshot_status("s1") == "VERIFIED"

def test_missing_bar_prevents_snapshot_verification(tmp_path):
    store = CandleStore(tmp_path / "data.sqlite")
    store.create_snapshot("s1")
    store.store_candles("NIFTY", "1m", "s1", "ANGEL_HISTORICAL", bars(4))
    store.finalize_snapshot("s1", status="ACQUIRED")
    audits = verify_snapshot(store, "s1", {("NIFTY", "1m"): (make_calendar(), [DAY])})
    assert len(audits[("NIFTY", "1m")].missing) == 1
    assert store.snapshot_status("s1") == "ACQUIRED"

def test_unexpected_out_of_session_bar_reported(tmp_path):
    store = CandleStore(tmp_path / "data.sqlite")
    store.create_snapshot("s1")
    outside = Candle(CLOSE, D("100"), D("102"), D("99"), D("101"), D("0"))
    store.store_candles("NIFTY", "1m", "s1", "ANGEL_HISTORICAL", [outside])
    store.finalize_snapshot("s1", status="ACQUIRED")
    audit = audit_candle_grid([outside], calendar=make_calendar(), trading_dates=[DAY], interval_minutes=1)
    assert len(audit.unexpected) == 1

def test_daily_interval_uses_one_bar_per_session():
    session = TradingSession("NSE", DAY, OPEN, datetime(2026,1,2,15,30,tzinfo=IST), "official calendar test")
    cal = ExchangeCalendar("NSE", "Asia/Kolkata", DAY, DAY, [session], [], "calendar fixture")
    daily = Candle(OPEN, D("100"), D("102"), D("99"), D("101"), D("0"))
    audit = audit_candle_grid([daily], calendar=cal, trading_dates=[DAY], interval_minutes=1440)
    assert audit.passed

def test_unverified_snapshot_is_not_backtest_readable(tmp_path):
    store = CandleStore(tmp_path / "data.sqlite")
    store.create_snapshot("s1")
    store.store_candles("NIFTY", "1m", "s1", "ANGEL_HISTORICAL", bars(5))
    store.finalize_snapshot("s1", status="ACQUIRED")
    with pytest.raises(ValueError):
        store.load_candles("NIFTY", "1m", "s1")