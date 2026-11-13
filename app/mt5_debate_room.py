from __future__ import annotations

import json
import sqlite3

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ============================================================
# MT5 Debate Room - Database
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

MT5_DEBATE_DB = DATA_DIR / "mt5_debate_room.sqlite3"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_db_connection():
    """
    Provide a SQLite connection with automatic commit,
    rollback, and close.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(
        MT5_DEBATE_DB,
        timeout=30,
    )

    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        yield conn
        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

def init_mt5_debate_db() -> None:
    """
    Create the initial database schema.

    Market candles and incoming messages are stored separately.
    """

    with get_db_connection() as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS mt5_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                message_id TEXT NOT NULL UNIQUE,
                message_type TEXT NOT NULL,
                symbol TEXT NOT NULL,

                received_at TEXT NOT NULL,

                status TEXT NOT NULL DEFAULT 'received',
                error_message TEXT,

                payload_json TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS mt5_candles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                candle_time TEXT NOT NULL,

                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,

                tick_volume INTEGER NOT NULL,
                spread_points INTEGER NOT NULL,

                river_center REAL,
                river_width_pips REAL,

                ma_bifurcation_direction TEXT,

                source_message_id TEXT NOT NULL,

                raw_json TEXT NOT NULL,
                received_at TEXT NOT NULL,

                UNIQUE (
                    symbol,
                    timeframe,
                    candle_time
                ),

                FOREIGN KEY (source_message_id)
                    REFERENCES mt5_messages(message_id)
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_mt5_candles_symbol_timeframe_time
            ON mt5_candles (
                symbol,
                timeframe,
                candle_time
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_mt5_messages_symbol_received
            ON mt5_messages (
                symbol,
                received_at
            )
        """)
