"""Phase 2.3: historical NSE cash candles from Angel One SmartAPI.

Read-only; no orders, no OB calculation. Python 3.12.
Requires .env: ANGEL_API_KEY, ANGEL_CLIENT_CODE, ANGEL_PASSWORD, ANGEL_TOTP_SECRET
Never print credentials. Test validation locally before authenticated fetch.
"""
import argparse
import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, time as dtime, timezone, date
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
IST = ZoneInfo("Asia/Kolkata")
INTERVALS = {"ONE_MINUTE": 1, "FIVE_MINUTE": 5}
DB = ROOT / "data" / "market_data.sqlite3"

def load_mapping():
    path = ROOT / "data" / "instruments" / "nifty50_mapping.json"
    obj = json.loads(path.read_text(encoding="utf-8"))
    rows = obj["instruments"]
    if obj.get("status") != "PASS" or len(rows) != 50 or len({r["token"] for r in rows}) != 50:
        raise ValueError("Instrument mapping must have 50 distinct validated tokens")
    return {r["symbol"]: r for r in rows}

def parse_timestamp(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Candle timestamp missing timezone: " + str(value))
    return dt.astimezone(IST)

def expected_candles(start_date, end_date, interval, holidays):
    """Count expected candles for a date range, excluding weekends/holidays."""
    minutes = INTERVALS[interval]
    count = 0
    current = start_date
    while current <= end_date:
        if current.weekday() < 5 and current not in holidays:
            cutoff = dtime(15, 15) if current >= date(2026, 8, 3) else dtime(15, 30)
            session_minutes = (15 * 60 + (15 if cutoff.hour == 15 else 30)) - (9 * 60 + 15)
            count += session_minutes // minutes
        current += timedelta(days=1)
    return count

def validate_rows(raw, interval, now=None):
    minutes = INTERVALS[interval]
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    parsed = {}
    problems = []
    for row in raw:
        try:
            if not isinstance(row, (list, tuple)) or len(row) < 6:
                raise ValueError("expected [time, open, high, low, close, volume]")
            dt = parse_timestamp(row[0])
            o, h, l, c, v = map(float, row[1:6])
            if not (o > 0 and l > 0 and l <= min(o, c) <= max(o, c) <= h and v >= 0):
                raise ValueError("invalid OHLCV")
            if dt.weekday() >= 5 or dt.time() < dtime(9, 15) or dt.time() >= (dtime(15, 15) if dt.date() >= date(2026, 8, 3) else dtime(15, 30)):
                raise ValueError("outside normal cash continuous session")
            session_minute = (dt.hour * 60 + dt.minute) - (9 * 60 + 15)
            if session_minute % minutes != 0 or dt.second != 0 or dt.microsecond != 0:
                raise ValueError("not session aligned")
            if dt.astimezone(timezone.utc) + timedelta(minutes=minutes) > now:
                raise ValueError("incomplete future/current candle")
            key = dt.astimezone(timezone.utc).isoformat()
            value = (key, o, h, l, c, v)
            if key in parsed and parsed[key] != value:
                raise ValueError("conflicting duplicate timestamp")
            parsed[key] = value
        except (ValueError, TypeError, IndexError) as exc:
            problems.append({"row": str(row)[:200], "reason": str(exc)})
    return sorted(parsed.values()), problems

def init_db(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS candles (
      symbol TEXT NOT NULL, interval TEXT NOT NULL, start_utc TEXT NOT NULL,
      open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL,
      close REAL NOT NULL, volume REAL NOT NULL, source TEXT NOT NULL,
      PRIMARY KEY(symbol, interval, start_utc))""")
    connection.execute("""CREATE TABLE IF NOT EXISTS collection_events (
      created_utc TEXT NOT NULL, symbol TEXT, interval TEXT, event TEXT NOT NULL,
      details TEXT NOT NULL)""")
    connection.execute("""CREATE TABLE IF NOT EXISTS auction_candles (
      symbol TEXT NOT NULL, interval TEXT NOT NULL, start_utc TEXT NOT NULL,
      open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL,
      close REAL NOT NULL, volume REAL NOT NULL, source TEXT NOT NULL,
      session_phase TEXT NOT NULL,
      PRIMARY KEY(symbol, interval, start_utc))""")
    connection.commit()

def classify_cas_time(dt):
    """NSE cash CAS, effective 2026-08-03; preserve broker bars separately."""
    t = dt.time()
    if dt.date() < date(2026, 8, 3) or dt.weekday() >= 5:
        return None
    if dtime(15, 15) <= t < dtime(15, 20):
        return "CAS_TRANSITION"
    if dtime(15, 20) <= t < dtime(15, 30):
        return "CAS_ORDER_ENTRY"
    if dtime(15, 30) <= t < dtime(15, 35):
        return "CAS_MATCHING"
    return None

def archive_cas(db, symbol, interval, raw):
    """Archive broker-reported CAS-window bars; never mix with CTS candles."""
    saved = duplicates = conflicts = 0
    for row in raw:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        try:
            dt = parse_timestamp(row[0])
            phase = classify_cas_time(dt)
            if phase is None:
                continue
            o, h, l, c, v = map(float, row[1:6])
            if not (o > 0 and l > 0 and l <= min(o, c) <= max(o, c) <= h and v >= 0):
                raise ValueError("Invalid CAS OHLCV")
            key = dt.astimezone(timezone.utc).isoformat()
            existing = db.execute(
                "SELECT open,high,low,close,volume FROM auction_candles WHERE symbol=? AND interval=? AND start_utc=?",
                (symbol, interval, key)).fetchone()
            values = (o, h, l, c, v)
            if existing is not None:
                if tuple(existing) != values:
                    conflicts += 1
                    log_event(db, symbol, interval, "CAS_CONFLICT", {"start_utc": key})
                else:
                    duplicates += 1
                continue
            db.execute("INSERT INTO auction_candles VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (symbol, interval, key, o, h, l, c, v, "ANGEL_HISTORICAL_CAS", phase))
            saved += 1
        except (ValueError, TypeError, IndexError) as exc:
            raise RuntimeError(f"Invalid CAS broker row: {type(exc).__name__}") from None
    db.commit()
    return saved, duplicates, conflicts

def log_event(db, symbol, interval, event, details):
    db.execute("INSERT INTO collection_events VALUES (?,?,?,?,?)",
               (datetime.now(timezone.utc).isoformat(), symbol, interval, event, json.dumps(details)))

def persist(db, symbol, interval, rows):
    inserted = duplicates = conflicts = 0
    for ts, o, h, l, c, v in rows:
        old = db.execute("SELECT open,high,low,close,volume FROM candles WHERE symbol=? AND interval=? AND start_utc=?",
                         (symbol, interval, ts)).fetchone()
        new = (o, h, l, c, v)
        if old is not None:
            if tuple(old) == new:
                duplicates += 1
            else:
                conflicts += 1
                log_event(db, symbol, interval, "HISTORICAL_CONFLICT", {"start_utc": ts, "stored": old, "incoming": new})
            continue
        db.execute("INSERT INTO candles VALUES (?,?,?,?,?,?,?,?,?)",
                   (symbol, interval, ts, o, h, l, c, v, "ANGEL_HISTORICAL"))
        inserted += 1
    db.commit()
    return inserted, duplicates, conflicts

def test_offline():
    base = "2026-10-12T09:15:00+05:30"
    good = [[base, 100, 102, 99, 101, 1000]]
    now = datetime(2026, 10, 12, 4, 0, tzinfo=timezone.utc)
    rows, errors = validate_rows(good, "ONE_MINUTE", now)
    assert len(rows) == 1 and not errors
    rows, errors = validate_rows(good + good, "ONE_MINUTE", now)
    assert len(rows) == 1 and not errors
    rows, errors = validate_rows([[base, 100, 98, 99, 101, 1000]], "ONE_MINUTE", now)
    assert len(rows) == 0 and len(errors) == 1
    rows, errors = validate_rows(good, "FIVE_MINUTE", datetime(2026, 10, 12, 3, 46, tzinfo=timezone.utc))
    assert not rows and errors
    print("OFFLINE VALIDATION: PASS")

def authenticate():
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    required = ("ANGEL_API_KEY", "ANGEL_CLIENT_CODE", "ANGEL_PASSWORD", "ANGEL_TOTP_SECRET")
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise RuntimeError("Missing .env keys: " + ", ".join(missing))
    import pyotp
    from SmartApi import SmartConnect
    client = SmartConnect(api_key=os.environ["ANGEL_API_KEY"])
    response = client.generateSession(os.environ["ANGEL_CLIENT_CODE"],
                                      os.environ["ANGEL_PASSWORD"],
                                      pyotp.TOTP(os.environ["ANGEL_TOTP_SECRET"]).now())
    if not isinstance(response, dict) or response.get("status") is not True:
        raise RuntimeError("Angel authentication failed (response intentionally redacted)")
    return client

class BrokerRetryableError(RuntimeError):
    pass

class BrokerPermanentError(RuntimeError):
    pass

class PartialDataError(RuntimeError):
    pass

def classify_broker_response(response):
    if not isinstance(response, dict):
        raise BrokerRetryableError("Invalid broker response")
    if response.get("status") is True and isinstance(response.get("data"), list):
        return response["data"]
    code = str(response.get("errorcode") or "").upper()
    message = str(response.get("message") or "").lower()
    if any(term in message for term in ("rate limit", "too many", "throttl", "try again", "temporar", "timeout", "timed out", "server busy")) or code in {"429", "503", "504", "AB1004"}:
        raise BrokerRetryableError("Broker throttled or temporarily unavailable")
    raise BrokerPermanentError("Broker rejected request (details redacted)")

def fetch_with_retry(client, params, max_attempts=3, base_delay=3.0):
    if not 1 <= max_attempts <= 6 or base_delay < 1:
        raise ValueError("Invalid retry policy")
    for attempt in range(1, max_attempts + 1):
        try:
            return classify_broker_response(client.getCandleData(params))
        except BrokerPermanentError:
            raise
        except Exception as exc:
            if attempt == max_attempts:
                raise BrokerRetryableError("Historical API unavailable after bounded retries") from None
            delay = min(60.0, base_delay * (2 ** (attempt - 1)))
            print(f"API RETRY {attempt}/{max_attempts} after {delay:.0f}s ({type(exc).__name__})")
            time.sleep(delay)

def collect(client, db, symbol, token, interval, start, end, pause, max_attempts=3, 
            holidays=None, auto_split=True, max_records=8000):
    """Fetch historical candles with automatic chunking on partial data.
    
    Args:
        auto_split: If True, split date ranges that exceed max_records.
        max_records: Angel One limit (documented 8000).
        holidays: set of dates to skip (from load_calendar).
    """
    if holidays is None:
        from backfill_historical import load_calendar
        holidays = load_calendar(start.date(), end.date())
    
    def fetch_range(start_dt, end_dt, depth=0):
        """Recursively fetch date range, splitting if truncated."""
        if depth > 5:
            raise RuntimeError("Max recursion depth (5) exceeded; range may exceed broker capacity")
        
        expected = expected_candles(start_dt.date(), end_dt.date(), interval, holidays)
        
        query_start = datetime.combine(start_dt.date(), dtime(9, 15), IST)
        query_end = datetime.combine(end_dt.date(), dtime(15, 35) if end_dt.date() >= date(2026, 8, 3) else dtime(15, 30), IST)
        params = {"exchange": "NSE", "symboltoken": token, "interval": interval,
                  "fromdate": query_start.strftime("%Y-%m-%d %H:%M"),
                  "todate": query_end.strftime("%Y-%m-%d %H:%M")}
        
        try:
            raw = fetch_with_retry(client, params, max_attempts=max_attempts)
            rows, problems = validate_rows(raw, interval)
            cas_saved, cas_dupes, cas_conflicts = archive_cas(db, symbol, interval, raw)
            if cas_conflicts:
                raise RuntimeError(f"Conflicting CAS candles: {cas_conflicts}")
            print(f"{symbol} {interval}: CAS archived={cas_saved} existing={cas_dupes}")
            
            received = len(rows)
            log_event(db, symbol, interval, "FETCH_ATTEMPT",
                      {"start": start_dt.isoformat(), "end": end_dt.isoformat(),
                       "expected": expected, "received": received, "depth": depth})
            
            # Detect silent truncation
            if auto_split and received < expected and received > 0 and start_dt.date() < end_dt.date():
                print(f"{symbol} {interval} {start_dt.date()}..{end_dt.date()}: "
                      f"PARTIAL (expected {expected}, got {received}); splitting...")
                
                # Binary split: try earlier half first
                mid = start_dt.date() + (end_dt.date() - start_dt.date()) // 2
                mid_dt = datetime.combine(mid, dtime(15, 15) if mid >= date(2026, 8, 3) else dtime(15, 30), IST)
                
                fetch_range(start_dt, mid_dt, depth=depth+1)
                time.sleep(pause)
                fetch_range(datetime.combine(mid + timedelta(days=1), dtime(9, 15), IST), end_dt, depth=depth+1)
                return  # Recursive calls persisted data
            
            outside = [p for p in problems if p["reason"] == "outside normal cash continuous session"]
            invalid = [p for p in problems if p["reason"] != "outside normal cash continuous session"]
            if outside:
                log_event(db, symbol, interval, "OUT_OF_SESSION_EXCLUDED",
                          {"count": len(outside), "samples": outside[:3]})
                print(f"{symbol} {interval}: excluded {len(outside)} out-of-session candles")
            if invalid:
                log_event(db, symbol, interval, "INVALID_ROWS",
                          {"count": len(invalid), "samples": invalid[:3]})
                db.commit()
                raise RuntimeError(f"Invalid broker candles: {len(invalid)}")
            if received < expected and (not auto_split or start_dt.date() == end_dt.date()):
                raise PartialDataError(f"Incomplete response: expected={expected} received={received}")

            # Full data or no data
            if received == 0 and expected == 0:
                log_event(db, symbol, interval, "FETCH", 
                          {"start": start_dt.date().isoformat(), "end": end_dt.date().isoformat(),
                           "inserted": 0, "duplicates": 0, "conflicts": 0, "rejected": 0, "reason": "no_trading_days"})
                print(f"{symbol} {interval} {start_dt.date()}..{end_dt.date()}: no trading days")
                return
            
            if received == 0 and expected > 0:
                raise RuntimeError(f"Expected {expected} candles but got 0; check date range or holiday calendar")
            
            # Persist all rows
            count, duplicates, conflicts = persist(db, symbol, interval, rows)
            log_event(db, symbol, interval, "FETCH",
                      {"start": start_dt.date().isoformat(), "end": end_dt.date().isoformat(),
                       "expected": expected, "received": received, 
                       "inserted": count, "duplicates": duplicates, "conflicts": conflicts,
                       "rejected": len(problems), "samples": problems[:3]})
            
            if conflicts > 0:
                raise RuntimeError("Integrity error: conflicting stored data; see collection_events")
            
            print(f"{symbol} {interval} {start_dt.date()}..{end_dt.date()}: "
                  f"inserted={count} dupes={duplicates} expected={expected} got={received}")
            
        except (BrokerRetryableError, BrokerPermanentError) as exc:
            log_event(db, symbol, interval, "FETCH_ERROR",
                      {"start": start_dt.date().isoformat(), "end": end_dt.date().isoformat(),
                       "error_type": type(exc).__name__, "message": str(exc)[:200]})
            raise
    
    # Calendar-day batching, splitting incomplete responses when necessary.
    batch_size = 22 if interval == "ONE_MINUTE" else 100  # calendar days
    current = start
    while current.date() <= end.date():
        batch_end = current + timedelta(days=batch_size - 1)
        if batch_end > end:
            batch_end = end
        
        try:
            fetch_range(current, batch_end)
            time.sleep(pause)
        except Exception as exc:
            log_event(db, symbol, interval, "BATCH_ERROR",
                      {"start": current.date().isoformat(), "end": batch_end.date().isoformat(),
                       "error_type": type(exc).__name__, "error": str(exc)[:200]})
            db.commit()
            raise
        
        current = datetime.combine(batch_end.date() + timedelta(days=1), dtime.min, IST)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--symbol", help="Single mapped NIFTY 50 symbol, e.g. SBIN")
    p.add_argument("--start", help="YYYY-MM-DD inclusive")
    p.add_argument("--end", help="YYYY-MM-DD inclusive")
    p.add_argument("--interval", choices=INTERVALS, default="ONE_MINUTE")
    p.add_argument("--pause", type=float, default=1.5)
    args = p.parse_args()
    if args.self_test:
        test_offline()
        return
    if not args.symbol or not args.start or not args.end or args.pause < 1:
        p.error("Fetch requires --symbol, --start, --end and --pause >= 1")
    start_date = datetime.strptime(args.start, "%Y-%m-%d").date()
    end_date = datetime.strptime(args.end, "%Y-%m-%d").date()
    if end_date < start_date or end_date >= datetime.now(IST).date():
        p.error("Use a past, completed date range (end before today)")
    instruments = load_mapping()
    symbol = args.symbol.upper()
    if symbol not in instruments:
        p.error("Symbol not in validated NIFTY 50 mapping")
    DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB) as db:
        init_db(db)
        client = authenticate()
        collect(client, db, symbol, instruments[symbol]["token"], args.interval,
                datetime.combine(start_date, dtime.min, IST),
                datetime.combine(end_date, dtime.min, IST), args.pause)

if __name__ == "__main__":
    main()