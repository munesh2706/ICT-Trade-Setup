"""Read-only Angel One historical index-candle adapter.

This module intentionally exposes no order, position, holding or funds API.
Credentials are loaded from the repository-local .env and never returned.
"""
from __future__ import annotations
import os
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

from .instruments import INDEX_INSTRUMENTS, InstrumentSpec
from .models import Candle

IST = ZoneInfo("Asia/Kolkata")
MASTER_URL = "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json"
INTERVALS = {"1m": "ONE_MINUTE", "3m": "THREE_MINUTE", "5m": "FIVE_MINUTE", "10m": "TEN_MINUTE", "15m": "FIFTEEN_MINUTE", "30m": "THIRTY_MINUTE", "1h": "ONE_HOUR", "1d": "ONE_DAY"}
MAX_REQUEST_DAYS = {"1m": 30, "3m": 60, "5m": 100, "10m": 100, "15m": 200, "30m": 200, "1h": 400, "1d": 2000}
ROOT = Path(__file__).resolve().parents[1]

class AngelOneFeedError(RuntimeError):
    pass

class AngelOneHistoricalFeed:
    def __init__(self, client, instruments: dict[str, InstrumentSpec], *, pace_seconds: float):
        if pace_seconds < (1 / 3):
            raise ValueError("pace_seconds must respect Angel One historical limit of 3 requests per second")
        self._client = client
        self._instruments = dict(instruments)
        self._pace_seconds = pace_seconds
        self._last_request_at = 0.0
        self.raw_responses: list[dict] = []

    @classmethod
    def connect_from_env(cls, *, pace_seconds: float = 1.0, env_path: str | Path = ROOT / ".env"):
        load_dotenv(Path(env_path))
        required = ("ANGEL_API_KEY", "ANGEL_CLIENT_CODE", "ANGEL_PIN", "ANGEL_TOTP_SECRET")
        missing = [name for name in required if not os.getenv(name)]
        if missing:
            raise AngelOneFeedError("Missing required local environment settings: " + ", ".join(missing))
        try:
            import pyotp
            from SmartApi import SmartConnect
            client = SmartConnect(os.environ["ANGEL_API_KEY"])
            login = client.generateSession(os.environ["ANGEL_CLIENT_CODE"], os.environ["ANGEL_PIN"], pyotp.TOTP(os.environ["ANGEL_TOTP_SECRET"]).now())
        except Exception:
            raise AngelOneFeedError("Angel One authentication could not be completed; inspect local SDK/network configuration") from None
        if not isinstance(login, dict) or login.get("status") is not True:
            raise AngelOneFeedError("Angel One authentication rejected; verify credentials, PIN and device clock")
        feed = cls(client, INDEX_INSTRUMENTS, pace_seconds=pace_seconds)
        feed._verify_instrument_master()
        return feed

    def _verify_instrument_master(self) -> None:
        try:
            response = requests.get(MASTER_URL, timeout=30)
            response.raise_for_status()
            rows = response.json()
        except Exception:
            raise AngelOneFeedError("Instrument master could not be retrieved") from None
        if not isinstance(rows, list):
            raise AngelOneFeedError("Instrument master format is invalid")
        for key, spec in self._instruments.items():
            matches = [r for r in rows if str(r.get("token", "")) == spec.token and str(r.get("exch_seg", "")).upper() == spec.exchange and str(r.get("instrumenttype", "")).upper() == "AMXIDX"]
            if len(matches) != 1:
                raise AngelOneFeedError(f"Instrument master did not uniquely verify {key}")
            row = matches[0]
            name = (str(row.get("name", "")) + " " + str(row.get("symbol", ""))).upper()
            expected = {"NIFTY": "NIFTY", "BANKNIFTY": "BANKNIFTY", "SENSEX": "SENSEX"}[key]
            if expected not in name:
                raise AngelOneFeedError(f"Instrument master identity mismatch for {key}")

    def fetch_candles(self, instrument_id: str, timeframe: str, start: datetime, end: datetime) -> list[Candle]:
        if instrument_id not in self._instruments:
            raise ValueError("instrument_id is outside the configured index-only scope")
        if timeframe not in INTERVALS:
            raise ValueError("unsupported timeframe")
        if start.tzinfo is None or end.tzinfo is None or end <= start:
            raise ValueError("start/end must be timezone-aware and end must be later")
        if (end - start).total_seconds() > MAX_REQUEST_DAYS[timeframe] * 86400:
            raise ValueError(f"request exceeds documented {MAX_REQUEST_DAYS[timeframe]}-day limit for {timeframe}; use fetch_range")
        if any(x.second != 0 or x.microsecond != 0 for x in (start, end)):
            raise ValueError("start/end must align to the API minute precision")
        spec = self._instruments[instrument_id]
        wait = self._pace_seconds - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()
        params = {
            "exchange": spec.exchange,
            "symboltoken": spec.token,
            "interval": INTERVALS[timeframe],
            "fromdate": start.astimezone(IST).strftime("%Y-%m-%d %H:%M"),
            "todate": end.astimezone(IST).strftime("%Y-%m-%d %H:%M"),
        }
        try:
            payload = self._client.getCandleData(params)
            fetched_at = datetime.now(timezone.utc)
            self.raw_responses.append({"instrument_id": instrument_id, "timeframe": timeframe, "fetched_at": fetched_at, "request_params": dict(params), "payload": payload})
        except Exception:
            raise AngelOneFeedError("Angel One historical request failed; no automatic retry was attempted") from None
        if not isinstance(payload, dict) or payload.get("status") is not True:
            code = payload.get("errorcode") if isinstance(payload, dict) else None
            raise AngelOneFeedError(f"Angel One historical request rejected (code={code})")
        rows = payload.get("data") or []
        if not isinstance(rows, list):
            raise AngelOneFeedError("Historical candle response has an invalid data field")
        candles = []
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) < 6:
                raise AngelOneFeedError("Historical response contains a malformed candle row")
            try:
                stamp = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=IST)
                values = [Decimal(str(row[i])) for i in range(1, 6)]
                candle = Candle(stamp, *values[:4], values[4])
            except (ValueError, TypeError, InvalidOperation, OverflowError):
                raise AngelOneFeedError("Historical response contains invalid timestamp or OHLCV values") from None
            candles.append(candle)
        if any(candles[i].timestamp >= candles[i + 1].timestamp for i in range(len(candles) - 1)):
            raise AngelOneFeedError("Historical response is duplicated or out of chronological order")
        if any(c.timestamp < start or c.timestamp >= end for c in candles):
            raise AngelOneFeedError("Historical response contains candles outside the requested interval")
        return candles

    def fetch_range(self, instrument_id: str, timeframe: str, start: datetime, end: datetime) -> list[Candle]:
        """Fetch a long range in documented interval-specific request windows."""
        if timeframe not in MAX_REQUEST_DAYS:
            raise ValueError("unsupported timeframe")
        if start.tzinfo is None or end.tzinfo is None or end <= start:
            raise ValueError("start/end must be timezone-aware and end must be later")
        max_span = timedelta(days=MAX_REQUEST_DAYS[timeframe])
        cursor = start
        combined: list[Candle] = []
        while cursor < end:
            chunk_end = min(cursor + max_span, end)
            chunk = self.fetch_candles(instrument_id, timeframe, cursor, chunk_end)
            if combined and chunk and chunk[0].timestamp <= combined[-1].timestamp:
                raise AngelOneFeedError("overlapping or non-chronological candle chunks")
            combined.extend(chunk)
            cursor = chunk_end
        return combined
