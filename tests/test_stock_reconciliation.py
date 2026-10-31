from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from ict_engine.market_calendar import ExchangeCalendar, TradingSession
from ict_engine.models import Candle
from ict_engine.stock_reconciliation import reconcile_universe
from ict_engine.stock_storage import StockCandleStore
from ict_engine.stock_universe import Constituent, StockInstrument, UniverseSnapshot

IST = ZoneInfo("Asia/Kolkata")

class FakeFeed:
    def __init__(self, members, *, provide_gap=True):
        self.instruments = {
            m.symbol: StockInstrument(m.symbol, m.company_name, m.symbol + "-EQ",
                                      str(i + 100), "NSE", "nse_cm")
            for i, m in enumerate(members)
        }
        self.raw_responses = []
        self.provide_gap = provide_gap

    def fetch_candles(self, symbol, timeframe, start, end):
        stamp = datetime(2026, 10, 30, 9, 16, tzinfo=IST)
        candle = Candle(stamp, Decimal("100"), Decimal("101"), Decimal("99"),
                        Decimal("100"), Decimal("500"))
        rows = [candle] if self.provide_gap and start <= stamp < end else []
        self.raw_responses.append({
            "fetched_at": datetime.now(IST),
            "request_params": {
                "exchange": "NSE", "symboltoken": self.instruments[symbol].token,
                "interval": "ONE_MINUTE", "fromdate": start.strftime("%Y-%m-%d %H:%M"),
                "todate": end.strftime("%Y-%m-%d %H:%M"),
            },
            "payload": {"status": True, "data": []},
        })
        return rows

def setup(tmp_path, provide_gap=True):
    members = tuple(Constituent(f"SYM{i:02d}", f"Company {i}") for i in range(50))
    universe = UniverseSnapshot("universe-test", datetime.now(IST).isoformat(),
                                "2026-10-30", "https://example.invalid/manifest.csv",
                                "a" * 64, members)
    session = TradingSession(
        "NSE", date(2026, 10, 30),
        datetime(2026, 10, 30, 9, 15, tzinfo=IST),
        datetime(2026, 10, 30, 9, 17, tzinfo=IST),
        "test fixture only",
    )
    calendar = ExchangeCalendar(
        "NSE", "Asia/Kolkata", date(2026, 10, 30), date(2026, 10, 30),
        [session], [], "test fixture only",
    )
    store = StockCandleStore(tmp_path / "stocks.sqlite")
    store.create_snapshot("base", universe.snapshot_id, "fixture base")
    first = Candle(datetime(2026, 10, 30, 9, 15, tzinfo=IST),
                   Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("500"))
    second = Candle(datetime(2026, 10, 30, 9, 16, tzinfo=IST),
                    Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("500"))
    for i, member in enumerate(members):
        candles = [first] if i == 0 else [first, second]
        store.store_candles("base", member.symbol, "1m", str(i + 100), candles)
    store.finalize("base", "ACQUIRED")
    return universe, calendar, store, FakeFeed(members, provide_gap=provide_gap)

def test_reconciliation_backfills_missing_minute_before_verifying(tmp_path):
    universe, calendar, store, feed = setup(tmp_path)
    result = reconcile_universe(
        universe=universe, feed=feed, store=store, calendar=calendar,
        trading_dates=[date(2026, 10, 30)], timeframes=["1m"], max_passes=2,
    )
    assert result.verified is True
    assert result.total_missing == 0
    assert len(store.load_verified_candles("SYM00", "1m")) == 2
    assert store.snapshot_status("base") == "VERIFIED"

def test_unresolved_gap_keeps_signal_data_unverified(tmp_path):
    universe, calendar, store, feed = setup(tmp_path, provide_gap=False)
    result = reconcile_universe(
        universe=universe, feed=feed, store=store, calendar=calendar,
        trading_dates=[date(2026, 10, 30)], timeframes=["1m"], max_passes=2,
    )
    assert result.verified is False
    assert result.total_missing == 1
    assert store.snapshot_status("base") == "ACQUIRED"
    assert store.load_verified_candles("SYM00", "1m") == []
