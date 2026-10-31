from datetime import datetime, timezone
from decimal import Decimal

import pytest

from ict_engine.stock_feed import AngelOneStockFeed, StockFeedError

def test_websocket_tick_normalizes_paise_and_exchange_timestamp():
    epoch_ms = int(datetime(2026, 10, 30, 9, 20, tzinfo=timezone.utc).timestamp() * 1000)
    tick = AngelOneStockFeed.normalize_stream_tick({
        "token": "12345",
        "exchange_type": 1,
        "subscription_mode": 2,
        "sequence_number": 77,
        "exchange_timestamp": epoch_ms,
        "last_traded_price": 123456,
        "volume_trade_for_the_day": 9000,
    }, {"12345": "RELIANCE"})
    assert tick.symbol == "RELIANCE"
    assert tick.ltp == Decimal("1234.56")
    assert tick.sequence_number == 77
    assert tick.cumulative_day_volume == 9000

def test_websocket_tick_rejects_unknown_tokens_and_wrong_exchange():
    with pytest.raises(StockFeedError):
        AngelOneStockFeed.normalize_stream_tick({
            "token": "99999", "exchange_type": 1, "last_traded_price": 10000,
            "exchange_timestamp": 1793352000000,
        }, {"12345": "RELIANCE"})
    with pytest.raises(StockFeedError):
        AngelOneStockFeed.normalize_stream_tick({
            "token": "12345", "exchange_type": 2, "last_traded_price": 10000,
            "exchange_timestamp": 1793352000000,
        }, {"12345": "RELIANCE"})
