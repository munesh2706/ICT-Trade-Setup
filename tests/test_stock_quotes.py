from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ict_engine.stock_feed import AngelOneStockFeed
from ict_engine.stock_universe import StockInstrument

IST = ZoneInfo("Asia/Kolkata")

class FakeQuoteClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def getMarketData(self, mode, exchange_tokens):
        self.calls.append((mode, exchange_tokens))
        return self.payload

def make_feed(timestamp):
    instruments = {
        f"SYM{i:02d}": StockInstrument(
            f"SYM{i:02d}", f"Company {i}", f"SYM{i:02d}-EQ",
            str(5000 + i), "NSE", "nse_cm",
        )
        for i in range(50)
    }
    rows = [{
        "symbolToken": str(5000 + i),
        "tradingSymbol": f"SYM{i:02d}-EQ",
        "ltp": "100.25",
        "exchFeedTime": timestamp,
    } for i in range(50)]
    client = FakeQuoteClient({"status": True, "data": {"fetched": rows, "unfetched": []}})
    return AngelOneStockFeed(client, instruments), client

def test_full_quote_snapshot_resolves_all_50_and_checks_freshness():
    stamp = datetime.now(IST).strftime("%d-%b-%Y %H:%M:%S")
    feed, client = make_feed(stamp)
    result = feed.fetch_full_quotes(max_age_seconds=90)
    assert result.complete
    assert len(result.quotes) == 50
    assert result.quotes[0].ltp.as_tuple().exponent == -2
    assert client.calls[0][0] == "FULL"
    assert len(client.calls[0][1]["NSE"]) == 50

def test_full_quote_snapshot_marks_stale_exchange_timestamps():
    stamp = (datetime.now(IST) - timedelta(minutes=5)).strftime("%d-%b-%Y %H:%M:%S")
    feed, _ = make_feed(stamp)
    result = feed.fetch_full_quotes(max_age_seconds=90)
    assert len(result.stale_symbols) == 50
    assert result.complete is False
