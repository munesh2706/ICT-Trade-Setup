from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from scripts.run_nifty50_session import _merge_quote_sources

IST = ZoneInfo("Asia/Kolkata")

def test_quote_merge_prefers_fresh_websocket_tick_over_stale_full_quote():
    now = datetime(2026,10,30,10,0,tzinfo=IST)
    fallback = SimpleNamespace(
        symbol="RELIANCE", ltp=Decimal("100"), exchange_timestamp=now-timedelta(seconds=180),
        received_at=now, age_seconds=180.0, stale=True,
    )
    tick = SimpleNamespace(
        symbol="RELIANCE", ltp=Decimal("101"), exchange_timestamp=now-timedelta(seconds=2),
        received_at=now, age_seconds=None, stale=None,
    )
    batch = SimpleNamespace(quotes=(fallback,))
    result = _merge_quote_sources({"RELIANCE":tick},batch)
    assert result["RELIANCE"]["ltp"] == "101"
    assert result["RELIANCE"]["source"] == "Angel One WebSocket V2"
    assert result["RELIANCE"]["stale"] is False

def test_quote_merge_uses_fresh_full_quote_when_websocket_tick_is_stale():
    now = datetime(2026,10,30,10,0,tzinfo=IST)
    fallback = SimpleNamespace(
        symbol="RELIANCE", ltp=Decimal("102"), exchange_timestamp=now-timedelta(seconds=3),
        received_at=now, age_seconds=3.0, stale=False,
    )
    tick = SimpleNamespace(
        symbol="RELIANCE", ltp=Decimal("99"), exchange_timestamp=now-timedelta(seconds=150),
        received_at=now, age_seconds=None, stale=None,
    )
    batch = SimpleNamespace(quotes=(fallback,))
    result = _merge_quote_sources({"RELIANCE":tick},batch)
    assert result["RELIANCE"]["ltp"] == "102"
    assert result["RELIANCE"]["source"] == "Angel One SmartAPI FULL quote"
    assert result["RELIANCE"]["stale"] is False

def test_quote_merge_keeps_stale_state_when_both_sources_are_stale():
    now = datetime(2026,10,30,10,0,tzinfo=IST)
    fallback = SimpleNamespace(
        symbol="RELIANCE", ltp=Decimal("100"), exchange_timestamp=now-timedelta(seconds=300),
        received_at=now, age_seconds=300.0, stale=True,
    )
    tick = SimpleNamespace(
        symbol="RELIANCE", ltp=Decimal("101"), exchange_timestamp=now-timedelta(seconds=120),
        received_at=now, age_seconds=None, stale=None,
    )
    result = _merge_quote_sources({"RELIANCE":tick},SimpleNamespace(quotes=(fallback,)))
    assert result["RELIANCE"]["ltp"] == "101"
    assert result["RELIANCE"]["stale"] is True


def test_quote_merge_selects_newest_exchange_timestamp_when_both_fresh():
    now = datetime(2026,10,30,10,0,tzinfo=IST)
    fallback = SimpleNamespace(
        symbol="RELIANCE", ltp=Decimal("102"), exchange_timestamp=now-timedelta(seconds=5),
        received_at=now, age_seconds=5.0, stale=False,
    )
    tick = SimpleNamespace(
        symbol="RELIANCE", ltp=Decimal("103"), exchange_timestamp=now-timedelta(seconds=1),
        received_at=now, age_seconds=None, stale=None,
    )
    result = _merge_quote_sources({"RELIANCE":tick},SimpleNamespace(quotes=(fallback,)))
    assert result["RELIANCE"]["ltp"] == "103"
    assert result["RELIANCE"]["source"] == "Angel One WebSocket V2"
