from datetime import date, datetime
from zoneinfo import ZoneInfo
import pytest
from ict_engine.sessions import containing_silver_bullet_window, silver_bullet_windows_ist

def test_london_window_winter_dst_conversion():
    w = next(x for x in silver_bullet_windows_ist(date(2026, 1, 15)) if x.name == "london_open")
    assert w.start.strftime("%H:%M") == "13:30"
    assert w.end.strftime("%H:%M") == "14:30"

def test_london_window_summer_dst_conversion():
    w = next(x for x in silver_bullet_windows_ist(date(2026, 7, 15)) if x.name == "london_open")
    assert w.start.strftime("%H:%M") == "12:30"
    assert w.end.strftime("%H:%M") == "13:30"

def test_ny_am_and_pm_windows_outside_indian_cash_session():
    w = {x.name: x for x in silver_bullet_windows_ist(date(2026, 1, 15))}
    assert w["new_york_am"].start.hour >= 19
    assert w["new_york_pm"].start.date() > date(2026, 1, 15)

def test_window_lookup_respects_dst():
    winter = datetime(2026, 1, 15, 13, 45, tzinfo=ZoneInfo("Asia/Kolkata"))
    summer = datetime(2026, 7, 15, 12, 45, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert containing_silver_bullet_window(winter) == "london_open"
    assert containing_silver_bullet_window(summer) == "london_open"

def test_naive_timestamp_rejected():
    with pytest.raises(ValueError):
        containing_silver_bullet_window(datetime(2026, 1, 15, 13, 45))
