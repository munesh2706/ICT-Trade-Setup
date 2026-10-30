"""Phase 2.4: deterministic live candle builder (no broker connection).

Ticks must contain exchange event time, price and *incremental* traded volume.
Angel cumulative volume requires normalization before ingestion. Never infer
missing ticks/candles. CAS ticks are excluded from continuous-session bars.
"""
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time as clock, timedelta, timezone
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class Tick:
    symbol: str
    at: datetime
    price: float
    volume: float


class CandleBuilder:
    def __init__(self, symbols, on_close, on_event, grace_seconds=3):
        self.symbols = set(symbols)
        self.on_close = on_close
        self.on_event = on_event
        self.grace = timedelta(seconds=grace_seconds)
        self.active = {}
        self.last = {}
        self.last_seen = {}
        self.finalized = {}

    @staticmethod
    def session(at):
        local = at.astimezone(IST)
        end = clock(15, 15) if local.date() >= date(2026, 8, 3) else clock(15, 30)
        return local.weekday() < 5 and clock(9, 15) <= local.time() < end

    @staticmethod
    def bucket(at):
        local = at.astimezone(IST)
        start = local.replace(hour=9, minute=15, second=0, microsecond=0)
        minutes = int((local - start).total_seconds() // 60)
        return start + timedelta(minutes=minutes)

    def ingest(self, tick):
        if tick.symbol not in self.symbols:
            raise ValueError("Unmapped symbol")
        if tick.at.tzinfo is None or tick.price <= 0 or tick.volume < 0:
            raise ValueError("Invalid tick")
        at = tick.at.astimezone(timezone.utc)
        if not self.session(at):
            self.on_event(tick.symbol, "OUTSIDE_CONTINUOUS_SESSION", at.isoformat())
            return
        prev = self.last_seen.get(tick.symbol)
        if prev is not None and at <= prev:
            self.on_event(tick.symbol, "OUT_OF_ORDER_OR_DUPLICATE_TICK", at.isoformat())
            return
        self.last_seen[tick.symbol] = at
        minute = self.bucket(at).astimezone(timezone.utc)
        key = tick.symbol
        if minute <= self.finalized.get(key, datetime.min.replace(tzinfo=timezone.utc)):
            self.on_event(key, "TICK_AFTER_FINALIZATION", minute.isoformat())
            return
        current = self.active.get(key)
        if current is not None and minute > current["start"]:
            self.flush(at)
            current = self.active.get(key)
            if current is not None and minute > current["start"]:
                self.on_event(key, "UNFINALIZED_MINUTE_GAP", current["start"].isoformat())
                # Do not silently close a candle before its grace deadline.
                return
        if current is None:
            if prev is not None:
                prev_minute = self.bucket(prev).astimezone(timezone.utc)
                if minute > prev_minute + timedelta(minutes=1):
                    self.on_event(key, "TICK_GAP", f"{prev_minute.isoformat()}..{minute.isoformat()}")
            self.active[key] = {"start": minute, "open": tick.price,
                                "high": tick.price, "low": tick.price,
                                "close": tick.price, "volume": tick.volume}
        else:
            if current["start"] != minute:
                self.on_event(key, "UNFINALIZED_MINUTE_GAP", minute.isoformat())
                return
            current["high"] = max(current["high"], tick.price)
            current["low"] = min(current["low"], tick.price)
            current["close"] = tick.price
            current["volume"] += tick.volume

    def flush(self, now):
        if now.tzinfo is None:
            raise ValueError("Timezone-aware clock required")
        now = now.astimezone(timezone.utc)
        for symbol, row in list(self.active.items()):
            if row["start"] + timedelta(minutes=1) + self.grace > now:
                continue
            del self.active[symbol]
            self.finalized[symbol] = row["start"]
            self.on_close(symbol, "ONE_MINUTE", dict(row))
            start = row["start"]
            anchor = start.astimezone(IST).replace(hour=9, minute=15, second=0, microsecond=0)
            offset = int((start.astimezone(IST) - anchor).total_seconds() // 60)
            five_start = start - timedelta(minutes=offset % 5)
            key = (symbol, five_start)
            part = self.last.setdefault(key, {})
            part[start] = dict(row)
            if len(part) == 5:
                required = [five_start + timedelta(minutes=i) for i in range(5)]
                if all(x in part for x in required):
                    bars = [part[x] for x in required]
                    self.on_close(symbol, "FIVE_MINUTE", {
                        "start": five_start, "open": bars[0]["open"],
                        "high": max(x["high"] for x in bars),
                        "low": min(x["low"] for x in bars),
                        "close": bars[-1]["close"],
                        "volume": sum(x["volume"] for x in bars)})
                del self.last[key]
            # Remove stale incomplete 5m groups, never fabricate candles.
            for old in list(self.last):
                if old[0] == symbol and old[1] + timedelta(minutes=5) < start:
                    self.on_event(symbol, "INCOMPLETE_FIVE_MINUTE", old[1].isoformat())
                    del self.last[old]
