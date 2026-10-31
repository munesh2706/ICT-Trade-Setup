"""Model-neutral, auditable signal lifecycle state machine."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

class SignalStatus(str, Enum):
    WATCHING = "watching"
    QUALIFIED = "qualified"
    ENTRY_ARMED = "entry_armed"
    FILLED = "filled"
    OPEN = "open"
    CLOSED = "closed"
    NO_TRADE = "no_trade"
    INVALIDATED = "invalidated"
    EXPIRED = "expired"
    CANCELLED_DATA = "cancelled_data"
    REJECTED_RISK = "rejected_risk"
    MISSED = "missed"

TERMINAL = {SignalStatus.CLOSED, SignalStatus.NO_TRADE, SignalStatus.INVALIDATED, SignalStatus.EXPIRED, SignalStatus.CANCELLED_DATA, SignalStatus.REJECTED_RISK, SignalStatus.MISSED}
ALLOWED = {
    SignalStatus.WATCHING: {SignalStatus.QUALIFIED, SignalStatus.NO_TRADE, SignalStatus.INVALIDATED, SignalStatus.EXPIRED, SignalStatus.CANCELLED_DATA},
    SignalStatus.QUALIFIED: {SignalStatus.ENTRY_ARMED, SignalStatus.NO_TRADE, SignalStatus.INVALIDATED, SignalStatus.EXPIRED, SignalStatus.CANCELLED_DATA, SignalStatus.REJECTED_RISK},
    SignalStatus.ENTRY_ARMED: {SignalStatus.FILLED, SignalStatus.MISSED, SignalStatus.INVALIDATED, SignalStatus.EXPIRED, SignalStatus.CANCELLED_DATA, SignalStatus.REJECTED_RISK, SignalStatus.NO_TRADE},
    SignalStatus.FILLED: {SignalStatus.OPEN, SignalStatus.CLOSED},
    SignalStatus.OPEN: {SignalStatus.CLOSED},
}

@dataclass(frozen=True, slots=True)
class SignalEvent:
    event_id: str
    timestamp: datetime
    target_status: SignalStatus
    reason: str
    evidence_ref: str | None = None

@dataclass(slots=True)
class SignalAggregate:
    signal_id: str
    model_id: str
    instrument: str
    status: SignalStatus = SignalStatus.WATCHING
    last_event_at: datetime | None = None
    applied_event_ids: set[str] = field(default_factory=set)
    history: list[SignalEvent] = field(default_factory=list)

    def apply(self, event: SignalEvent) -> bool:
        """Apply event once. Return False for a duplicate event ID."""
        if not event.event_id.strip():
            raise ValueError("event_id cannot be empty")
        if event.timestamp.tzinfo is None:
            raise ValueError("event timestamp must be timezone-aware")
        if event.event_id in self.applied_event_ids:
            return False
        if self.last_event_at is not None and event.timestamp < self.last_event_at:
            raise ValueError("signal events must be applied chronologically")
        if self.status in TERMINAL:
            raise ValueError(f"terminal signal cannot transition from {self.status.value}")
        if event.target_status not in ALLOWED.get(self.status, set()):
            raise ValueError(f"invalid transition: {self.status.value} -> {event.target_status.value}")
        if not event.reason.strip():
            raise ValueError("event reason cannot be empty")
        self.status = event.target_status
        self.last_event_at = event.timestamp
        self.applied_event_ids.add(event.event_id)
        self.history.append(event)
        return True