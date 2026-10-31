"""Persistent SQLite signal/event journal and broker-free paper-position store."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from .risk_controls import DailyRiskState
from .signal_lifecycle import ALLOWED, TERMINAL, SignalStatus
from .trade_simulator import PaperExit, PaperPosition

def _utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")

class StockPaperStore:
    """Restart-safe signal journal, event log, paper positions and daily risk."""

    def __init__(self, database: str | Path):
        self.database = str(database)
        self._initialize()

    def _connect(self):
        db = sqlite3.connect(self.database, timeout=30)
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def _initialize(self):
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS paper_signals (
                signal_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, model_id TEXT NOT NULL,
                direction TEXT NOT NULL, status TEXT NOT NULL, available_at_utc TEXT NOT NULL,
                evidence_json TEXT NOT NULL, created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS paper_signal_events (
                event_id TEXT PRIMARY KEY, signal_id TEXT NOT NULL, timestamp_utc TEXT NOT NULL,
                target_status TEXT NOT NULL, reason TEXT NOT NULL, evidence_ref TEXT,
                payload_json TEXT NOT NULL,
                FOREIGN KEY(signal_id) REFERENCES paper_signals(signal_id)
            )""")
            db.execute("""CREATE INDEX IF NOT EXISTS idx_paper_events_signal
                ON paper_signal_events(signal_id,timestamp_utc)""")
            db.execute("""CREATE TABLE IF NOT EXISTS paper_positions (
                position_id TEXT PRIMARY KEY, signal_id TEXT NOT NULL UNIQUE,
                symbol TEXT NOT NULL, model_id TEXT NOT NULL, direction TEXT NOT NULL,
                entry_time_utc TEXT NOT NULL, entry_price TEXT NOT NULL, stop TEXT NOT NULL,
                target TEXT NOT NULL, quantity TEXT NOT NULL, point_value TEXT NOT NULL,
                fees_per_unit TEXT NOT NULL, slippage_points TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'OPEN',
                exit_time_utc TEXT, exit_price TEXT, exit_reason TEXT,
                gross_pnl TEXT, fees TEXT, slippage_cost TEXT, net_pnl TEXT,
                ambiguous_bar INTEGER, gap_through_stop INTEGER, r_multiple TEXT,
                duration_minutes INTEGER, last_processed_bar_utc TEXT,
                FOREIGN KEY(signal_id) REFERENCES paper_signals(signal_id)
            )""")
            columns = {row[1] for row in db.execute("PRAGMA table_info(paper_positions)").fetchall()}
            if "last_processed_bar_utc" not in columns:
                db.execute("ALTER TABLE paper_positions ADD COLUMN last_processed_bar_utc TEXT")
            db.execute("""CREATE TABLE IF NOT EXISTS paper_daily_risk (
                risk_date TEXT PRIMARY KEY, equity TEXT NOT NULL, realized_pnl TEXT NOT NULL,
                open_positions INTEGER NOT NULL, trades_today INTEGER NOT NULL,
                consecutive_losses INTEGER NOT NULL, updated_at_utc TEXT NOT NULL
            )""")

    def register_signal(self, signal, *, evidence: dict, observed_at: datetime) -> bool:
        """Create a signal once, then apply source scanner lifecycle events idempotently."""
        observed = _utc(observed_at)
        available = _utc(signal.available_at)
        evidence_json = json.dumps(evidence, sort_keys=True, separators=(",", ":"), default=str)
        with self._connect() as db:
            cur = db.execute("""INSERT OR IGNORE INTO paper_signals
                (signal_id,symbol,model_id,direction,status,available_at_utc,evidence_json,created_at_utc,updated_at_utc)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (signal.signal_id, signal.symbol, signal.model_id, signal.direction,
                 SignalStatus.WATCHING.value, available, evidence_json, observed, observed))
            created = cur.rowcount == 1
            if not created:
                db.execute("UPDATE paper_signals SET evidence_json=?,updated_at_utc=? WHERE signal_id=?",
                           (evidence_json, observed, signal.signal_id))
        current = SignalStatus.WATCHING if created else self.signal_status(signal.signal_id)
        changed = created
        if current == SignalStatus.WATCHING:
            changed = self.append_event(
                f"{signal.signal_id}:qualified", signal.signal_id, observed_at,
                SignalStatus.QUALIFIED, "ICT model conditions confirmed", evidence_ref=signal.source_id,
            ) or changed
            current = self.signal_status(signal.signal_id)
        if signal.status == "ENTRY_ARMED" and current == SignalStatus.QUALIFIED:
            changed = self.append_event(
                f"{signal.signal_id}:entry-armed", signal.signal_id,
                observed_at, SignalStatus.ENTRY_ARMED,
                "FVG zone established; paper limit order armed", evidence_ref=signal.source_id,
            ) or changed
        return changed

    def append_event(self, event_id: str, signal_id: str, timestamp: datetime,
                     target_status: SignalStatus, reason: str, *,
                     evidence_ref: str | None = None, payload: dict | None = None) -> bool:
        if not event_id.strip() or not reason.strip():
            raise ValueError("event_id and reason are required")
        stamp = _utc(timestamp)
        encoded = json.dumps(payload or {}, sort_keys=True, separators=(",", ":"), default=str)
        with self._connect() as db:
            if db.execute("SELECT 1 FROM paper_signal_events WHERE event_id=?", (event_id,)).fetchone():
                return False
            row = db.execute("SELECT status FROM paper_signals WHERE signal_id=?", (signal_id,)).fetchone()
            if row is None:
                raise ValueError("unknown signal_id")
            current = SignalStatus(row[0])
            if current in TERMINAL or target_status not in ALLOWED.get(current, set()):
                raise ValueError(f"invalid signal transition: {current.value} -> {target_status.value}")
            previous = db.execute(
                "SELECT timestamp_utc FROM paper_signal_events WHERE signal_id=? ORDER BY timestamp_utc DESC,rowid DESC LIMIT 1",
                (signal_id,),
            ).fetchone()
            if previous and stamp < previous[0]:
                raise ValueError("signal events must be chronological")
            db.execute("""INSERT INTO paper_signal_events
                (event_id,signal_id,timestamp_utc,target_status,reason,evidence_ref,payload_json)
                VALUES (?,?,?,?,?,?,?)""",
                (event_id, signal_id, stamp, target_status.value, reason, evidence_ref, encoded))
            db.execute("UPDATE paper_signals SET status=?,updated_at_utc=? WHERE signal_id=?",
                       (target_status.value, stamp, signal_id))
        return True

    def pending_signals(self) -> list[dict]:
        with self._connect() as db:
            rows = db.execute("""SELECT signal_id,status,created_at_utc FROM paper_signals
                WHERE status IN (?,?,?) ORDER BY created_at_utc""",
                (SignalStatus.WATCHING.value, SignalStatus.QUALIFIED.value, SignalStatus.ENTRY_ARMED.value)).fetchall()
        return [{"signal_id": r[0], "status": r[1], "created_at": datetime.fromisoformat(r[2])} for r in rows]

    def signal_created_at(self, signal_id: str) -> datetime:
        with self._connect() as db:
            row = db.execute("SELECT created_at_utc FROM paper_signals WHERE signal_id=?", (signal_id,)).fetchone()
        if row is None:
            raise ValueError("unknown signal_id")
        return datetime.fromisoformat(row[0])

    def signal_status(self, signal_id: str) -> SignalStatus:
        with self._connect() as db:
            row = db.execute("SELECT status FROM paper_signals WHERE signal_id=?", (signal_id,)).fetchone()
        if row is None:
            raise ValueError("unknown signal_id")
        return SignalStatus(row[0])

    def signal_events(self, signal_id: str) -> list[dict]:
        with self._connect() as db:
            rows = db.execute("""SELECT event_id,timestamp_utc,target_status,reason,evidence_ref,payload_json
                FROM paper_signal_events WHERE signal_id=? ORDER BY timestamp_utc,rowid""",
                (signal_id,)).fetchall()
        return [{
            "event_id": r[0], "timestamp": r[1], "status": r[2],
            "reason": r[3], "evidence_ref": r[4], "payload": json.loads(r[5]),
        } for r in rows]

    def open_position(self, position: PaperPosition, signal_id: str) -> bool:
        with self._connect() as db:
            signal = db.execute("SELECT status FROM paper_signals WHERE signal_id=?", (signal_id,)).fetchone()
            if signal is None:
                raise ValueError("unknown signal_id")
            if signal[0] != SignalStatus.ENTRY_ARMED.value:
                raise ValueError("paper position requires an ENTRY_ARMED signal")
            existing = db.execute("SELECT 1 FROM paper_positions WHERE signal_id=?", (signal_id,)).fetchone()
            if existing:
                return False
            entry_time = _utc(position.entry_time)
            db.execute("""INSERT INTO paper_positions
                (position_id,signal_id,symbol,model_id,direction,entry_time_utc,entry_price,stop,target,
                 quantity,point_value,fees_per_unit,slippage_points,status,last_processed_bar_utc)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'OPEN',?)""",
                (position.position_id, signal_id, position.instrument_id, position.model_id,
                 position.direction, entry_time, str(position.entry_price), str(position.stop),
                 str(position.target), str(position.quantity), str(position.point_value),
                 str(position.round_trip_fees_per_unit), str(position.round_trip_slippage_points), entry_time))
            db.execute("""INSERT INTO paper_signal_events
                (event_id,signal_id,timestamp_utc,target_status,reason,evidence_ref,payload_json)
                VALUES (?,?,?,?,?,?,?)""",
                (f"{signal_id}:filled", signal_id, entry_time, SignalStatus.FILLED.value,
                 "Paper limit entry filled from completed Angel One candle", None, "{}"))
            db.execute("""INSERT INTO paper_signal_events
                (event_id,signal_id,timestamp_utc,target_status,reason,evidence_ref,payload_json)
                VALUES (?,?,?,?,?,?,?)""",
                (f"{signal_id}:open", signal_id, entry_time, SignalStatus.OPEN.value,
                 "Paper position opened", None, "{}"))
            db.execute("UPDATE paper_signals SET status=?,updated_at_utc=? WHERE signal_id=?",
                       (SignalStatus.OPEN.value, entry_time, signal_id))
        return True

    def has_position_for_signal(self, signal_id: str) -> bool:
        with self._connect() as db:
            row = db.execute("SELECT 1 FROM paper_positions WHERE signal_id=?", (signal_id,)).fetchone()
        return row is not None

    def load_open_positions(self) -> list[PaperPosition]:
        with self._connect() as db:
            rows = db.execute("""SELECT position_id,symbol,model_id,direction,entry_time_utc,
                entry_price,stop,target,quantity,point_value,fees_per_unit,slippage_points
                FROM paper_positions WHERE status='OPEN' ORDER BY entry_time_utc""").fetchall()
        return [PaperPosition(
            position_id=r[0], instrument_id=r[1], model_id=r[2], direction=r[3],
            entry_time=datetime.fromisoformat(r[4]), entry_price=Decimal(r[5]),
            stop=Decimal(r[6]), target=Decimal(r[7]), quantity=Decimal(r[8]),
            point_value=Decimal(r[9]), round_trip_fees_per_unit=Decimal(r[10]),
            round_trip_slippage_points=Decimal(r[11]),
        ) for r in rows]

    def close_position(self, exit_: PaperExit, signal_id: str) -> bool:
        stamp = _utc(exit_.exit_time)
        with self._connect() as db:
            row = db.execute("SELECT status FROM paper_positions WHERE position_id=?", (exit_.position_id,)).fetchone()
            if row is None:
                raise ValueError("unknown position_id")
            if row[0] == "CLOSED":
                return False
            db.execute("""UPDATE paper_positions SET status='CLOSED',exit_time_utc=?,exit_price=?,exit_reason=?,
                gross_pnl=?,fees=?,slippage_cost=?,net_pnl=?,ambiguous_bar=?,gap_through_stop=?,
                r_multiple=?,duration_minutes=? WHERE position_id=?""",
                (stamp, str(exit_.exit_price), exit_.reason, str(exit_.gross_pnl), str(exit_.fees),
                 str(exit_.slippage_cost), str(exit_.net_pnl), int(exit_.ambiguous_bar),
                 int(exit_.gap_through_stop), str(exit_.r_multiple), exit_.duration_minutes, exit_.position_id))
            db.execute("""INSERT OR IGNORE INTO paper_signal_events
                (event_id,signal_id,timestamp_utc,target_status,reason,evidence_ref,payload_json)
                VALUES (?,?,?,?,?,?,?)""",
                (f"{signal_id}:closed", signal_id, stamp, SignalStatus.CLOSED.value,
                 f"Paper position closed: {exit_.reason}", None,
                 json.dumps({"net_pnl": str(exit_.net_pnl), "r_multiple": str(exit_.r_multiple)})))
            db.execute("UPDATE paper_signals SET status=?,updated_at_utc=? WHERE signal_id=?",
                       (SignalStatus.CLOSED.value, stamp, signal_id))
        return True

    def position_signal_id(self, position_id: str) -> str:
        with self._connect() as db:
            row = db.execute("SELECT signal_id FROM paper_positions WHERE position_id=?", (position_id,)).fetchone()
        if row is None:
            raise ValueError("unknown position_id")
        return row[0]

    def last_processed_bar(self, position_id: str) -> datetime:
        with self._connect() as db:
            row = db.execute("SELECT last_processed_bar_utc,entry_time_utc FROM paper_positions WHERE position_id=? AND status='OPEN'", (position_id,)).fetchone()
        if row is None:
            raise ValueError("unknown open position_id")
        return datetime.fromisoformat(row[0] or row[1])

    def update_position_progress(self, position_id: str, bar_timestamp: datetime):
        stamp = _utc(bar_timestamp)
        with self._connect() as db:
            db.execute("UPDATE paper_positions SET last_processed_bar_utc=? WHERE position_id=? AND status='OPEN'",
                       (stamp, position_id))

    def load_daily_risk(self, risk_date: date, starting_equity: Decimal) -> DailyRiskState:
        """Reconstruct daily counters from the immutable paper-position journal.

        This makes a restart between position creation and risk-state persistence
        recoverable instead of trusting a possibly stale counter row.
        """
        day = risk_date.isoformat()
        with self._connect() as db:
            open_count = db.execute(
                "SELECT COUNT(*) FROM paper_positions WHERE status='OPEN'"
            ).fetchone()[0]
            trades_today = db.execute(
                "SELECT COUNT(*) FROM paper_positions WHERE substr(entry_time_utc,1,10)=?",
                (day,),
            ).fetchone()[0]
            pnl_rows = db.execute(
                """SELECT net_pnl FROM paper_positions
                   WHERE status='CLOSED' AND substr(exit_time_utc,1,10)=?
                   ORDER BY exit_time_utc""",
                (day,),
            ).fetchall()
            realized = sum((Decimal(row[0] or "0") for row in pnl_rows), Decimal("0"))
            consecutive = 0
            for (value,) in reversed(pnl_rows):
                pnl = Decimal(value or "0")
                if pnl < 0:
                    consecutive += 1
                else:
                    break
            db.execute("""INSERT INTO paper_daily_risk
                (risk_date,equity,realized_pnl,open_positions,trades_today,consecutive_losses,updated_at_utc)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(risk_date) DO UPDATE SET
                    equity=excluded.equity,realized_pnl=excluded.realized_pnl,
                    open_positions=excluded.open_positions,trades_today=excluded.trades_today,
                    consecutive_losses=excluded.consecutive_losses,updated_at_utc=excluded.updated_at_utc""",
                (day, str(starting_equity), str(realized), open_count, trades_today,
                 consecutive, datetime.now(timezone.utc).isoformat()))
        return DailyRiskState(risk_date, realized, open_count, trades_today, consecutive)

    def save_daily_risk(self, risk_date: date, equity: Decimal, state: DailyRiskState):
        if state.risk_date != risk_date:
            raise ValueError("risk state date mismatch")
        with self._connect() as db:
            db.execute("""INSERT INTO paper_daily_risk
                (risk_date,equity,realized_pnl,open_positions,trades_today,consecutive_losses,updated_at_utc)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(risk_date) DO UPDATE SET
                    equity=excluded.equity,realized_pnl=excluded.realized_pnl,
                    open_positions=excluded.open_positions,trades_today=excluded.trades_today,
                    consecutive_losses=excluded.consecutive_losses,updated_at_utc=excluded.updated_at_utc""",
                (risk_date.isoformat(), str(equity), str(state.realized_pnl), state.open_positions,
                 state.trades_today, state.consecutive_losses, datetime.now(timezone.utc).isoformat()))

    def closed_trade_rows(self, *, start_date: date | None = None, end_date: date | None = None) -> list[dict]:
        sql = """SELECT symbol,model_id,direction,entry_time_utc,entry_price,stop,target,quantity,
            exit_time_utc,exit_price,exit_reason,gross_pnl,fees,slippage_cost,net_pnl,
            ambiguous_bar,gap_through_stop,r_multiple,duration_minutes
            FROM paper_positions WHERE status='CLOSED'"""
        params = []
        if start_date:
            sql += " AND entry_time_utc>=?"
            params.append(_utc(datetime.combine(start_date, datetime.min.time(), timezone.utc)))
        if end_date:
            sql += " AND entry_time_utc<?"
            params.append(_utc(datetime.combine(end_date + timedelta(days=1), datetime.min.time(), timezone.utc)))
        sql += " ORDER BY exit_time_utc,entry_time_utc"
        with self._connect() as db:
            rows = db.execute(sql, params).fetchall()
        keys = ["symbol","model_id","direction","entry_time","entry_price","stop","target","quantity",
                "exit_time","exit_price","exit_reason","gross_pnl","fees","slippage_cost","net_pnl",
                "ambiguous_bar","gap_through_stop","r_multiple","duration_minutes"]
        return [dict(zip(keys, row)) for row in rows]
