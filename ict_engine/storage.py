"""Snapshot-versioned SQLite storage for canonical index candles."""
from __future__ import annotations
import sqlite3
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Sequence
from .models import Candle

class CandleConflict(RuntimeError):
    """Same instrument/timeframe/time/snapshot arrived with different values."""

def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")

class CandleStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._initialize()

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def _initialize(self):
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS candle_snapshots (
                snapshot_id TEXT PRIMARY KEY, created_at_utc TEXT NOT NULL,
                description TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN')""")
            columns = {row[1] for row in db.execute("PRAGMA table_info(candle_snapshots)").fetchall()}
            if "status" not in columns:
                db.execute("ALTER TABLE candle_snapshots ADD COLUMN status TEXT NOT NULL DEFAULT 'OPEN'")
            db.execute("""CREATE TABLE IF NOT EXISTS candles (
                instrument_id TEXT NOT NULL, timeframe TEXT NOT NULL,
                start_utc TEXT NOT NULL, snapshot_id TEXT NOT NULL,
                open TEXT NOT NULL, high TEXT NOT NULL, low TEXT NOT NULL,
                close TEXT NOT NULL, volume TEXT NOT NULL, source TEXT NOT NULL,
                PRIMARY KEY(instrument_id,timeframe,start_utc,snapshot_id),
                FOREIGN KEY(snapshot_id) REFERENCES candle_snapshots(snapshot_id))""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_candles_lookup ON candles(instrument_id,timeframe,snapshot_id,start_utc)")
            db.execute("""CREATE TABLE IF NOT EXISTS raw_batches (
                snapshot_id TEXT NOT NULL, batch_no INTEGER NOT NULL,
                instrument_id TEXT NOT NULL, timeframe TEXT NOT NULL,
                fetched_at_utc TEXT NOT NULL, request_json TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY(snapshot_id,batch_no),
                FOREIGN KEY(snapshot_id) REFERENCES candle_snapshots(snapshot_id))""")

    def create_snapshot(self, snapshot_id: str, *, description: str = "") -> None:
        if not snapshot_id.strip():
            raise ValueError("snapshot_id cannot be empty")
        with self._connect() as db:
            db.execute("INSERT INTO candle_snapshots(snapshot_id,created_at_utc,description,status) VALUES (?,?,?,'OPEN')",
                       (snapshot_id, datetime.now(timezone.utc).isoformat(), description))

    def finalize_snapshot(self, snapshot_id: str, *, status: str, description: str | None = None) -> None:
        if status not in {"ACQUIRED", "VERIFIED", "FAILED"}:
            raise ValueError("status must be ACQUIRED, VERIFIED or FAILED")
        with self._connect() as db:
            current = db.execute("SELECT status FROM candle_snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
            allowed = {"OPEN": {"ACQUIRED", "FAILED"}, "ACQUIRED": {"VERIFIED", "FAILED"}}
            if current is None or status not in allowed.get(current[0], set()):
                raise ValueError("invalid snapshot status transition")
            if description is None:
                updated = db.execute("UPDATE candle_snapshots SET status=? WHERE snapshot_id=?", (status, snapshot_id)).rowcount
            else:
                updated = db.execute("UPDATE candle_snapshots SET status=?, description=? WHERE snapshot_id=?", (status, description, snapshot_id)).rowcount
            if updated != 1:
                raise ValueError("snapshot does not exist or could not be finalized")

    def snapshot_status(self, snapshot_id: str) -> str:
        with self._connect() as db:
            row = db.execute("SELECT status FROM candle_snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
        if row is None:
            raise ValueError("unknown snapshot_id")
        return row[0]

    def store_raw_batch(self, snapshot_id: str, batch_no: int, instrument_id: str, timeframe: str,
                        fetched_at: datetime, request_params: dict, payload: dict) -> None:
        """Persist the successful/failed provider response without auth material."""
        if batch_no < 0:
            raise ValueError("batch_no must be non-negative")
        allowed_params = {"exchange", "symboltoken", "interval", "fromdate", "todate"}
        if set(request_params) - allowed_params:
            raise ValueError("raw request metadata contains an unapproved field")
        request_json = json.dumps(request_params, sort_keys=True, separators=(",", ":"))
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        fetched_utc = _utc_iso(fetched_at)
        with self._connect() as db:
            snapshot = db.execute("SELECT status FROM candle_snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
            if snapshot is None or snapshot[0] != "OPEN":
                raise ValueError("raw batches can only be added to an OPEN snapshot")
            existing = db.execute("SELECT instrument_id,timeframe,fetched_at_utc,request_json,payload_json FROM raw_batches WHERE snapshot_id=? AND batch_no=?", (snapshot_id, batch_no)).fetchone()
            row = (instrument_id, timeframe, fetched_utc, request_json, payload_json)
            if existing is not None:
                if tuple(existing) != row:
                    raise CandleConflict(f"raw batch conflict at batch {batch_no}")
                return
            db.execute("INSERT INTO raw_batches(snapshot_id,batch_no,instrument_id,timeframe,fetched_at_utc,request_json,payload_json) VALUES (?,?,?,?,?,?,?)",
                       (snapshot_id, batch_no, *row))

    def load_raw_batches(self, snapshot_id: str) -> list[dict]:
        with self._connect() as db:
            rows = db.execute("SELECT batch_no,instrument_id,timeframe,fetched_at_utc,request_json,payload_json FROM raw_batches WHERE snapshot_id=? ORDER BY batch_no", (snapshot_id,)).fetchall()
        return [{"batch_no": r[0], "instrument_id": r[1], "timeframe": r[2], "fetched_at_utc": r[3],
                 "request": json.loads(r[4]), "payload": json.loads(r[5])} for r in rows]

    def store_candles(self, instrument_id: str, timeframe: str, snapshot_id: str, source: str, candles: Sequence[Candle]) -> int:
        """Insert immutable rows atomically; identical repeats are idempotent.

        A provider revision must use a new snapshot_id. Conflicting data inside
        one snapshot is rejected rather than silently overwriting backtest input.
        """
        if not all(x.strip() for x in (instrument_id, timeframe, snapshot_id, source)):
            raise ValueError("instrument, timeframe, snapshot and source are required")
        if not candles:
            return 0
        stamps = [_utc_iso(c.timestamp) for c in candles]
        if any(stamps[i] >= stamps[i + 1] for i in range(len(stamps) - 1)):
            raise ValueError("candle batch must be strictly chronological and duplicate-free")
        rows = [(instrument_id, timeframe, stamp, snapshot_id, str(c.open), str(c.high), str(c.low), str(c.close), str(c.volume), source) for stamp, c in zip(stamps, candles)]
        inserted = 0
        with self._connect() as db:
            snapshot = db.execute("SELECT status FROM candle_snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
            if snapshot is None:
                raise ValueError("snapshot_id must be created before storing candles")
            if snapshot[0] != "OPEN":
                raise ValueError("candles can only be added to an OPEN snapshot")
            for row in rows:
                existing = db.execute("""SELECT open,high,low,close,volume,source FROM candles WHERE instrument_id=? AND timeframe=? AND start_utc=? AND snapshot_id=?""", row[:4]).fetchone()
                if existing is not None:
                    if tuple(existing) != row[4:]:
                        raise CandleConflict(f"immutable candle conflict at {row[2]}")
                    continue
                db.execute("""INSERT INTO candles (instrument_id,timeframe,start_utc,snapshot_id,open,high,low,close,volume,source) VALUES (?,?,?,?,?,?,?,?,?,?)""", row)
                inserted += 1
        return inserted

    def load_candles(self, instrument_id: str, timeframe: str, snapshot_id: str, start: datetime | None = None, end: datetime | None = None, *, allow_incomplete: bool = False) -> list[Candle]:
        status = self.snapshot_status(snapshot_id)
        if status != "VERIFIED" and not allow_incomplete:
            raise ValueError(f"snapshot {snapshot_id} is not VERIFIED")
        query = "SELECT start_utc,open,high,low,close,volume FROM candles WHERE instrument_id=? AND timeframe=? AND snapshot_id=?"
        params: list[object] = [instrument_id, timeframe, snapshot_id]
        if start is not None:
            query += " AND start_utc>=?"
            params.append(_utc_iso(start))
        if end is not None:
            query += " AND start_utc<?"
            params.append(_utc_iso(end))
        query += " ORDER BY start_utc"
        with self._connect() as db:
            rows = db.execute(query, params).fetchall()
        return [Candle(datetime.fromisoformat(r[0]), Decimal(r[1]), Decimal(r[2]), Decimal(r[3]), Decimal(r[4]), Decimal(r[5])) for r in rows]