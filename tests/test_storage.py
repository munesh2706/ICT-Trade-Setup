from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import pytest
from ict_engine.models import Candle
from ict_engine.storage import CandleConflict, CandleStore

def candle(i, close="101"):
    return Candle(datetime(2026,1,1,9,15,tzinfo=timezone.utc)+timedelta(minutes=i), D("100"), D("102"), D("99"), D(close), D("10"))

def test_snapshot_storage_is_idempotent_and_round_trips(tmp_path):
    store = CandleStore(tmp_path / "ict.sqlite")
    store.create_snapshot("snapshot-a", description="test source capture")
    bars = [candle(0), candle(1)]
    assert store.store_candles("NIFTY_SPOT", "1m", "snapshot-a", "ANGEL_HISTORICAL", bars) == 2
    assert store.store_candles("NIFTY_SPOT", "1m", "snapshot-a", "ANGEL_HISTORICAL", bars) == 0
    store.finalize_snapshot("snapshot-a", status="ACQUIRED")
    store.finalize_snapshot("snapshot-a", status="VERIFIED")
    loaded = store.load_candles("NIFTY_SPOT", "1m", "snapshot-a")
    assert loaded == bars

def test_conflicting_data_cannot_overwrite_same_snapshot(tmp_path):
    store = CandleStore(tmp_path / "ict.sqlite")
    store.create_snapshot("snapshot-a")
    store.store_candles("NIFTY_SPOT", "1m", "snapshot-a", "ANGEL_HISTORICAL", [candle(0)])
    with pytest.raises(CandleConflict):
        store.store_candles("NIFTY_SPOT", "1m", "snapshot-a", "ANGEL_HISTORICAL", [candle(0, "100.5")])

def test_provider_revision_uses_separate_snapshot(tmp_path):
    store = CandleStore(tmp_path / "ict.sqlite")
    store.create_snapshot("snapshot-a")
    store.create_snapshot("snapshot-b")
    store.store_candles("NIFTY_SPOT", "1m", "snapshot-a", "ANGEL_HISTORICAL", [candle(0, "101")])
    store.store_candles("NIFTY_SPOT", "1m", "snapshot-b", "ANGEL_HISTORICAL", [candle(0, "100.5")])
    store.finalize_snapshot("snapshot-a", status="ACQUIRED")
    store.finalize_snapshot("snapshot-a", status="VERIFIED")
    store.finalize_snapshot("snapshot-b", status="ACQUIRED")
    store.finalize_snapshot("snapshot-b", status="VERIFIED")
    assert store.load_candles("NIFTY_SPOT", "1m", "snapshot-a")[0].close == D("101")
    assert store.load_candles("NIFTY_SPOT", "1m", "snapshot-b")[0].close == D("100.5")

def test_unsorted_batch_rejected(tmp_path):
    store = CandleStore(tmp_path / "ict.sqlite")
    store.create_snapshot("snapshot-a")
    with pytest.raises(ValueError):
        store.store_candles("NIFTY_SPOT", "1m", "snapshot-a", "ANGEL_HISTORICAL", [candle(1), candle(0)])

def test_unknown_snapshot_rejected(tmp_path):
    store = CandleStore(tmp_path / "ict.sqlite")
    with pytest.raises(ValueError):
        store.store_candles("NIFTY_SPOT", "1m", "missing", "ANGEL_HISTORICAL", [candle(0)])
def test_incomplete_or_failed_snapshot_cannot_be_loaded_by_backtest(tmp_path):
    store = CandleStore(tmp_path / "ict.sqlite")
    store.create_snapshot("open-snapshot")
    with pytest.raises(ValueError):
        store.load_candles("NIFTY_SPOT", "1m", "open-snapshot")
    store.finalize_snapshot("open-snapshot", status="FAILED")
    with pytest.raises(ValueError):
        store.load_candles("NIFTY_SPOT", "1m", "open-snapshot")


def test_finalized_snapshot_is_immutable(tmp_path):
    store = CandleStore(tmp_path / "ict.sqlite")
    store.create_snapshot("snapshot-a")
    store.finalize_snapshot("snapshot-a", status="ACQUIRED")
    store.finalize_snapshot("snapshot-a", status="VERIFIED")
    with pytest.raises(ValueError):
        store.store_candles("NIFTY_SPOT", "1m", "snapshot-a", "ANGEL_HISTORICAL", [candle(0)])

def test_acquired_snapshot_requires_audit_before_backtest_read(tmp_path):
    store = CandleStore(tmp_path / "ict.sqlite")
    store.create_snapshot("snapshot-a")
    store.store_candles("NIFTY_SPOT", "1m", "snapshot-a", "ANGEL_HISTORICAL", [candle(0)])
    store.finalize_snapshot("snapshot-a", status="ACQUIRED")
    with pytest.raises(ValueError):
        store.load_candles("NIFTY_SPOT", "1m", "snapshot-a")
    store.finalize_snapshot("snapshot-a", status="VERIFIED")
    assert len(store.load_candles("NIFTY_SPOT", "1m", "snapshot-a")) == 1

def test_raw_provider_response_is_retained_and_idempotent(tmp_path):
    store = CandleStore(tmp_path / "ict.sqlite")
    store.create_snapshot("snapshot-a")
    fetched = datetime(2026,1,1,10,0,tzinfo=timezone.utc)
    request = {"exchange": "NSE", "symboltoken": "99926000", "interval": "ONE_MINUTE", "fromdate": "2026-01-01 09:15", "todate": "2026-01-01 09:30"}
    payload = {"status": True, "data": [["2026-01-01T09:15:00+05:30", 100, 102, 99, 101, 0]]}
    store.store_raw_batch("snapshot-a", 0, "NIFTY", "1m", fetched, request, payload)
    store.store_raw_batch("snapshot-a", 0, "NIFTY", "1m", fetched, request, payload)
    batches = store.load_raw_batches("snapshot-a")
    assert len(batches) == 1
    assert batches[0]["payload"] == payload
    assert batches[0]["request"]["symboltoken"] == "99926000"


def test_raw_batch_rejects_auth_fields(tmp_path):
    store = CandleStore(tmp_path / "ict.sqlite")
    store.create_snapshot("snapshot-a")
    with pytest.raises(ValueError):
        store.store_raw_batch("snapshot-a", 0, "NIFTY", "1m", datetime.now(timezone.utc), {"Authorization": "secret"}, {"status": True})
