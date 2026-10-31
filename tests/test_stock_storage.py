from datetime import datetime, timezone
from decimal import Decimal

import pytest

from ict_engine.models import Candle
from ict_engine.stock_storage import StockCandleStore, StockStoreError

def candle(minute, close="100"):
    stamp = datetime(2026, 10, 30, 9, minute, tzinfo=timezone.utc)
    return Candle(stamp, Decimal(close), Decimal(close), Decimal(close), Decimal(close), Decimal("1"))

def test_stock_store_immutable_snapshots_and_status_gate(tmp_path):
    store = StockCandleStore(tmp_path / "stocks.sqlite")
    store.create_snapshot("snap1", "universe1")
    store.store_candles("snap1", "RELIANCE", "1m", "123", [candle(15)])
    assert store.load_verified_candles("RELIANCE", "1m") == []
    store.finalize("snap1", "ACQUIRED")
    assert len(store.load_reconciliation_candles("RELIANCE", "1m")) == 1
    assert store.load_verified_candles("RELIANCE", "1m") == []
    store.mark_universe_snapshots_verified("universe1")
    assert len(store.load_verified_candles("RELIANCE", "1m")) == 1

def test_conflicting_same_snapshot_candle_is_rejected(tmp_path):
    store = StockCandleStore(tmp_path / "stocks.sqlite")
    store.create_snapshot("snap1", "universe1")
    store.store_candles("snap1", "RELIANCE", "1m", "123", [candle(15)])
    with pytest.raises(StockStoreError):
        store.store_candles("snap1", "RELIANCE", "1m", "123", [candle(15, "101")])
