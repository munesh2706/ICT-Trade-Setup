from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from ict_engine.market_calendar import ExchangeCalendar, TradingSession
from ict_engine.models import Candle
from ict_engine.stock_live_refresh import refresh_current_session
from ict_engine.stock_storage import StockCandleStore
from ict_engine.stock_universe import Constituent, StockInstrument, UniverseSnapshot

IST = ZoneInfo("Asia/Kolkata")

class FakeFeed:
    def __init__(self, members):
        self.instruments = {
            m.symbol: StockInstrument(m.symbol, m.company_name, m.symbol+"-EQ",
                                      str(8000+i), "NSE", "nse_cm")
            for i,m in enumerate(members)
        }
        self.raw_responses = []
    def fetch_candles(self, symbol, timeframe, start, end):
        stamp = start
        candle = Candle(stamp, Decimal("100"), Decimal("101"), Decimal("99"),
                        Decimal("100"), Decimal("500"))
        self.raw_responses.append({
            "fetched_at": datetime.now(IST),
            "request_params": {
                "exchange":"NSE", "symboltoken":self.instruments[symbol].token,
                "interval":"ONE_MINUTE", "fromdate":start.strftime("%Y-%m-%d %H:%M"),
                "todate":end.strftime("%Y-%m-%d %H:%M"),
            },
            "payload":{"status":True,"data":[[stamp.isoformat(),"100","101","99","100","500"]]},
        })
        return [candle]

def setup(tmp_path):
    members=tuple(Constituent(f"SYM{i:02d}",f"Company {i}") for i in range(50))
    universe=UniverseSnapshot("universe-live",datetime.now(IST).isoformat(),"2026-10-30",
                              "nse-source","c"*64,members)
    session=TradingSession("NSE",date(2026,10,30),
        datetime(2026,10,30,9,15,tzinfo=IST),
        datetime(2026,10,30,9,17,tzinfo=IST),"test")
    calendar=ExchangeCalendar("NSE","Asia/Kolkata",date(2026,10,30),date(2026,10,30),
                               [session],[],"test")
    return universe,calendar,StockCandleStore(tmp_path/"live.sqlite"),FakeFeed(members)

def test_live_refresh_verifies_each_stock_series_incrementally(tmp_path):
    universe,calendar,store,feed=setup(tmp_path)
    first=refresh_current_session(
        universe=universe,feed=feed,store=store,calendar=calendar,
        as_of=datetime(2026,10,30,9,16,tzinfo=IST),timeframes=["1m"],
    )
    assert first.total_series==50
    assert first.ready_series==50
    assert len(store.load_verified_candles("SYM00","1m"))==1

    second=refresh_current_session(
        universe=universe,feed=feed,store=store,calendar=calendar,
        as_of=datetime(2026,10,30,9,17,tzinfo=IST),timeframes=["1m"],
    )
    assert second.ready_series==50
    assert len(store.load_verified_candles("SYM00","1m"))==2
