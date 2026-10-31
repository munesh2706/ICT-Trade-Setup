"""Explicit Angel One SmartAPI mapping for the three in-scope spot indices."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class InstrumentSpec:
    instrument_id: str
    display_name: str
    exchange: str
    trading_symbol: str
    token: str
    segment: str
    websocket_exchange_type: int
    series_type: str = "SPOT_INDEX"

INDEX_INSTRUMENTS = {
    "NIFTY": InstrumentSpec("NIFTY", "NIFTY 50", "NSE", "Nifty 50", "99926000", "AMXIDX", 1),
    "BANKNIFTY": InstrumentSpec("BANKNIFTY", "BANKNIFTY", "NSE", "Nifty Bank", "99926009", "AMXIDX", 1),
    "SENSEX": InstrumentSpec("SENSEX", "SENSEX", "BSE", "SENSEX", "99919000", "AMXIDX", 3),
}

def validate_registry(registry: dict[str, InstrumentSpec] = INDEX_INSTRUMENTS) -> None:
    if not registry:
        raise ValueError("instrument registry cannot be empty")
    identities = set()
    for key, spec in registry.items():
        if key != spec.instrument_id:
            raise ValueError("registry key must equal instrument_id")
        if spec.series_type != "SPOT_INDEX":
            raise ValueError("only spot-index series are enabled in this project scope")
        if spec.exchange not in {"NSE", "BSE"} or spec.segment != "AMXIDX":
            raise ValueError("unsupported index exchange/segment mapping")
        if not spec.token.isdigit():
            raise ValueError("instrument token must be numeric")
        if spec.websocket_exchange_type not in {1, 3}:
            raise ValueError("invalid SmartAPI WebSocket exchange type")
        identity = (spec.exchange, spec.token)
        if identity in identities:
            raise ValueError("duplicate exchange/token mapping")
        identities.add(identity)

validate_registry()