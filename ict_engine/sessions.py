"""DST-aware ICT Silver Bullet windows from the 2023 ICT lesson."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
INDIA = ZoneInfo("Asia/Kolkata")

@dataclass(frozen=True, slots=True)
class SessionWindow:
    name: str
    start: datetime
    end: datetime

_SILVER_BULLET_LOCAL = (
    ("london_open", time(3, 0), time(4, 0)),
    ("new_york_am", time(10, 0), time(11, 0)),
    ("new_york_pm", time(14, 0), time(15, 0)),
)

def silver_bullet_windows_ist(trading_date: date) -> tuple[SessionWindow, ...]:
    """Convert source-defined New York windows using IANA DST rules."""
    windows = []
    for name, start_time, end_time in _SILVER_BULLET_LOCAL:
        start_ny = datetime.combine(trading_date, start_time, tzinfo=NEW_YORK)
        end_ny = datetime.combine(trading_date, end_time, tzinfo=NEW_YORK)
        windows.append(SessionWindow(name, start_ny.astimezone(INDIA), end_ny.astimezone(INDIA)))
    return tuple(windows)

def containing_silver_bullet_window(timestamp: datetime) -> str | None:
    """Return the New York-local Silver Bullet window containing timestamp."""
    if timestamp.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    local_ny = timestamp.astimezone(NEW_YORK)
    for name, start_time, end_time in _SILVER_BULLET_LOCAL:
        start = datetime.combine(local_ny.date(), start_time, tzinfo=NEW_YORK)
        end = datetime.combine(local_ny.date(), end_time, tzinfo=NEW_YORK)
        if start <= local_ny < end:
            return name
    return None
