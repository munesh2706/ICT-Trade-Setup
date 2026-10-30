"""Persistent per-symbol feed health; offline-safe SQLite utility."""
import sqlite3
from datetime import datetime, timezone


def init_health(db):
    db.execute("""CREATE TABLE IF NOT EXISTS live_feed_health(
      symbol TEXT PRIMARY KEY, connection_state TEXT NOT NULL,
      last_tick_utc TEXT, last_update_utc TEXT NOT NULL,
      recovery_required INTEGER NOT NULL, reason TEXT NOT NULL)""")
    db.commit()


def set_health(db, symbol, state, last_tick=None, recovery_required=False, reason=""):
    if last_tick is not None:
        if last_tick.tzinfo is None:
            raise ValueError("Tick timestamp must have timezone")
        last_tick = last_tick.astimezone(timezone.utc).isoformat()
    now = datetime.now(timezone.utc).isoformat()
    db.execute("""INSERT INTO live_feed_health
        (symbol,connection_state,last_tick_utc,last_update_utc,recovery_required,reason)
        VALUES (?,?,?,?,?,?)
        ON CONFLICT(symbol) DO UPDATE SET
        connection_state=excluded.connection_state,
        last_tick_utc=COALESCE(excluded.last_tick_utc,live_feed_health.last_tick_utc),
        last_update_utc=excluded.last_update_utc,
        recovery_required=MAX(live_feed_health.recovery_required,excluded.recovery_required),
        reason=excluded.reason""",
        (symbol, state, last_tick, now, int(recovery_required), reason[:200]))
    db.commit()


def acknowledge_recovery(db, symbol):
    """Only call after verified canonical historical recovery."""
    db.execute("UPDATE live_feed_health SET recovery_required=0, reason='RECOVERED' WHERE symbol=?",
               (symbol,))
    db.commit()
