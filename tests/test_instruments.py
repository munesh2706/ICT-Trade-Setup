import pytest
from ict_engine.instruments import INDEX_INSTRUMENTS, InstrumentSpec, validate_registry

def test_index_registry_has_exactly_three_spot_indices():
    assert set(INDEX_INSTRUMENTS) == {"NIFTY", "BANKNIFTY", "SENSEX"}
    assert INDEX_INSTRUMENTS["NIFTY"].token == "99926000"
    assert INDEX_INSTRUMENTS["BANKNIFTY"].token == "99926009"
    assert INDEX_INSTRUMENTS["SENSEX"].token == "99919000"
    assert INDEX_INSTRUMENTS["SENSEX"].exchange == "BSE"

def test_duplicate_exchange_token_rejected():
    x = InstrumentSpec("A", "A", "NSE", "A", "123", "AMXIDX", 1)
    y = InstrumentSpec("B", "B", "NSE", "B", "123", "AMXIDX", 1)
    with pytest.raises(ValueError):
        validate_registry({"A": x, "B": y})

def test_equity_or_futures_series_rejected():
    x = InstrumentSpec("NIFTY", "NIFTY", "NSE", "NIFTY", "123", "nse_cm", 1, "FUTURES")
    with pytest.raises(ValueError):
        validate_registry({"NIFTY": x})