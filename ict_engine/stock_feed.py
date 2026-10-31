"""Read-only Angel One SmartAPI feed for NIFTY 50 NSE cash equities."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from .models import Candle
from .stock_universe import (
    ANGEL_MASTER_URL, HEADERS, StockInstrument, UniverseSnapshot,
    UniverseError, download_angelone_master, resolve_angelone_equities,
)

IST = ZoneInfo("Asia/Kolkata")
INTERVALS = {
    "1m": "ONE_MINUTE", "3m": "THREE_MINUTE", "5m": "FIVE_MINUTE",
    "10m": "TEN_MINUTE", "15m": "FIFTEEN_MINUTE", "30m": "THIRTY_MINUTE",
    "1h": "ONE_HOUR", "1d": "ONE_DAY",
}
INTERVAL_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "10m": 10, "15m": 15, "30m": 30, "1h": 60, "1d": 1440}
MAX_REQUEST_DAYS = {"1m": 30, "3m": 60, "5m": 100, "10m": 100, "15m": 200, "30m": 200, "1h": 400, "1d": 2000}
ROOT = Path(__file__).resolve().parents[1]

class StockFeedError(RuntimeError):
    pass

@dataclass(frozen=True, slots=True)
class StockQuote:
    symbol: str
    token: str
    ltp: Decimal
    exchange_timestamp: datetime | None
    received_at: datetime
    age_seconds: float | None
    stale: bool

@dataclass(frozen=True, slots=True)
class QuoteBatch:
    quotes: tuple[StockQuote, ...]
    missing_symbols: tuple[str, ...]
    stale_symbols: tuple[str, ...]
    unfetched_tokens: tuple[str, ...]
    errors: tuple[str, ...]
    received_at: datetime

    @property
    def complete(self) -> bool:
        return not self.missing_symbols and not self.stale_symbols and not self.unfetched_tokens and not self.errors

class AngelOneStockFeed:
    def __init__(self, client, instruments: dict[str, StockInstrument], *, pace_seconds: float = 1.0, master_sha256: str = ""):
        if pace_seconds < (1 / 3):
            raise ValueError("pace_seconds must be at least 1/3 second (Angel One historical API limit)")
        if len(instruments) != 50:
            raise ValueError("exactly 50 resolved NIFTY 50 instruments are required")
        self._client = client
        self.instruments = dict(instruments)
        self.pace_seconds = pace_seconds
        self.master_sha256 = master_sha256
        self._last_request_at = 0.0
        self._last_quote_request_at = 0.0
        self.raw_responses: list[dict] = []

    @classmethod
    def connect_from_env(cls, universe: UniverseSnapshot, *, pace_seconds: float = 1.0, env_path: str | Path = ROOT / ".env"):
        load_dotenv(Path(env_path))
        required = ("ANGEL_API_KEY", "ANGEL_CLIENT_CODE", "ANGEL_PIN", "ANGEL_TOTP_SECRET")
        missing = [key for key in required if not os.getenv(key)]
        if missing:
            raise StockFeedError("missing local Angel One settings: " + ", ".join(missing))
        try:
            import pyotp
            from SmartApi import SmartConnect
            client = SmartConnect(os.environ["ANGEL_API_KEY"])
            login = client.generateSession(
                os.environ["ANGEL_CLIENT_CODE"], os.environ["ANGEL_PIN"],
                pyotp.TOTP(os.environ["ANGEL_TOTP_SECRET"]).now(),
            )
        except Exception:
            raise StockFeedError("Angel One authentication failed; check local SDK, network and device clock") from None
        if not isinstance(login, dict) or login.get("status") is not True:
            raise StockFeedError("Angel One rejected authentication; check credentials, PIN and TOTP clock")
        try:
            master, digest = download_angelone_master()
            instruments = resolve_angelone_equities(universe, master)
        except UniverseError as exc:
            raise StockFeedError(str(exc)) from None
        return cls(client, instruments, pace_seconds=pace_seconds, master_sha256=digest)

    def fetch_candles(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> list[Candle]:
        if symbol not in self.instruments:
            raise ValueError(f"{symbol} is not in the resolved NIFTY 50 universe")
        if timeframe not in INTERVALS:
            raise ValueError(f"unsupported timeframe: {timeframe}")
        if start.tzinfo is None or end.tzinfo is None or end <= start:
            raise ValueError("start/end must be timezone-aware and end must be later")
        if (end - start).total_seconds() > MAX_REQUEST_DAYS[timeframe] * 86400:
            raise ValueError(f"{timeframe} request exceeds {MAX_REQUEST_DAYS[timeframe]} calendar days")
        if any(x.second or x.microsecond for x in (start, end)):
            raise ValueError("request boundaries must align to minute precision")
        instrument = self.instruments[symbol]
        wait = self.pace_seconds - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()
        params = {
            "exchange": "NSE",
            "symboltoken": instrument.token,
            "interval": INTERVALS[timeframe],
            "fromdate": start.astimezone(IST).strftime("%Y-%m-%d %H:%M"),
            "todate": end.astimezone(IST).strftime("%Y-%m-%d %H:%M"),
        }
        try:
            payload = self._client.getCandleData(params)
            fetched_at = datetime.now(timezone.utc)
            self.raw_responses.append({
                "symbol": symbol, "timeframe": timeframe, "token": instrument.token,
                "fetched_at": fetched_at, "request_params": dict(params), "payload": payload,
            })
        except Exception as exc:
            raise StockFeedError(f"Angel One historical request failed for {symbol}/{timeframe}: {type(exc).__name__}") from None
        if not isinstance(payload, dict) or payload.get("status") is not True:
            code = payload.get("errorcode") if isinstance(payload, dict) else "INVALID_RESPONSE"
            raise StockFeedError(f"Angel One historical request rejected for {symbol}/{timeframe}: {code}")
        rows = payload.get("data") or []
        if not isinstance(rows, list):
            raise StockFeedError("Angel One historical response data is not a list")
        candles = []
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) < 6:
                raise StockFeedError("Angel One returned a malformed candle row")
            try:
                stamp = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=IST)
                values = [Decimal(str(row[i])) for i in range(1, 6)]
                candles.append(Candle(stamp, *values[:4], values[4]))
            except (ValueError, TypeError, InvalidOperation, OverflowError):
                raise StockFeedError("Angel One returned an invalid timestamp or OHLCV row") from None
        if any(candles[i].timestamp >= candles[i + 1].timestamp for i in range(len(candles) - 1)):
            raise StockFeedError(f"Angel One response for {symbol}/{timeframe} is duplicated or out of order")
        return candles

    @staticmethod
    def _parse_exchange_time(value) -> datetime | None:
        if value in (None, ""):
            return None
        text = str(value).strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=IST)
            return parsed.astimezone(IST)
        except ValueError:
            for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M"):
                try:
                    return datetime.strptime(text, fmt).replace(tzinfo=IST)
                except ValueError:
                    pass
        return None

    def fetch_full_quotes(self, *, max_age_seconds: float = 90.0) -> QuoteBatch:
        """Fetch one FULL quote batch for all 50 NSE stocks via SmartAPI.

        SmartAPI documents 50 symbols per market-data request and a one-request
        per-second rate. Staleness is reported from exchange feed time; missing
        timestamps are not assumed fresh. This is a quote snapshot, not a
        substitute for the historical candle reconciliation process.
        """
        if max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be positive")
        wait = 1.0 - (time.monotonic() - self._last_quote_request_at)
        if wait > 0:
            time.sleep(wait)
        self._last_quote_request_at = time.monotonic()
        token_to_symbol = {item.token: symbol for symbol, item in self.instruments.items()}
        params = {"NSE": list(token_to_symbol)}
        try:
            payload = self._client.getMarketData("FULL", params)
        except Exception as exc:
            raise StockFeedError(f"Angel One FULL quote request failed: {type(exc).__name__}") from None
        received_at = datetime.now(IST)
        if not isinstance(payload, dict) or payload.get("status") is not True:
            code = payload.get("errorcode") if isinstance(payload, dict) else "INVALID_RESPONSE"
            raise StockFeedError(f"Angel One FULL quote request rejected: {code}")
        data = payload.get("data") or {}
        fetched = data.get("fetched") if isinstance(data, dict) else None
        unfetched = data.get("unfetched") if isinstance(data, dict) else None
        if not isinstance(fetched, list):
            raise StockFeedError("Angel One FULL quote response has no fetched list")
        seen: set[str] = set()
        quotes: list[StockQuote] = []
        errors: list[str] = []
        stale_symbols: list[str] = []
        for row in fetched:
            if not isinstance(row, dict):
                errors.append("malformed quote row")
                continue
            token = str(row.get("symbolToken", row.get("symboltoken", ""))).strip()
            symbol = token_to_symbol.get(token)
            if symbol is None:
                errors.append(f"unknown quote token {token or '<blank>'}")
                continue
            if symbol in seen:
                errors.append(f"duplicate quote row for {symbol}")
                continue
            seen.add(symbol)
            try:
                ltp = Decimal(str(row.get("ltp")))
                if not ltp.is_finite() or ltp <= 0:
                    raise InvalidOperation
            except (InvalidOperation, TypeError, ValueError):
                errors.append(f"invalid LTP for {symbol}")
                continue
            stamp = self._parse_exchange_time(row.get("exchFeedTime", row.get("exch_feed_time")))
            age = (received_at - stamp).total_seconds() if stamp else None
            stale = age is None or age < -5 or age > max_age_seconds
            if stale:
                stale_symbols.append(symbol)
            quotes.append(StockQuote(symbol, token, ltp, stamp, received_at, age, stale))
        missing = tuple(sorted(set(self.instruments) - seen))
        unfetched_tokens = []
        if isinstance(unfetched, list):
            for row in unfetched:
                if isinstance(row, dict):
                    token = str(row.get("symbolToken", row.get("symboltoken", ""))).strip()
                    unfetched_tokens.append(token or "<blank>")
                else:
                    unfetched_tokens.append(str(row))
        elif unfetched not in (None, []):
            errors.append("malformed unfetched quote list")
        return QuoteBatch(
            tuple(sorted(quotes, key=lambda x: x.symbol)),
            missing,
            tuple(sorted(set(stale_symbols))),
            tuple(unfetched_tokens),
            tuple(errors),
            received_at,
        )

    def fetch_range(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> list[Candle]:
        """Fetch a range in non-overlapping provider-sized chunks."""
        if timeframe not in MAX_REQUEST_DAYS:
            raise ValueError("unsupported timeframe")
        limit = timedelta(days=MAX_REQUEST_DAYS[timeframe])
        cursor = start
        result: list[Candle] = []
        while cursor < end:
            boundary = min(cursor + limit, end)
            chunk = self.fetch_candles(symbol, timeframe, cursor, boundary)
            if result and chunk and chunk[0].timestamp <= result[-1].timestamp:
                raise StockFeedError("Angel One returned overlapping historical chunks")
            result.extend(chunk)
            cursor = boundary
        return result
