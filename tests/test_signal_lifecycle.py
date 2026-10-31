from datetime import datetime, timedelta, timezone
import pytest
from ict_engine.signal_lifecycle import SignalAggregate, SignalEvent, SignalStatus

def event(name, minute, target):
    return SignalEvent(name, datetime(2026,1,1,9,15,tzinfo=timezone.utc)+timedelta(minutes=minute), target, name)

def aggregate():
    return SignalAggregate("sig-1", "ICT_2022_Mentorship_Episode_6", "NIFTY")

def test_valid_signal_lifecycle():
    s = aggregate()
    for e in [event("q",0,SignalStatus.QUALIFIED), event("a",1,SignalStatus.ENTRY_ARMED), event("f",2,SignalStatus.FILLED), event("o",2,SignalStatus.OPEN), event("c",3,SignalStatus.CLOSED)]:
        assert s.apply(e)
    assert s.status == SignalStatus.CLOSED

def test_duplicate_event_is_idempotent():
    s = aggregate()
    e = event("same",0,SignalStatus.QUALIFIED)
    assert s.apply(e)
    assert not s.apply(e)
    assert len(s.history) == 1

def test_invalid_transition_rejected():
    with pytest.raises(ValueError):
        aggregate().apply(event("bad",0,SignalStatus.FILLED))

def test_terminal_signal_cannot_reopen():
    s = aggregate()
    s.apply(event("q",0,SignalStatus.QUALIFIED))
    s.apply(event("x",1,SignalStatus.NO_TRADE))
    with pytest.raises(ValueError):
        s.apply(event("again",2,SignalStatus.QUALIFIED))

def test_out_of_order_events_rejected():
    s = aggregate()
    s.apply(event("q",2,SignalStatus.QUALIFIED))
    with pytest.raises(ValueError):
        s.apply(event("late",1,SignalStatus.ENTRY_ARMED))

def test_timezone_naive_event_rejected():
    s = aggregate()
    e = SignalEvent("naive", datetime(2026,1,1,9,15), SignalStatus.QUALIFIED, "reason")
    with pytest.raises(ValueError):
        s.apply(e)