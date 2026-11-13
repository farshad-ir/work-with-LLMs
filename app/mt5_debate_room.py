from __future__ import annotations

import json
import math
import sqlite3

from contextlib import contextmanager
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

def validate_mt5_candle(candle: dict) -> dict:
    """
    Validate and normalize one MT5 candle.
    MT5 candle time is preserved without timezone conversion.
    """

    if not isinstance(candle, dict):
        raise ValueError("Candle must be a JSON object.")

    required_fields = (
        "time",
        "open",
        "high",
        "low",
        "close",
        "tick_volume",
        "spread_points",
        "river_center",
        "river_width_pips",
        "ma_bifurcation",
    )

    for field in required_fields:
        if field not in candle:
            raise ValueError(
                f"Missing candle field: {field}"
            )

    candle_time = candle["time"]

    if not isinstance(candle_time, str) or not candle_time.strip():
        raise ValueError("Invalid candle time.")

    try:
        datetime.strptime(
            candle_time,
            "%Y.%m.%d %H:%M",
        )
    except ValueError:
        raise ValueError(
            "Candle time must use YYYY.MM.DD HH:MM format."
        ) from None

    numeric_fields = (
        "open",
        "high",
        "low",
        "close",
        "river_center",
        "river_width_pips",
    )

    normalized = {}

    for field in numeric_fields:
        value = candle[field]

        if isinstance(value, bool):
            raise ValueError(
                f"Invalid numeric value: {field}"
            )

        try:
            value = float(value)
        except (TypeError, ValueError):
            raise ValueError(
                f"Invalid numeric value: {field}"
            ) from None

        if not math.isfinite(value):
            raise ValueError(
                f"Non-finite numeric value: {field}"
            )

        normalized[field] = value

    if normalized["high"] < normalized["low"]:
        raise ValueError("Candle high is below low.")

    if normalized["high"] < max(
        normalized["open"],
        normalized["close"],
    ):
        raise ValueError("Candle high is invalid.")

    if normalized["low"] > min(
        normalized["open"],
        normalized["close"],
    ):
        raise ValueError("Candle low is invalid.")

    if normalized["river_width_pips"] < 0:
        raise ValueError("River width cannot be negative.")

    for field in ("tick_volume", "spread_points"):
        value = candle[field]

        if isinstance(value, bool):
            raise ValueError(
                f"Invalid integer value: {field}"
            )

        try:
            integer_value = int(value)
        except (TypeError, ValueError):
            raise ValueError(
                f"Invalid integer value: {field}"
            ) from None

        if integer_value < 0 or integer_value != float(value):
            raise ValueError(
                f"Invalid integer value: {field}"
            )

        normalized[field] = integer_value

    bifurcation = candle["ma_bifurcation"]

    if not isinstance(bifurcation, dict):
        raise ValueError(
            "ma_bifurcation must be an object."
        )

    direction = bifurcation.get("direction")

    if not isinstance(direction, str) or not direction.strip():
        raise ValueError(
            "Invalid MA bifurcation direction."
        )

    normalized["time"] = candle_time
    normalized["ma_bifurcation"] = {
        "direction": direction
    }

    return normalized


