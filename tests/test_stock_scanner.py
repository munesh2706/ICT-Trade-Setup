from datetime import date, datetime, timedelta
from decimal import Decimal as D
from zoneinfo import ZoneInfo

from ict_engine.market_calendar import ExchangeCalendar, TradingSession
from ict_engine.models import Candle
from ict_engine.stock_scanner import StockICTScanConfig, StockICTScanner
from ict_engine.stock_universe import Constituent, UniverseSnapshot

IST = ZoneInfo("Asia/Kolkata")

def candle(ts, o, h, l, close):
    return Candle(ts, D(str(o)), D(str(h)), D(str(l)), D(str(close)), D("100"))

def setup_data():
    members = tuple(Constituent(f"SYM{i:02d}", f"Company {i}") for i in range(50))
    universe = UniverseSnapshot("scan-universe", datetime.now(IST).isoformat(),
        "2026-10-30", "nse-source", "b" * 64, members)
    session = TradingSession("NSE", date(2026,10,30),
        datetime(2026,10,30,9,15,tzinfo=IST),
        datetime(2026,10,30,15,30,tzinfo=IST), "test fixture")
    calendar = ExchangeCalendar("NSE","Asia/Kolkata",date(2026,10,30),date(2026,10,30),
        [session], [], "test fixture")
    one = [candle(datetime(2026,10,30,9,15,tzinfo=IST)+timedelta(minutes=i),100,101,99,100)
           for i in range(45)]
    fifteen = [candle(datetime(2026,10,30,9,15,tzinfo=IST)+timedelta(minutes=15*i),100,101,99,100)
               for i in range(3)]
    pattern = [
        (9,10,8,9),(10,11,9,10),(9,10,7,8),(9,10.5,8,9),(11,12,9,11),
        (10,11,8,9),(12,13,10,12.5),(10,10.5,5.5,6),(6,9.5,6,8.5),
    ]
    five_pattern = [candle(datetime(2026,10,30,9,15,tzinfo=IST)+timedelta(minutes=5*i),*x)
                    for i,x in enumerate(pattern)]
    five_flat = [candle(datetime(2026,10,30,9,15,tzinfo=IST)+timedelta(minutes=5*i),100,101,99,100)
                 for i in range(9)]
    data = {}
    for i, member in enumerate(members):
        data[(member.symbol,"1m")] = one
        data[(member.symbol,"5m")] = five_pattern if i == 0 else five_flat
        data[(member.symbol,"15m")] = fifteen
    return universe, calendar, data

class FakeVerifiedStore:
    def __init__(self, data):
        self.data = data
        self.calls = []
    def load_verified_candles(self, symbol, timeframe, start=None, end=None, limit=None):
        self.calls.append((symbol, timeframe, end, limit))
        rows = list(self.data.get((symbol,timeframe), []))
        if start is not None:
            rows = [x for x in rows if x.timestamp >= start]
        if end is not None:
            rows = [x for x in rows if x.timestamp < end]
        return rows[-limit:] if limit is not None else rows

def test_scanner_emits_explainable_episode6_candidate_for_individual_stock():
    universe, calendar, data = setup_data()
    as_of = datetime(2026,10,30,10,0,tzinfo=IST)
    store = FakeVerifiedStore(data)
    report = StockICTScanner(StockICTScanConfig(
        enable_silver_bullet=False, pivot_left=1, pivot_right=1,
        displacement_min_body_to_range=D("0.5"),
        max_bars_after_sweep=3, max_bars_after_mss=3,
    )).scan_universe(
        universe=universe, store=store, calendar=calendar,
        scan_date=date(2026,10,30), as_of=as_of,
    )
    assert report.total_stocks == 50
    assert report.ready_stocks == 50
    assert len(report.signals) == 1
    signal = report.signals[0]
    assert signal.symbol == "SYM00"
    assert signal.model_id == "ICT_2022_Mentorship_Episode_6"
    assert signal.direction == "bearish"
    assert signal.status == "ENTRY_ARMED"
    assert signal.retest_time is None
    assert signal.entry_zone_lower < signal.entry_zone_upper
    assert len(signal.invalidation_references) == 2
    assert len(signal.context["additional_liquidity_sweeps"]) == 2
    assert len(store.calls) == 150
    assert all(call[2] == as_of for call in store.calls)

def test_scanner_blocks_stock_with_missing_current_session_candle():
    universe, calendar, data = setup_data()
    data[("SYM01","1m")] = data[("SYM01","1m")][:-1]
    report = StockICTScanner(StockICTScanConfig(
        enable_silver_bullet=False, pivot_left=1, pivot_right=1,
        displacement_min_body_to_range=D("0.5"),
        max_bars_after_sweep=3, max_bars_after_mss=3,
    )).scan_universe(
        universe=universe, store=FakeVerifiedStore(data), calendar=calendar,
        scan_date=date(2026,10,30),
        as_of=datetime(2026,10,30,10,0,tzinfo=IST),
    )
    status = next(x for x in report.stock_status if x.symbol == "SYM01")
    assert status.status == "DATA_NOT_READY"
    assert "1m=1" in status.reason
    assert report.ready_stocks == 49


def test_scanner_has_bounded_15m_context_history():
    config = StockICTScanConfig()
    assert config.max_15m_context_bars == 300

def test_scanner_rejects_non_positive_15m_context_history():
    import pytest
    with pytest.raises(ValueError, match="bar limits must be positive"):
        StockICTScanConfig(max_15m_context_bars=0)
