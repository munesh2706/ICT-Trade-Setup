"""Immutable SQLite storage for NIFTY 50 stock candles and reconciliation batches."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Sequence

from .models import Candle

class StockStoreError(RuntimeError):
    pass

def _utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")

class StockCandleStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._init()

    def _db(self):
        db = sqlite3.connect(self.path, timeout=45)
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def _init(self):
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS stock_snapshots(
                snapshot_id TEXT PRIMARY KEY, universe_snapshot_id TEXT NOT NULL,
                created_at_utc TEXT NOT NULL, status TEXT NOT NULL,
                description TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS stock_candles(
                symbol TEXT NOT NULL, timeframe TEXT NOT NULL, start_utc TEXT NOT NULL,
                snapshot_id TEXT NOT NULL, token TEXT NOT NULL, open TEXT NOT NULL,
                high TEXT NOT NULL, low TEXT NOT NULL, close TEXT NOT NULL,
                volume TEXT NOT NULL, source TEXT NOT NULL,
                PRIMARY KEY(symbol,timeframe,start_utc,snapshot_id),
                FOREIGN KEY(snapshot_id) REFERENCES stock_snapshots(snapshot_id))""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_stock_candles ON stock_candles(symbol,timeframe,start_utc)")
            db.execute("""CREATE TABLE IF NOT EXISTS stock_raw_batches(
                snapshot_id TEXT NOT NULL, batch_no INTEGER NOT NULL, symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL, token TEXT NOT NULL, fetched_at_utc TEXT NOT NULL,
                request_json TEXT NOT NULL, payload_json TEXT NOT NULL,
                PRIMARY KEY(snapshot_id,batch_no),
                FOREIGN KEY(snapshot_id) REFERENCES stock_snapshots(snapshot_id))""")

    def create_snapshot(self, snapshot_id: str, universe_snapshot_id: str, description: str = ""):
        with self._db() as db:
            db.execute("INSERT INTO stock_snapshots VALUES(?,?,?,?,?)", (
                snapshot_id, universe_snapshot_id, datetime.now(timezone.utc).isoformat(),
                "OPEN", description,
            ))

    def snapshot_status(self, snapshot_id: str) -> str:
        with self._db() as db:
            row = db.execute("SELECT status FROM stock_snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
        if not row:
            raise StockStoreError(f"unknown snapshot: {snapshot_id}")
        return row[0]

    def finalize(self, snapshot_id: str, status: str, description: str | None = None):
        if status not in {"ACQUIRED", "VERIFIED", "FAILED"}:
            raise ValueError("invalid snapshot status")
        with self._db() as db:
            row = db.execute("SELECT status FROM stock_snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
            allowed = {"OPEN": {"ACQUIRED", "FAILED"}, "ACQUIRED": {"VERIFIED", "FAILED"}}
            if not row or status not in allowed.get(row[0], set()):
                raise StockStoreError("invalid stock snapshot state transition")
            if description is None:
                db.execute("UPDATE stock_snapshots SET status=? WHERE snapshot_id=?", (status, snapshot_id))
            else:
                db.execute("UPDATE stock_snapshots SET status=?,description=? WHERE snapshot_id=?", (status, description, snapshot_id))

    def store_raw(self, snapshot_id: str, batch_no: int, symbol: str, timeframe: str,
                  token: str, fetched_at: datetime, request: dict, payload: dict):
        safe_keys = {"exchange", "symboltoken", "interval", "fromdate", "todate"}
        if set(request) - safe_keys:
            raise ValueError("request metadata contains unexpected fields")
        with self._db() as db:
            state = db.execute("SELECT status FROM stock_snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
            if not state or state[0] != "OPEN":
                raise StockStoreError("raw batches can only be written to OPEN snapshots")
            db.execute("INSERT INTO stock_raw_batches VALUES(?,?,?,?,?,?,?,?)", (
                snapshot_id, batch_no, symbol, timeframe, token, _utc(fetched_at),
                json.dumps(request, sort_keys=True, separators=(",", ":")),
                json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str),
            ))

    def store_candles(self, snapshot_id: str, symbol: str, timeframe: str, token: str,
                      candles: Sequence[Candle], source: str = "ANGEL_HISTORICAL") -> int:
        if not candles:
            return 0
        stamps = [_utc(c.timestamp) for c in candles]
        if any(stamps[i] >= stamps[i+1] for i in range(len(stamps)-1)):
            raise ValueError("candles must be strictly chronological and duplicate-free")
        inserted = 0
        with self._db() as db:
            state = db.execute("SELECT status FROM stock_snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
            if not state or state[0] != "OPEN":
                raise StockStoreError("candles can only be written to OPEN snapshots")
            for stamp, candle in zip(stamps, candles):
                values = (str(candle.open), str(candle.high), str(candle.low), str(candle.close), str(candle.volume), source)
                existing = db.execute("""SELECT open,high,low,close,volume,source FROM stock_candles
                    WHERE symbol=? AND timeframe=? AND start_utc=? AND snapshot_id=?""",
                    (symbol, timeframe, stamp, snapshot_id)).fetchone()
                if existing:
                    if tuple(existing) != values:
                        raise StockStoreError(f"immutable candle conflict {symbol}/{timeframe}/{stamp}")
                    continue
                db.execute("INSERT INTO stock_candles VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
                    symbol, timeframe, stamp, snapshot_id, token, *values,
                ))
                inserted += 1
        return inserted

    def _load(self, symbol: str, timeframe: str, statuses: tuple[str, ...],
              start: datetime | None = None, end: datetime | None = None,
              acquired_universe_id: str | None = None, limit: int | None = None) -> list[Candle]:
        if limit is not None and limit < 1:
            raise ValueError("limit must be positive")
        placeholders = ",".join("?" for _ in statuses)
        if acquired_universe_id is not None:
            where = """c.symbol=? AND c.timeframe=?
                AND (s.status='VERIFIED' OR (s.status='ACQUIRED' AND s.universe_snapshot_id=?))"""
            params: list[object] = [symbol, timeframe, acquired_universe_id]
        else:
            where = f"c.symbol=? AND c.timeframe=? AND s.status IN ({placeholders})"
            params = [symbol, timeframe, *statuses]
        if start is not None:
            where += " AND c.start_utc>=?"
            params.append(_utc(start))
        if end is not None:
            where += " AND c.start_utc<?"
            params.append(_utc(end))
        sql = f"""SELECT start_utc,open,high,low,close,volume FROM (
            SELECT c.start_utc,c.open,c.high,c.low,c.close,c.volume,
                   ROW_NUMBER() OVER (PARTITION BY c.start_utc ORDER BY s.created_at_utc DESC) AS rn
            FROM stock_candles c JOIN stock_snapshots s ON s.snapshot_id=c.snapshot_id
            WHERE {where}
        ) WHERE rn=1 ORDER BY start_utc DESC"""
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with self._db() as db:
            rows = db.execute(sql, params).fetchall()
        rows.reverse()
        return [Candle(datetime.fromisoformat(r[0]), Decimal(r[1]), Decimal(r[2]),
                       Decimal(r[3]), Decimal(r[4]), Decimal(r[5])) for r in rows]

    def load_verified_candles(self, symbol: str, timeframe: str,
                              start: datetime | None = None, end: datetime | None = None,
                              limit: int | None = None) -> list[Candle]:
        return self._load(symbol, timeframe, ("VERIFIED",), start, end, limit=limit)

    def load_reconciliation_candles(self, symbol: str, timeframe: str,
                                   start: datetime | None = None, end: datetime | None = None,
                                   universe_snapshot_id: str | None = None) -> list[Candle]:
        if universe_snapshot_id is None:
            raise ValueError("universe_snapshot_id is required to include unverified acquisition data")
        return self._load(symbol, timeframe, ("VERIFIED",), start, end, universe_snapshot_id)

    def mark_universe_snapshots_verified(self, universe_snapshot_id: str):
        with self._db() as db:
            db.execute("""UPDATE stock_snapshots SET status='VERIFIED'
                WHERE universe_snapshot_id=? AND status='ACQUIRED'""", (universe_snapshot_id,))


    def mark_series_snapshots_verified(self, universe_snapshot_id: str, symbol: str, timeframe: str):
        """Verify staged snapshots containing only one audited stock/timeframe.

        Used by the intraday incremental refresh path. Multi-series pre-market
        snapshots are verified only by the all-universe reconciliation gate.
        """
        with self._db() as db:
            rows = db.execute("""SELECT s.snapshot_id
                FROM stock_snapshots s
                WHERE s.universe_snapshot_id=? AND s.status='ACQUIRED'
                AND EXISTS (SELECT 1 FROM stock_candles c WHERE c.snapshot_id=s.snapshot_id)
                AND NOT EXISTS (
                    SELECT 1 FROM stock_candles c
                    WHERE c.snapshot_id=s.snapshot_id
                    AND (c.symbol<>? OR c.timeframe<>?)
                )""", (universe_snapshot_id, symbol, timeframe)).fetchall()
            for (snapshot_id,) in rows:
                db.execute("UPDATE stock_snapshots SET status='VERIFIED' WHERE snapshot_id=?", (snapshot_id,))

    def pending_snapshots(self, universe_snapshot_id: str) -> list[str]:
        with self._db() as db:
            rows = db.execute("""SELECT snapshot_id FROM stock_snapshots
                WHERE universe_snapshot_id=? AND status='ACQUIRED' ORDER BY created_at_utc""",
                (universe_snapshot_id,)).fetchall()
        return [x[0] for x in rows]
