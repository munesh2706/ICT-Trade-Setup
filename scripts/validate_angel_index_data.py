#!/usr/bin/env python3
"""Read-only Angel One SmartAPI validation for NIFTY, BANKNIFTY and SENSEX.

This utility never calls any order-placement, modification, cancellation or position API.
Credentials are read only from environment variables / a local .env file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
import time
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

IST = ZoneInfo("Asia/Kolkata")
MASTER_URL = "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json"
INSTRUMENTS = {
    "NIFTY": {"name": "NIFTY 50", "exchange": "NSE", "segment": "nse_cm",
              "token": "99926000", "ws_exchange_type": 1},
    "BANKNIFTY": {"name": "BANKNIFTY", "exchange": "NSE", "segment": "nse_cm",
                  "token": "99926009", "ws_exchange_type": 1},
    "SENSEX": {"name": "SENSEX", "exchange": "BSE", "segment": "bse_cm",
               "token": "99919000", "ws_exchange_type": 3},
}
INTERVALS = {
    "ONE_MINUTE": 1,
    "FIVE_MINUTE": 5,
    "FIFTEEN_MINUTE": 15,
}
ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "data" / "reports"


def result(status: str, **kwargs):
    return {"status": status, **kwargs}


def load_credentials():
    load_dotenv(ROOT / ".env")
    required = ["ANGEL_API_KEY", "ANGEL_CLIENT_CODE", "ANGEL_PIN", "ANGEL_TOTP_SECRET"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise RuntimeError("Missing environment variables: " + ", ".join(missing) +
                           ". Copy .env.example to .env and fill it locally.")
    return {k: os.environ[k] for k in required}


def resolve_date(value: str | None) -> date:
    if value:
        return date.fromisoformat(value)
    today = datetime.now(IST).date()
    candidate = today - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def fetch_master():
    response = requests.get(MASTER_URL, timeout=30)
    response.raise_for_status()
    raw = response.content
    rows = response.json()
    if not isinstance(rows, list):
        raise RuntimeError("Instrument master did not return a JSON list.")
    digest = hashlib.sha256(raw).hexdigest()
    resolved = {}
    checks = {}
    for key, expected in INSTRUMENTS.items():
        matches = [
            row for row in rows
            if str(row.get("token", "")) == expected["token"]
            and str(row.get("exch_seg", "")).lower() == expected["segment"]
            and str(row.get("instrumenttype", "")).upper() == "AMXIDX"
        ]
        if len(matches) != 1:
            checks[key] = result("FAIL", match_count=len(matches),
                                 reason="Expected exactly one token+segment+AMXIDX match")
            continue
        row = matches[0]
        master_name = str(row.get("name", "")).upper()
        symbol = str(row.get("symbol", "")).upper()
        acceptable = {
            "NIFTY": ("NIFTY",),
            "BANKNIFTY": ("BANKNIFTY",),
            "SENSEX": ("SENSEX",),
        }[key]
        if not any(n in master_name or n in symbol for n in acceptable):
            checks[key] = result("FAIL", reason="Token matched but instrument name did not")
            continue
        resolved[key] = {**expected, "master_symbol": row.get("symbol"),
                         "master_name": row.get("name"), "token": str(row["token"])}
        checks[key] = result("PASS", symbol=row.get("symbol"), name=row.get("name"),
                             exchange_segment=row.get("exch_seg"),
                             instrument_type=row.get("instrumenttype"))
    return resolved, {"status": "PASS" if len(resolved) == 3 else "FAIL",
                      "retrieved_at_ist": datetime.now(IST).isoformat(),
                      "sha256": digest, "row_count": len(rows), "instruments": checks}


def parse_candles(payload):
    if not isinstance(payload, dict) or payload.get("status") is not True:
        msg = payload.get("message", "Unknown API response") if isinstance(payload, dict) else "Non-JSON response"
        code = payload.get("errorcode") if isinstance(payload, dict) else None
        raise RuntimeError(f"Historical API rejected request: {msg} ({code})")
    rows = (payload.get("data") or [])
    parsed = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        ts = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=IST)
        ts = ts.astimezone(IST)
        vals = [float(row[i]) for i in range(1, 5)]
        volume = float(row[5])
        parsed.append({"timestamp": ts, "open": vals[0], "high": vals[1],
                       "low": vals[2], "close": vals[3], "volume": volume})
    return parsed


def audit_candles(candles, minutes, session_date):
    if not candles:
        return result("FAIL", reason="No candles returned", count=0)
    times = [c["timestamp"] for c in candles]
    duplicates = len(times) - len(set(times))
    monotonic = all(a < b for a, b in zip(times, times[1:]))
    invalid_ohlc = []
    outside = []
    future = []
    for c in candles:
        o, h, l, cl = c["open"], c["high"], c["low"], c["close"]
        if not all(map(lambda x: x == x and abs(x) != float("inf"), [o, h, l, cl])):
            invalid_ohlc.append(c["timestamp"].isoformat())
        elif h < max(o, cl, l) or l > min(o, cl, h) or min(o, h, l, cl) <= 0:
            invalid_ohlc.append(c["timestamp"].isoformat())
        if c["volume"] < 0:
            invalid_ohlc.append(c["timestamp"].isoformat())
        if c["timestamp"].date() != session_date or not (
            dtime(9, 15) <= c["timestamp"].time().replace(tzinfo=None) < dtime(15, 30)
        ):
            outside.append(c["timestamp"].isoformat())
        if c["timestamp"] > datetime.now(IST) + timedelta(minutes=1):
            future.append(c["timestamp"].isoformat())
    expected = int((15 * 60 + 30 - (9 * 60 + 15)) / minutes)
    # Do not label missing bars as definitive until the exchange calendar/halts are checked.
    return result("PASS" if not duplicates and monotonic and not invalid_ohlc and not outside and not future else "FAIL",
                  count=len(candles), duplicates=duplicates, strictly_increasing=monotonic,
                  invalid_ohlc_or_volume=invalid_ohlc[:10], out_of_session=outside[:10],
                  future_timestamps=future[:10], first=times[0].isoformat(),
                  last=times[-1].isoformat(), expected_full_session_bar_count=expected,
                  observed_bar_count=len(candles),
                  note="Bar-count shortfall is a gap candidate, not proof of missing data until holidays, halts and session exceptions are excluded.")


def aggregate_from_1m(candles, minutes):
    buckets = {}
    for c in candles:
        minute_of_day = c["timestamp"].hour * 60 + c["timestamp"].minute
        anchor = 9 * 60 + 15
        bucket_minute = anchor + ((minute_of_day - anchor) // minutes) * minutes
        start = c["timestamp"].replace(hour=bucket_minute // 60,
                                       minute=bucket_minute % 60, second=0, microsecond=0)
        b = buckets.setdefault(start, {"timestamp": start, "open": c["open"],
                                       "high": c["high"], "low": c["low"],
                                       "close": c["close"], "volume": 0.0, "n": 0})
        b["high"] = max(b["high"], c["high"])
        b["low"] = min(b["low"], c["low"])
        b["close"] = c["close"]
        b["volume"] += c["volume"]
        b["n"] += 1
    return buckets


def compare_aggregates(one_minute, provider, minutes):
    agg = aggregate_from_1m(one_minute, minutes)
    by_time = {c["timestamp"]: c for c in provider}
    compared = 0
    mismatches = []
    for ts, a in agg.items():
        p = by_time.get(ts)
        if not p:
            continue
        compared += 1
        fields = {}
        for k in ("open", "high", "low", "close"):
            if abs(a[k] - p[k]) > max(0.02, abs(p[k]) * 1e-6):
                fields[k] = {"aggregated_1m": a[k], "provider": p[k]}
        if fields:
            mismatches.append({"timestamp": ts.isoformat(), "differences": fields})
    return result("PASS" if compared and not mismatches else ("WARN" if compared else "FAIL"),
                  matched_buckets=compared, aggregate_buckets=len(agg),
                  provider_buckets=len(provider), mismatch_count=len(mismatches),
                  examples=mismatches[:5],
                  note="OHLC comparison only; volume may be unavailable or differently defined for index candles. Differences are reported, never overwritten.")


def run_websocket(api, creds, instruments, seconds):
    from SmartApi.smartWebSocketV2 import SmartWebSocketV2
    received = []
    errors = []
    opened = threading.Event()
    got_packet = threading.Event()
    ws = SmartWebSocketV2(api.access_token, creds["ANGEL_API_KEY"],
                          creds["ANGEL_CLIENT_CODE"], api.feed_token,
                          max_retry_attempt=0)

    def on_open(wsapp):
        opened.set()
        token_list = [
            {"exchangeType": 1, "tokens": [instruments["NIFTY"]["token"],
                                             instruments["BANKNIFTY"]["token"]]},
            {"exchangeType": 3, "tokens": [instruments["SENSEX"]["token"]]},
        ]
        ws.subscribe("ICTDATATEST", 1, token_list)

    def on_data(wsapp, packet):
        # The SDK decodes binary packets into a dictionary.
        if isinstance(packet, dict):
            received.append({
                "exchange_type": packet.get("exchange_type"),
                "token": str(packet.get("token", "")),
                "exchange_timestamp": packet.get("exchange_timestamp"),
                "ltp": packet.get("last_traded_price"),
            })
            got_packet.set()

    def on_error(*args):
        errors.append("WebSocket callback error")

    ws.on_open = on_open
    ws.on_data = on_data
    ws.on_error = on_error
    thread = threading.Thread(target=ws.connect, daemon=True)
    thread.start()
    opened.wait(timeout=10)
    got_packet.wait(timeout=seconds)
    try:
        ws.close_connection()
    except Exception:
        pass
    thread.join(timeout=3)

    expected = {
        (1, instruments["NIFTY"]["token"]),
        (1, instruments["BANKNIFTY"]["token"]),
        (3, instruments["SENSEX"]["token"]),
    }
    seen = {(p["exchange_type"], p["token"]) for p in received}
    return result("PASS" if expected.issubset(seen) else "WARN",
                  connected=opened.is_set(), packets=len(received),
                  instruments_seen=[{"exchange_type": x, "token": t} for x, t in sorted(seen)],
                  missing=[{"exchange_type": x, "token": t} for x, t in sorted(expected - seen)],
                  callback_errors=errors,
                  note="A missing packet outside active market hours is inconclusive. Run during NSE/BSE market hours; this short probe does not validate continuous-feed reliability.")


def main():
    parser = argparse.ArgumentParser(description="Read-only Angel One index feed validation")
    parser.add_argument("--date", help="Trading date YYYY-MM-DD to validate (IST). Defaults to previous weekday; specify a known trading day.")
    parser.add_argument("--skip-websocket", action="store_true", help="Skip live WebSocket probe.")
    parser.add_argument("--ws-seconds", type=int, default=15, help="Seconds to wait for WebSocket packets (default: 15).")
    parser.add_argument("--no-quote", action="store_true", help="Skip live quote endpoint probe.")
    args = parser.parse_args()

    report = {"started_at_ist": datetime.now(IST).isoformat(),
              "scope": list(INSTRUMENTS), "orders_placed": False, "checks": {}}
    try:
        creds = load_credentials()
        from SmartApi import SmartConnect
        import pyotp
        instruments, master_report = fetch_master()
        report["checks"]["instrument_master"] = master_report
        if len(instruments) != 3:
            raise RuntimeError("Instrument-master validation failed; refusing to use hard-coded fallback tokens.")

        api = SmartConnect(creds["ANGEL_API_KEY"])
        login = api.generateSession(creds["ANGEL_CLIENT_CODE"], creds["ANGEL_PIN"],
                                    pyotp.TOTP(creds["ANGEL_TOTP_SECRET"]).now())
        if not isinstance(login, dict) or login.get("status") is not True:
            raise RuntimeError("SmartAPI login failed. Check account/API credentials, PIN and TOTP clock.")
        report["checks"]["authentication"] = result("PASS", message="Authenticated; secrets redacted")

        session_day = resolve_date(args.date)
        report["session_date"] = session_day.isoformat()
        start = datetime.combine(session_day, dtime(9, 15)).strftime("%Y-%m-%d %H:%M")
        end = datetime.combine(session_day, dtime(15, 30)).strftime("%Y-%m-%d %H:%M")
        candle_store = {}
        hist = {}
        for key, inst in instruments.items():
            hist[key] = {}
            for interval, mins in INTERVALS.items():
                try:
                    payload = api.getCandleData({
                        "exchange": inst["exchange"], "symboltoken": inst["token"],
                        "interval": interval, "fromdate": start, "todate": end,
                    })
                    candles = parse_candles(payload)
                    audit = audit_candles(candles, mins, session_day)
                    hist[key][interval] = audit
                    candle_store[(key, interval)] = candles
                except Exception as exc:
                    hist[key][interval] = result("FAIL", error=str(exc)[:300])
            one = candle_store.get((key, "ONE_MINUTE"), [])
            for interval, mins in (("FIVE_MINUTE", 5), ("FIFTEEN_MINUTE", 15)):
                provider = candle_store.get((key, interval), [])
                hist[key][interval + "_vs_1m"] = compare_aggregates(one, provider, mins) if one and provider else result("FAIL", reason="Cannot compare: 1m or provider timeframe data missing")
        report["checks"]["historical_candles"] = hist

        if not args.no_quote:
            quotes = {}
            tokens_by_exchange = {"NSE": [instruments["NIFTY"]["token"], instruments["BANKNIFTY"]["token"]],
                                  "BSE": [instruments["SENSEX"]["token"]]}
            try:
                q = api.getMarketData("FULL", tokens_by_exchange)
                if q.get("status") is not True:
                    raise RuntimeError(f"Quote API rejected request: {q.get('message')} ({q.get('errorcode')})")
                data = q.get("data") or {}
                fetched = data.get("fetched") or []
                unfetched = data.get("unfetched") or []
                for key, inst in instruments.items():
                    matches = [x for x in fetched
                               if str(x.get("symbolToken", x.get("symboltoken", ""))) == inst["token"]]
                    row = matches[0] if len(matches) == 1 else {}
                    exchange_ok = str(row.get("exchange", "")).upper() == inst["exchange"]
                    try:
                        ltp = float(row.get("ltp", 0))
                    except (TypeError, ValueError):
                        ltp = 0.0
                    checks_ok = len(matches) == 1 and exchange_ok and ltp > 0
                    quotes[key] = result("PASS" if checks_ok else "WARN",
                                         matched_count=len(matches), exchange_matches=exchange_ok,
                                         ltp_present=ltp > 0 if row else False,
                                         feed_time=row.get("exchFeedTime"),
                                         unfetched_count=len(unfetched),
                                         reason=None if checks_ok else "Expected exactly one token match with correct exchange and positive LTP")
            except Exception as exc:
                quotes = {k: result("FAIL", error=str(exc)[:300]) for k in instruments}
            report["checks"]["live_quotes"] = quotes

        if not args.skip_websocket:
            try:
                report["checks"]["websocket"] = run_websocket(api, creds, instruments, max(1, args.ws_seconds))
            except Exception as exc:
                report["checks"]["websocket"] = result("FAIL", error=str(exc)[:300])

        report["finished_at_ist"] = datetime.now(IST).isoformat()
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        out = REPORT_DIR / f"angel_index_validation_{datetime.now(IST).strftime('%Y%m%d_%H%M%S')}.json"
        out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(json.dumps(report, indent=2, default=str))
        print(f"\nSanitized report saved to: {out}")
        return 0
    except Exception as exc:
        report["fatal_error"] = str(exc)
        report["finished_at_ist"] = datetime.now(IST).isoformat()
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        out = REPORT_DIR / f"angel_index_validation_{datetime.now(IST).strftime('%Y%m%d_%H%M%S')}.json"
        out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(json.dumps(report, indent=2, default=str))
        print(f"\nReport saved to: {out}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
