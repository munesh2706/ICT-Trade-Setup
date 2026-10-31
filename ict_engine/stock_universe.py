"""NIFTY 50 membership snapshots and strict Angel One NSE-EQ resolution.

Membership is sourced from the official NSE Indices constituent CSV. Market
prices and instrument tokens are sourced only from Angel One SmartAPI/master.
No fallback constituent list or guessed token is embedded in this module.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

import requests

NSE_CONSTITUENT_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv"
ANGEL_MASTER_URL = "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "text/csv,application/json,*/*"}

class UniverseError(RuntimeError):
    pass

@dataclass(frozen=True, slots=True)
class Constituent:
    symbol: str
    company_name: str
    industry: str = ""

@dataclass(frozen=True, slots=True)
class UniverseSnapshot:
    snapshot_id: str
    captured_at_utc: str
    as_of_date: str
    source_url: str
    source_sha256: str
    constituents: tuple[Constituent, ...]

@dataclass(frozen=True, slots=True)
class StockInstrument:
    symbol: str
    company_name: str
    trading_symbol: str
    token: str
    exchange: str
    segment: str
    websocket_exchange_type: int = 1
    tick_size: Decimal | None = None

    def __post_init__(self):
        if self.tick_size is not None and self.tick_size <= 0:
            raise UniverseError("instrument tick_size must be positive")

def _field(row: dict[str, Any], *names: str) -> str:
    normalized = {str(k).strip().lower().replace(" ", "").replace("_", ""): v for k, v in row.items()}
    for name in names:
        value = normalized.get(name.lower().replace(" ", "").replace("_", ""))
        if value is not None:
            return str(value).strip()
    return ""

def parse_nse_constituent_csv(raw_csv: str, *, captured_on: date | None = None) -> UniverseSnapshot:
    if not raw_csv.strip():
        raise UniverseError("NSE constituent CSV is empty")
    try:
        rows = list(csv.DictReader(io.StringIO(raw_csv.lstrip("\ufeff"))))
    except csv.Error as exc:
        raise UniverseError(f"cannot parse NSE constituent CSV: {exc}") from None
    if not rows:
        raise UniverseError("NSE constituent CSV contains no data rows")
    constituents = []
    for line, row in enumerate(rows, start=2):
        symbol = _field(row, "Symbol").upper()
        company = _field(row, "Company Name", "CompanyName")
        industry = _field(row, "Industry")
        series = _field(row, "Series").upper()
        if not symbol or not company:
            raise UniverseError(f"NSE CSV row {line} is missing symbol/company name")
        if series and series != "EQ":
            continue
        constituents.append(Constituent(symbol, company, industry))
    symbols = [x.symbol for x in constituents]
    if len(constituents) != 50 or len(set(symbols)) != 50:
        raise UniverseError(f"expected 50 unique NIFTY 50 constituents, got {len(constituents)}")
    digest = hashlib.sha256(raw_csv.encode("utf-8")).hexdigest()
    today = captured_on or datetime.now(ZoneInfo('Asia/Kolkata')).date()
    snapshot_id = f"nifty50_{digest[:16]}"
    return UniverseSnapshot(
        snapshot_id=snapshot_id,
        captured_at_utc=datetime.now(timezone.utc).isoformat(),
        as_of_date=today.isoformat(),
        source_url=NSE_CONSTITUENT_URL,
        source_sha256=digest,
        constituents=tuple(sorted(constituents, key=lambda x: x.symbol)),
    )

def download_nse_universe(*, timeout: int = 30, session: requests.Session | None = None) -> UniverseSnapshot:
    client = session or requests.Session()
    try:
        response = client.get(NSE_CONSTITUENT_URL, headers=HEADERS, timeout=timeout)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").lower()
        if "csv" not in content_type and "text/plain" not in content_type and response.text.lstrip()[:1] in "<{":
            raise UniverseError("NSE returned a non-CSV response; refusing to create a universe snapshot")
        return parse_nse_constituent_csv(response.content.decode("utf-8-sig"))
    except UniverseError:
        raise
    except Exception as exc:
        raise UniverseError(f"official NSE constituent download failed: {type(exc).__name__}") from None

def save_universe_snapshot(snapshot: UniverseSnapshot, directory: str | Path) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{snapshot.as_of_date}_{snapshot.snapshot_id}.json"
    payload = {
        "snapshot_id": snapshot.snapshot_id,
        "captured_at_utc": snapshot.captured_at_utc,
        "as_of_date": snapshot.as_of_date,
        "source_url": snapshot.source_url,
        "source_sha256": snapshot.source_sha256,
        "constituents": [asdict(x) for x in snapshot.constituents],
    }
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing.get("source_sha256") != snapshot.source_sha256 or existing.get("constituents") != payload["constituents"]:
            raise UniverseError(f"immutable universe snapshot conflict: {path}")
    else:
        path.write_text(encoded, encoding="utf-8")
    return path

def load_universe_snapshot(path: str | Path) -> UniverseSnapshot:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        members = tuple(Constituent(**row) for row in payload["constituents"])
        snapshot = UniverseSnapshot(
            snapshot_id=payload["snapshot_id"],
            captured_at_utc=payload["captured_at_utc"],
            as_of_date=payload["as_of_date"],
            source_url=payload["source_url"],
            source_sha256=payload["source_sha256"],
            constituents=members,
        )
    except Exception as exc:
        raise UniverseError(f"invalid universe snapshot: {type(exc).__name__}") from None
    if len(snapshot.constituents) != 50 or len({x.symbol for x in snapshot.constituents}) != 50:
        raise UniverseError("universe snapshot must contain exactly 50 unique symbols")
    if len(snapshot.source_sha256) != 64 or any(ch not in "0123456789abcdef" for ch in snapshot.source_sha256.lower()):
        raise UniverseError("universe snapshot has an invalid source SHA-256")
    return snapshot

def _normalize_exchange(value: Any) -> str:
    return str(value or "").strip().upper().replace("_", "").replace("-", "")

def resolve_angelone_equities(snapshot: UniverseSnapshot, instrument_master: list[dict[str, Any]]) -> dict[str, StockInstrument]:
    """Resolve all 50 members against NSE cash-equity rows in Angel One master.

    SmartAPI's cash rows commonly use exch_seg='NSE'/'nse_cm', symbol='X-EQ'
    and a blank instrumenttype. We identify cash EQ by exact '-EQ' symbol and
    NSE cash segment; we do not incorrectly require instrumenttype == 'EQ'.
    """
    if not isinstance(instrument_master, list):
        raise UniverseError("Angel One instrument master is not a list")
    cash_rows = []
    for row in instrument_master:
        if not isinstance(row, dict):
            continue
        exchange = _normalize_exchange(row.get("exch_seg"))
        symbol = str(row.get("symbol", "")).strip().upper()
        token = str(row.get("token", "")).strip()
        if exchange in {"NSE", "NSECM"} and symbol.endswith("-EQ") and token.isdigit():
            cash_rows.append(row)
    result: dict[str, StockInstrument] = {}
    errors = []
    for member in snapshot.constituents:
        expected = f"{member.symbol}-EQ"
        matches = [row for row in cash_rows if str(row.get("symbol", "")).strip().upper() == expected]
        if len(matches) != 1:
            errors.append(f"{member.symbol}: expected one NSE EQ master row, found {len(matches)}")
            continue
        row = matches[0]
        try:
            # Angel One publishes tick_size in paise; normalize to rupees.
            tick_size = Decimal(str(row.get("tick_size", ""))) / Decimal("100")
            if not tick_size.is_finite() or tick_size <= 0:
                raise InvalidOperation
        except (InvalidOperation, ValueError, TypeError):
            errors.append(f"{member.symbol}: invalid Angel One tick_size")
            continue
        result[member.symbol] = StockInstrument(
            symbol=member.symbol,
            company_name=member.company_name,
            trading_symbol=expected,
            token=str(row["token"]).strip(),
            exchange="NSE",
            segment=str(row.get("exch_seg", "NSE")).strip(),
            websocket_exchange_type=1,
            tick_size=tick_size,
        )
    if errors or len(result) != 50:
        raise UniverseError("Angel One universe resolution failed closed: " + "; ".join(errors))
    tokens = [x.token for x in result.values()]
    if len(tokens) != len(set(tokens)):
        raise UniverseError("Angel One master maps multiple NIFTY 50 symbols to the same token")
    return result

def download_angelone_master(*, timeout: int = 30, session: requests.Session | None = None) -> tuple[list[dict[str, Any]], str]:
    client = session or requests.Session()
    try:
        response = client.get(ANGEL_MASTER_URL, headers=HEADERS, timeout=timeout)
        response.raise_for_status()
        rows = response.json()
    except Exception as exc:
        raise UniverseError(f"Angel One instrument master download failed: {type(exc).__name__}") from None
    if not isinstance(rows, list):
        raise UniverseError("Angel One instrument master has an unexpected structure")
    digest = hashlib.sha256(response.content).hexdigest()
    return rows, digest
