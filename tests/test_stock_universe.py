from datetime import date
import pytest

from ict_engine.stock_universe import (
    UniverseError, parse_nse_constituent_csv, resolve_angelone_equities,
)

def make_csv(count=50):
    rows = ["Company Name,Industry,Symbol,Series,ISIN Code"]
    for i in range(count):
        rows.append(f"Company {i},Industry,SYM{i:02d},EQ,INE00000000{i:02d}")
    return "\\n".join(rows)

def test_constituent_csv_requires_exactly_50_unique_members():
    snapshot = parse_nse_constituent_csv(make_csv(), captured_on=date(2026, 10, 31))
    assert len(snapshot.constituents) == 50
    assert snapshot.constituents[0].symbol == "SYM00"
    with pytest.raises(UniverseError):
        parse_nse_constituent_csv(make_csv(49))

def test_constituent_csv_rejects_duplicate_symbols():
    raw = make_csv().replace("SYM01", "SYM00")
    with pytest.raises(UniverseError):
        parse_nse_constituent_csv(raw)

def test_angel_master_cash_eq_resolution_does_not_require_instrumenttype_eq():
    snapshot = parse_nse_constituent_csv(make_csv(), captured_on=date(2026, 10, 31))
    master = [
        {"token": str(1000+i), "symbol": f"SYM{i:02d}-EQ", "name": f"SYM{i:02d}",
         "exch_seg": "nse_cm", "instrumenttype": ""}
        for i in range(50)
    ]
    result = resolve_angelone_equities(snapshot, master)
    assert len(result) == 50
    assert result["SYM00"].token == "1000"

def test_angel_master_missing_or_ambiguous_token_fails_closed():
    snapshot = parse_nse_constituent_csv(make_csv(), captured_on=date(2026, 10, 31))
    master = [
        {"token": str(1000+i), "symbol": f"SYM{i:02d}-EQ", "exch_seg": "NSE"}
        for i in range(49)
    ]
    with pytest.raises(UniverseError):
        resolve_angelone_equities(snapshot, master)
