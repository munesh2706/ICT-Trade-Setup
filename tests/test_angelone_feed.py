from datetime import datetime
from zoneinfo import ZoneInfo
from decimal import Decimal as D
import pytest
from ict_engine.angelone_feed import AngelOneFeedError, AngelOneHistoricalFeed
from ict_engine.instruments import INDEX_INSTRUMENTS

IST = ZoneInfo("Asia/Kolkata")

class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []
    def getCandleData(self, params):
        self.calls.append(params)
        return self.payload

def feed(payload):
    return AngelOneHistoricalFeed(FakeClient(payload), INDEX_INSTRUMENTS, pace_seconds=0.34)

def test_fetch_candles_normalizes_decimal_ohlcv_and_uses_index_token():
    f = feed({"status": True, "data": [["2026-01-01T09:15:00+05:30", "100", "102", "99", "101", "50"]]})
    bars = f.fetch_candles("NIFTY", "1m", datetime(2026,1,1,9,15,tzinfo=IST), datetime(2026,1,1,10,0,tzinfo=IST))
    assert len(bars) == 1
    assert bars[0].close == D("101")
    assert f._client.calls[0]["symboltoken"] == "99926000"
    assert f._client.calls[0]["exchange"] == "NSE"

def test_rejects_duplicate_or_out_of_order_provider_rows():
    data = [["2026-01-01T09:16:00+05:30", "100", "102", "99", "101", "50"], ["2026-01-01T09:15:00+05:30", "100", "102", "99", "101", "50"]]
    f = feed({"status": True, "data": data})
    with pytest.raises(AngelOneFeedError):
        f.fetch_candles("NIFTY", "1m", datetime(2026,1,1,9,15,tzinfo=IST), datetime(2026,1,1,10,0,tzinfo=IST))

def test_rejects_invalid_ohlc():
    f = feed({"status": True, "data": [["2026-01-01T09:15:00+05:30", "100", "98", "99", "101", "50"]]})
    with pytest.raises(AngelOneFeedError):
        f.fetch_candles("NIFTY", "1m", datetime(2026,1,1,9,15,tzinfo=IST), datetime(2026,1,1,10,0,tzinfo=IST))

def test_rejects_unknown_instrument_and_unsupported_interval():
    f = feed({"status": True, "data": []})
    with pytest.raises(ValueError):
        f.fetch_candles("RELIANCE", "1m", datetime(2026,1,1,9,15,tzinfo=IST), datetime(2026,1,1,10,0,tzinfo=IST))
    with pytest.raises(ValueError):
        f.fetch_candles("NIFTY", "2m", datetime(2026,1,1,9,15,tzinfo=IST), datetime(2026,1,1,10,0,tzinfo=IST))

def test_rejects_provider_failure_without_retry():
    f = feed({"status": False, "errorcode": "AB1004", "data": None})
    with pytest.raises(AngelOneFeedError):
        f.fetch_candles("NIFTY", "1m", datetime(2026,1,1,9,15,tzinfo=IST), datetime(2026,1,1,10,0,tzinfo=IST))
    assert len(f._client.calls) == 1
def test_long_range_is_split_at_documented_one_minute_limit():
    f = feed({"status": True, "data": []})
    start = datetime(2026,1,1,9,15,tzinfo=IST)
    end = datetime(2026,2,1,9,15,tzinfo=IST)
    assert f.fetch_range("NIFTY", "1m", start, end) == []
    assert len(f._client.calls) == 2
    assert f._client.calls[0]["todate"] == "2026-01-31 09:15"
    assert f._client.calls[1]["fromdate"] == "2026-01-31 09:15"


def test_single_request_over_documented_limit_rejected():
    f = feed({"status": True, "data": []})
    with pytest.raises(ValueError):
        f.fetch_candles("NIFTY", "1m", datetime(2026,1,1,9,15,tzinfo=IST), datetime(2026,2,1,9,15,tzinfo=IST))


def test_historical_rate_pacing_cannot_exceed_documented_limit():
    with pytest.raises(ValueError):
        AngelOneHistoricalFeed(FakeClient({"status": True, "data": []}), INDEX_INSTRUMENTS, pace_seconds=0.2)
