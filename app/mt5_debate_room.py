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
            CREATE TABLE IF NOT EXISTS mt5_receive_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                received_at TEXT NOT NULL,
                message_type TEXT NOT NULL,
                symbol TEXT NOT NULL,
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

    # Optional observer-derived numeric fields.
    for field in ("river_center", "river_width_pips"):
        if field not in candle or candle[field] is None:
            continue

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

        if field == "river_width_pips" and value < 0:
            raise ValueError("River width cannot be negative.")

        normalized[field] = value

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

    # Optional MA bifurcation observer output.
    if "ma_bifurcation" in candle and candle["ma_bifurcation"] is not None:
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

        normalized["ma_bifurcation"] = {
            "direction": direction
        }

    normalized["time"] = candle_time

    return normalized

def validate_mt5_message(payload: dict) -> dict:
    """
    Validate the envelope of an incoming MT5 message.
    """

    if not isinstance(payload, dict):
        raise ValueError("Message must be a JSON object.")

    message_type = payload.get("message_type")
    message_id = payload.get("message_id")
    symbol = payload.get("symbol")

    if message_type not in ("INIT", "CANDLE_UPDATE"):
        raise ValueError("Unsupported MT5 message_type.")

    if not isinstance(message_id, str) or not message_id.strip():
        raise ValueError("Invalid message_id.")

    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("Invalid symbol.")

    if message_type == "CANDLE_UPDATE":
        timeframe = payload.get("timeframe")

        if timeframe not in ("H1", "H6"):
            raise ValueError("Invalid candle timeframe.")

        candles = payload.get("candles")

        if not isinstance(candles, list) or len(candles) != 1:
            raise ValueError(
                "CANDLE_UPDATE must contain exactly one candle."
            )

        request_debate = payload.get("request_debate", False)

        if not isinstance(request_debate, bool):
            raise ValueError("request_debate must be a boolean.")

        
        return {
            "message_type": message_type,
            "message_id": message_id,
            "symbol": symbol,
            "timeframe": timeframe,
            "request_debate": request_debate,
            "candles": [
                validate_mt5_candle(candles[0])
            ],
        }

    timeframes = payload.get("timeframes")

    if not isinstance(timeframes, dict):
        raise ValueError("INIT timeframes must be an object.")

    normalized_timeframes = {}

    for timeframe, expected_count in (
        ("H1", 100),
        ("H6", 20),
    ):
        timeframe_data = timeframes.get(timeframe)

        if not isinstance(timeframe_data, dict):
            raise ValueError(
                f"INIT is missing {timeframe} data."
            )

        candles = timeframe_data.get("candles")

        if not isinstance(candles, list):
            raise ValueError(
                f"INIT {timeframe} candles must be a list."
            )

        if len(candles) != expected_count:
            raise ValueError(
                f"INIT {timeframe} must contain exactly "
                f"{expected_count} candles."
            )

        normalized_timeframes[timeframe] = [
            validate_mt5_candle(candle)
            for candle in candles
        ]


    for timeframe, candles in normalized_timeframes.items():
        candle_times = [
            datetime.strptime(
                candle["time"],
                "%Y.%m.%d %H:%M",
            )
            for candle in candles
        ]

        for index in range(1, len(candle_times)):
            if candle_times[index] <= candle_times[index - 1]:
                raise ValueError(
                    f"INIT {timeframe} candles must be "
                    "strictly ordered oldest-to-newest."
                )
    
    return {
        "message_type": message_type,
        "message_id": message_id,
        "symbol": symbol,
        "timeframes": normalized_timeframes,
    }

def store_mt5_message(payload: dict) -> dict:
    """
    Store a validated MT5 message and its candles atomically.
    Duplicate messages and candles are handled idempotently.
    """

    message_id = payload["message_id"]
    message_type = payload["message_type"]
    symbol = payload["symbol"]

    payload_json = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    received_at = _now()

    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        existing = conn.execute(
            """
            SELECT message_id, payload_json
            FROM mt5_messages
            WHERE message_id = ?
            """,
            (message_id,),
        ).fetchone()

        if existing:
            existing_payload = json.loads(
                existing["payload_json"]
            )

            if existing_payload != payload:
                raise ValueError(
                    "message_id already exists with different content."
                )

            return {
                "success": True,
                "duplicate_message": True,
                "message_id": message_id,
                "inserted_candles": 0,
                "duplicate_candles": 0,
                "request_debate": False,
            }

        conn.execute(
            """
            INSERT INTO mt5_messages (
                message_id,
                message_type,
                symbol,
                received_at,
                status,
                payload_json
            )
            VALUES (?, ?, ?, ?, 'received', ?)
            """,
            (
                message_id,
                message_type,
                symbol,
                received_at,
                payload_json,
            ),
        )

        candle_items = []

        if message_type == "CANDLE_UPDATE":
            candle_items = [
                (payload["timeframe"], candle)
                for candle in payload["candles"]
            ]

        elif message_type == "INIT":
            for timeframe, candles in payload["timeframes"].items():
                candle_items.extend(
                    (timeframe, candle)
                    for candle in candles
                )

        inserted_candles = 0
        duplicate_candles = 0

        for timeframe, candle in candle_items:
            cursor = conn.execute(
                """
                INSERT INTO mt5_candles (
                    symbol,
                    timeframe,
                    candle_time,
                    open,
                    high,
                    low,
                    close,
                    tick_volume,
                    spread_points,
                    river_center,
                    river_width_pips,
                    ma_bifurcation_direction,
                    source_message_id,
                    raw_json,
                    received_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (
                    symbol,
                    timeframe,
                    candle_time
                ) DO NOTHING
                """,
                (
                    symbol,
                    timeframe,
                    candle["time"],
                    candle["open"],
                    candle["high"],
                    candle["low"],
                    candle["close"],
                    candle["tick_volume"],
                    candle["spread_points"],
                    candle.get("river_center"),
                    candle.get("river_width_pips"),
                    (candle.get("ma_bifurcation") or {}).get("direction"),
                    message_id,
                    json.dumps(
                        candle,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    received_at,
                ),
            )

            if cursor.rowcount == 1:
                inserted_candles += 1
            else:
                duplicate_candles += 1

        if inserted_candles == 0:
            status = "duplicate_candles"
        elif duplicate_candles > 0:
            status = "stored_with_duplicates"
        else:
            status = "stored"

        conn.execute(
            """
            UPDATE mt5_messages
            SET status = ?
            WHERE message_id = ?
            """,
            (status, message_id),
        )

        request_debate = (
            message_type == "CANDLE_UPDATE"
            and payload.get("request_debate", False)
            and inserted_candles == 1
        )

        return {
            "success": True,
            "duplicate_message": False,
            "message_id": message_id,
            "status": status,
            "inserted_candles": inserted_candles,
            "duplicate_candles": duplicate_candles,
            "request_debate": request_debate,
        }

def _record_mt5_receive_event(payload: dict) -> None:
    """
    Record every received MT5 payload before validation
    and duplicate-message detection.
    """

    raw_payload = (
        payload
        if isinstance(payload, dict)
        else {"_raw_value": payload}
    )

    payload_json = json.dumps(
        raw_payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    message_type = str(
        raw_payload.get("message_type") or "UNKNOWN"
    )

    symbol = str(
        raw_payload.get("symbol") or "UNKNOWN"
    )

    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO mt5_receive_events (
                received_at,
                message_type,
                symbol,
                payload_json
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                _now(),
                message_type,
                symbol,
                payload_json,
            ),
        )


def process_mt5_message(payload: dict) -> dict:
    """
    Validate and store an incoming MT5 message.

    Debate execution is intentionally handled separately.
    """
    
    _record_mt5_receive_event(payload)
    normalized_payload = validate_mt5_message(payload)

    storage_result = store_mt5_message(
        normalized_payload
    )

    return {
        "success": True,
        "message_type": normalized_payload["message_type"],
        "message_id": normalized_payload["message_id"],
        "symbol": normalized_payload["symbol"],
        "storage": storage_result,
        "debate_requested": storage_result["request_debate"],
    }


def get_mt5_receive_report() -> dict:
    """
    Return a plain-English report about the latest
    MT5 payload received by the server.
    """

    with get_db_connection() as conn:
        event = conn.execute(
            """
            SELECT
                message_type,
                symbol,
                payload_json,
                received_at
            FROM mt5_receive_events
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()

    if event is None:
        return {
            "report": "The server has not received any MT5 message yet."
        }

    payload = json.loads(
        event["payload_json"]
    )

    message_type = event["message_type"]
    symbol = event["symbol"]

    h1_count = 0
    h6_count = 0

    if message_type == "INIT":

        timeframes = payload.get("timeframes", {})

        if isinstance(timeframes, dict):

            h1_data = timeframes.get("H1", {})
            h6_data = timeframes.get("H6", {})

            h1_candles = (
                h1_data.get("candles", [])
                if isinstance(h1_data, dict)
                else []
            )

            h6_candles = (
                h6_data.get("candles", [])
                if isinstance(h6_data, dict)
                else []
            )

            h1_count = (
                len(h1_candles)
                if isinstance(h1_candles, list)
                else 0
            )

            h6_count = (
                len(h6_candles)
                if isinstance(h6_candles, list)
                else 0
            )

    elif message_type == "CANDLE_UPDATE":

        timeframe = payload.get("timeframe")
        candles = payload.get("candles", [])

        candle_count = (
            len(candles)
            if isinstance(candles, list)
            else 0
        )

        if timeframe == "H1":
            h1_count = candle_count

        elif timeframe == "H6":
            h6_count = candle_count

    total_count = h1_count + h6_count

    init_status = (
        "yes"
        if message_type == "INIT"
        else "no"
    )

    h1_label = (
        "candle"
        if h1_count == 1
        else "candles"
    )

    h6_label = (
        "candle"
        if h6_count == 1
        else "candles"
    )

    total_label = (
        "candle"
        if total_count == 1
        else "candles"
    )

    report_text = (
        f"The server received a {message_type} JSON message "
        f"for {symbol}. "
        f"INIT message: {init_status}. "
        f"The message contained {h1_count} H1 {h1_label} "
        f"and {h6_count} H6 {h6_label}. "
        f"Total candles received: {total_count}."
    )

    return {
        "report": report_text
    }
