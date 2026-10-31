"""Snapshot-versioned SQLite storage for canonical index candles."""
from __future__ import annotations
import sqlite3
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

    def create_snapshot(self, snapshot_id: str, *, description: str = "") -> None:
        if not snapshot_id.strip():
            raise ValueError("snapshot_id cannot be empty")
        with self._connect() as db:
            db.execute("INSERT INTO candle_snapshots(snapshot_id,created_at_utc,description,status) VALUES (?,?,?,'OPEN')",
                       (snapshot_id, datetime.now(timezone.utc).isoformat(), description))

    def finalize_snapshot(self, snapshot_id: str, *, status: str, description: str | None = None) -> None:
        if status not in {"COMPLETE", "FAILED"}:
            raise ValueError("final status must be COMPLETE or FAILED")
        with self._connect() as db:
            if description is None:
                updated = db.execute("UPDATE candle_snapshots SET status=? WHERE snapshot_id=? AND status='OPEN'", (status, snapshot_id)).rowcount
            else:
                updated = db.execute("UPDATE candle_snapshots SET status=?, description=? WHERE snapshot_id=? AND status='OPEN'", (status, description, snapshot_id)).rowcount
            if updated != 1:
                raise ValueError("snapshot does not exist or is already finalized")

    def snapshot_status(self, snapshot_id: str) -> str:
        with self._connect() as db:
            row = db.execute("SELECT status FROM candle_snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
        if row is None:
            raise ValueError("unknown snapshot_id")
        return row[0]

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
        if status != "COMPLETE" and not allow_incomplete:
            raise ValueError(f"snapshot {snapshot_id} is not COMPLETE")
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