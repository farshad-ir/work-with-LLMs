import hashlib
import json
import sqlite3

from datetime import datetime, timezone
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent

DELIVERY_DB = (
    BASE_DIR
    / "data"
    / "mt5_delivery.sqlite3"
)


class RequestConflictError(Exception):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat()


def _connect():
    DELIVERY_DB.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    conn = sqlite3.connect(
        DELIVERY_DB,
        timeout=30,
    )

    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA synchronous = FULL")

    return conn


def init_mt5_delivery_db():
    conn = _connect()

    try:
        conn.execute("PRAGMA journal_mode = WAL")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS mt5_delivery_requests (
                client_id TEXT NOT NULL,
                request_id TEXT NOT NULL,

                payload_hash TEXT NOT NULL,
                request_json TEXT NOT NULL,

                status TEXT NOT NULL,

                created_at TEXT NOT NULL,
                registered_at TEXT NOT NULL,

                response_id TEXT,
                response_json TEXT,

                acknowledged_at TEXT,

                PRIMARY KEY (
                    client_id,
                    request_id
                )
            )
        """)

        conn.commit()

    finally:
        conn.close()


def _validate_envelope(envelope):

    if not isinstance(envelope, dict):
        raise ValueError(
            "Request must be a JSON object."
        )

    if envelope.get("protocol") != "mt5-gateway":
        raise ValueError("Invalid protocol.")

    if envelope.get("version") != 1:
        raise ValueError("Unsupported protocol version.")

    if envelope.get("message_type") != "INGEST":
        raise ValueError("Expected INGEST message.")

    client_id = envelope.get("client_id")
    request_id = envelope.get("request_id")
    created_at = envelope.get("created_at")
    payload = envelope.get("payload")

    if not isinstance(client_id, str) or not client_id.strip():
        raise ValueError("Invalid client_id.")

    if not isinstance(request_id, str) or not request_id.strip():
        raise ValueError("Invalid request_id.")

    if not isinstance(created_at, str) or not created_at.strip():
        raise ValueError("Invalid created_at.")

    if not isinstance(payload, dict):
        raise ValueError("payload must be an object.")

    command = payload.get("command")

    if command not in ("INIT", "CANDLE_UPDATE"):
        raise ValueError("Unsupported payload command.")

    return client_id, request_id, created_at


def register_mt5_request(envelope):

    client_id, request_id, created_at = (
        _validate_envelope(envelope)
    )

    request_json = json.dumps(
        envelope,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )

    payload_hash = hashlib.sha256(
        request_json.encode("utf-8")
    ).hexdigest()

    registered_at = _now()

    conn = _connect()

    try:
        conn.execute("BEGIN IMMEDIATE")

        existing = conn.execute(
            """
            SELECT
                payload_hash,
                status,
                response_id
            FROM mt5_delivery_requests
            WHERE client_id = ?
              AND request_id = ?
            """,
            (client_id, request_id),
        ).fetchone()

        if existing:

            if existing["payload_hash"] != payload_hash:
                raise RequestConflictError(
                    "request_id already exists with different content."
                )

            status = existing["status"]
            response_id = existing["response_id"]

            conn.commit()

        else:

            conn.execute(
                """
                INSERT INTO mt5_delivery_requests (
                    client_id,
                    request_id,
                    payload_hash,
                    request_json,
                    status,
                    created_at,
                    registered_at
                )
                VALUES (?, ?, ?, ?, 'REGISTERED', ?, ?)
                """,
                (
                    client_id,
                    request_id,
                    payload_hash,
                    request_json,
                    created_at,
                    registered_at,
                ),
            )

            status = "REGISTERED"
            response_id = None

            conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    return {
        "protocol": "mt5-gateway",
        "version": 1,
        "message_type": "INGEST_RESULT",
        "client_id": client_id,
        "request_id": request_id,
        "status": status,
        "response_id": response_id,
        "created_at": created_at,
        "payload": None,
    }
