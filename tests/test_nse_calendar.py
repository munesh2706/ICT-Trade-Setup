from datetime import date
from pathlib import Path

from scripts.reconcile_nifty50_history import load_calendar

def test_bundled_nse_calendar_covers_special_budget_session_and_holidays():
    root = Path(__file__).resolve().parents[1]
    calendar = load_calendar(root / "data/calendars/nse_2026_through_2026-11-07.json")
    assert calendar.session_for(date(2026, 2, 1)) is not None
    assert calendar.session_for(date(2026, 1, 15)) is None
    assert calendar.session_for(date(2026, 10, 31)) is None
    assert calendar.session_for(date(2026, 11, 10)) is not None
    assert len(calendar.expected_candle_starts(date(2026, 2, 1), 1)) == 375

def test_bundled_nse_calendar_fails_closed_beyond_coverage():
    root = Path(__file__).resolve().parents[1]
    calendar = load_calendar(root / "data/calendars/nse_2026_through_2026-11-07.json")
    import pytest
    from ict_engine.market_calendar import CalendarCoverageError
    with pytest.raises(CalendarCoverageError):
        calendar.session_for(date(2026, 11, 2))
