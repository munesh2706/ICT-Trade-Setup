"""Angel One authoritative completed-candle ingestion for the live scanner.

Source is SmartAPI getCandleData, NEVER sampled WebSocket quotes. Both intervals
are independently broker-supplied. Every requested completed candle must exist,
match its exchange session grid, pass source/price validation, and (for 5m)
match five verified broker-origin 1m candles before commit.

No retries on rejected requests. No broker order API, invented data or rule
changes. The caller controls the single credential/session and global pacing.
"""
import math
import sqlite3
import time
from datetime import date, datetime, time as dtime, timedelta, timezone

from collect_historical_uploaded import IST, parse_timestamp, validate_rows, classify_broker_response
from live_gap_recovery import error_category
from audit_historical import close as ohlcv_close

START = dtime(9, 15)
TRUSTED = {"ANGEL_HISTORICAL", "ANGEL_LIVE_CATCHUP"}
STEPS = {"ONE_MINUTE": 1, "FIVE_MINUTE": 5}
CANDLE_GRACE = 5


class CandleFeedBlocked(RuntimeError):
    """Sanitized interruption; no credentials, payloads or request URLs."""


def session_close(day):
    return dtime(15, 15) if day >= date(2026, 8, 3) else dtime(15, 30)


def complete_times(day, interval, now):
    if interval not in STEPS or now.tzinfo is None:
        raise ValueError("INVALID_INTERVAL_OR_NAIVE_CLOCK")
    if day > now.astimezone(IST).date() or day.weekday() >= 5:
        raise ValueError("NOT_A_COMPLETED_OR_ACTIVE_WEEKDAY")
    begin = datetime.combine(day, START, IST)
    stop = datetime.combine(day, session_close(day), IST)
    complete_through = min(stop, now.astimezone(IST) - timedelta(seconds=CANDLE_GRACE))
    step = STEPS[interval]
    count = max(0, int((complete_through - begin).total_seconds() // (step * 60)))
    return [begin + timedelta(minutes=i * step) for i in range(count)]


def verified_database_rows(db, symbol, interval, begins):
    """Return exact canonical rows or None; also reject untrusted/invalid values."""
    if not begins:
        return []
    expected = [b.astimezone(timezone.utc).isoformat() for b in begins]
    rows = db.execute(
        "SELECT start_utc,open,high,low,close,volume,source FROM candles "
        "WHERE symbol=? AND interval=? AND start_utc>=? AND start_utc<=? ORDER BY start_utc",
        (symbol, interval, expected[0], expected[-1])).fetchall()
    if [x[0] for x in rows] != expected:
        return None
    for stamp, o, h, l, c, v, source in rows:
        vals = (o, h, l, c, v)
        if (source not in TRUSTED or any(not math.isfinite(x) for x in vals)
                or not (o > 0 and l > 0 and l <= min(o, c)
                        and max(o, c) <= h and v >= 0)):
            raise CandleFeedBlocked("UNTRUSTED_OR_INVALID_CANONICAL_HISTORY")
    return [r[:6] for r in rows]


def verified_day(db, symbol, day, interval):
    begin = datetime.combine(day, START, IST)
    finish = datetime.combine(day, session_close(day), IST) + timedelta(minutes=1)
    return verified_database_rows(db, symbol, interval, complete_times(day, interval, finish)) is not None


def parity_rows(one_rows, five_rows):
    """Exact five-to-one match with canonical historical comparison tolerance."""
    minute_map = {x[0]: x[1:] for x in one_rows}
    for five in five_rows:
        t = datetime.fromisoformat(five[0])
        group = [minute_map.get((t + timedelta(minutes=i)).isoformat()) for i in range(5)]
        if any(row is None for row in group):
            raise CandleFeedBlocked("5M_REQUIRES_FIVE_VERIFIED_1M_CANDLES")
        expected = (group[0][0], max(z[1] for z in group), min(z[2] for z in group),
                    group[-1][3], sum(z[4] for z in group))
        if not all(ohlcv_close(x, y) for x, y in zip(expected, five[1:])):
            raise CandleFeedBlocked("BROKER_1M_5M_OHLCV_CONFLICT")


def insert_atomic(db, symbol, interval, new_rows):
    """Caller owns transaction; any existing conflict aborts the entire batch."""
    added = 0
    for row in new_rows:
        stamp, o, h, l, c, v = row
        existing = db.execute(
            "SELECT open,high,low,close,volume,source FROM candles "
            "WHERE symbol=? AND interval=? AND start_utc=?",
            (symbol, interval, stamp)).fetchone()
        if existing is not None:
            if existing[5] not in TRUSTED or tuple(existing[:5]) != (o, h, l, c, v):
                raise CandleFeedBlocked("CANONICAL_CANDLE_CONFLICT_OR_UNTRUSTED_SOURCE")
            continue
        db.execute(
            "INSERT INTO candles(symbol,interval,start_utc,open,high,low,close,volume,source) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (symbol, interval, stamp, o, h, l, c, v, "ANGEL_HISTORICAL"))
        added += 1
    return added


class AngelCandleFeed:
    def __init__(self, client, mapping, db, pace_seconds=3.0, sleeper=time.sleep,
                 monotonic=time.monotonic):
        if pace_seconds < 2 or pace_seconds > 60:
            raise ValueError("RATE_LIMIT_PACING_MUST_BE_2_TO_60_SECONDS")
        self.client, self.mapping, self.db = client, mapping, db
        self.pace_seconds = pace_seconds
        self.sleeper, self.monotonic = sleeper, monotonic
        self.next_request = None
        self.calls = 0
        self.blocked = False

    def _request(self, symbol, interval, begins, now):
        if self.blocked:
            raise CandleFeedBlocked("HISTORICAL_API_CIRCUIT_OPEN")
        record = self.mapping.get(symbol)
        if (not isinstance(record, dict) or record.get("exchange") != "NSE"
                or record.get("segment") != "nse_cm"
                or not str(record.get("token", "")).isdigit()):
            raise CandleFeedBlocked("UNVERIFIED_NSE_CASH_SYMBOL")
        if not begins:
            return []
        if self.next_request is not None:
            self.sleeper(max(0.0, self.next_request - self.monotonic()))
        self.next_request = self.monotonic() + self.pace_seconds
        self.calls += 1
        # Sending the exclusive end as todate supports both inclusive and
        # exclusive broker implementations. We discard only boundary rows.
        end_exclusive = begins[-1] + timedelta(minutes=STEPS[interval])
        params = {"exchange": "NSE", "symboltoken": str(record["token"]),
                  "interval": interval, "fromdate": begins[0].strftime("%Y-%m-%d %H:%M"),
                  "todate": end_exclusive.strftime("%Y-%m-%d %H:%M")}
        try:
            reply = self.client.getCandleData(params)
            if isinstance(reply, dict) and reply.get("status") is not True:
                reason = str(reply.get("errorcode") or "") + " " + str(reply.get("message") or "")
                category = error_category(RuntimeError(reason))
                if category == "ACCESS_RATE_REJECTED":
                    self.blocked = True
                    raise CandleFeedBlocked("ACCESS_RATE_REJECTED")
            raw = classify_broker_response(reply)
        except CandleFeedBlocked:
            raise
        except Exception as exc:
            category = error_category(exc)
            # Never probe repeatedly after any unknown/broker failure; stop
            # until an operator inspects the record.
            self.blocked = True
            raise CandleFeedBlocked("BROKER_" + category) from None
        expected = [d.astimezone(timezone.utc).isoformat() for d in begins]
        end = end_exclusive.astimezone(timezone.utc)
        clean = []
        for row in raw:
            try:
                ts = parse_timestamp(row[0])
            except (ValueError, TypeError, IndexError, OverflowError):
                self.blocked = True
                raise CandleFeedBlocked("INVALID_BROKER_TIMESTAMP") from None
            if ts >= end_exclusive:
                # Only a timestamp exactly at the requested exclusive bound
                # may be returned, or postclose CAS within its official range.
                if ts == end_exclusive or (
                    ts.date() == begins[0].date() and
                    dtime(15, 15) <= ts.time() < dtime(15, 35)):
                    continue
                self.blocked = True
                raise CandleFeedBlocked("UNEXPECTED_BROKER_ROW_OUTSIDE_WINDOW")
            clean.append(row)
        rows, issues = validate_rows(clean, interval, now=now)
        if issues or [x[0] for x in rows] != expected:
            self.blocked = True
            raise CandleFeedBlocked("INCOMPLETE_OR_INVALID_BROKER_CANDLES")
        if any(not all(math.isfinite(float(v)) for v in row[1:]) for row in rows):
            self.blocked = True
            raise CandleFeedBlocked("NONFINITE_BROKER_OHLCV")
        return rows

    def sync(self, symbol, day, now, both=True):
        """Sync all completed bars up to this clock; 5m always parity-checked."""
        if self.blocked:
            raise CandleFeedBlocked("HISTORICAL_API_CIRCUIT_OPEN")
        one_grid = complete_times(day, "ONE_MINUTE", now)
        five_grid = complete_times(day, "FIVE_MINUTE", now) if both else []
        if not one_grid:
            return {"symbol": symbol, "one_minute": 0, "five_minute": 0,
                    "requests": 0, "inserted": 0}
        prior_calls = self.calls
        new_one = (None if verified_database_rows(self.db, symbol, "ONE_MINUTE", one_grid) is not None
                   else self._request(symbol, "ONE_MINUTE", one_grid, now))
        new_five = (None if not five_grid or
                    verified_database_rows(self.db, symbol, "FIVE_MINUTE", five_grid) is not None
                    else self._request(symbol, "FIVE_MINUTE", five_grid, now))
        # Validate all intervals together using data pending insertion.
        existing_one = verified_database_rows(self.db, symbol, "ONE_MINUTE", one_grid)
        existing_five = verified_database_rows(self.db, symbol, "FIVE_MINUTE", five_grid) if five_grid else []
        one_rows = new_one if new_one is not None else existing_one
        five_rows = new_five if new_five is not None else existing_five
        if one_rows is None or five_rows is None:
            raise CandleFeedBlocked("INCOMPLETE_CANONICAL_HISTORY")
        if five_grid:
            parity_rows(one_rows, five_rows)
        with self.db:
            added = 0
            if new_one is not None:
                added += insert_atomic(self.db, symbol, "ONE_MINUTE", new_one)
            if new_five is not None:
                added += insert_atomic(self.db, symbol, "FIVE_MINUTE", new_five)
        return {"symbol": symbol, "one_minute": len(one_grid),
                "five_minute": len(five_grid),
                "requests": self.calls - prior_calls, "inserted": added}
