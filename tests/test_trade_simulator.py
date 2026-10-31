from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import pytest
from ict_engine.models import Candle
from ict_engine.trade_simulator import PaperPosition, process_position_bar

def candle(minute, o, h, l, c):
    return Candle(datetime(2026,1,1,9,15,tzinfo=timezone.utc)+timedelta(minutes=minute), D(str(o)), D(str(h)), D(str(l)), D(str(c)))

def long_position():
    return PaperPosition("p1", "NIFTY", "ICT_2022_Mentorship_Episode_6", "long", datetime(2026,1,1,9,15,tzinfo=timezone.utc), D("100"), D("90"), D("120"), D("2"), D("1"), D("1"), D("0.5"))

def test_entry_bar_is_not_used_for_exit_ordering():
    assert process_position_bar(long_position(), candle(0, 100, 125, 85, 110), bar_duration=timedelta(minutes=1)) is None

def test_long_stop_exit_calculates_net_pnl():
    result = process_position_bar(long_position(), candle(1, 95, 100, 88, 92), bar_duration=timedelta(minutes=1))
    assert result.reason == "stop_loss"
    assert result.exit_price == D("90")
    assert result.gross_pnl == D("-20")
    assert result.fees == D("2")
    assert result.slippage_cost == D("1.0")
    assert result.net_pnl == D("-23.0")

def test_gap_through_stop_uses_worse_open_for_pnl():
    result = process_position_bar(long_position(), candle(1, 85, 90, 80, 88), bar_duration=timedelta(minutes=1))
    assert result.gap_through_stop
    assert result.exit_price == D("85")
    assert result.net_pnl == D("-33.0")

def test_short_target_exit_calculates_net_pnl():
    position = PaperPosition("p2", "SENSEX", "ICT_SILVER_BULLET_2023", "short", datetime(2026,1,1,9,15,tzinfo=timezone.utc), D("100"), D("110"), D("90"), D("2"), D("1"), D("1"), D("0.5"))
    result = process_position_bar(position, candle(1, 95, 105, 85, 90), bar_duration=timedelta(minutes=1))
    assert result.reason == "take_profit"
    assert result.exit_price == D("90")
    assert result.net_pnl == D("17.0")

def test_no_barrier_touch_keeps_position_open():
    assert process_position_bar(long_position(), candle(1, 100, 110, 95, 105), bar_duration=timedelta(minutes=1)) is None

def test_invalid_position_geometry_rejected():
    with pytest.raises(ValueError):
        PaperPosition("bad", "NIFTY", "model", "long", datetime(2026,1,1,9,15,tzinfo=timezone.utc), D("100"), D("110"), D("120"), D("1"), D("1"), D("0"), D("0"))