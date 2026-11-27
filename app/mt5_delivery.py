import hashlib
import json
import sqlite3
import secrets

from app.mt5_sqlite import execute_command
from app.mt5_thinker_room import consult_mt5
from datetime import datetime, timezone
from pathlib import Path
from app.mads_orchestrator import run_mads_debate


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

        columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(mt5_delivery_requests)"
            ).fetchall()
        }

        if "cancel_requested_at" not in columns:
            conn.execute("""
                ALTER TABLE mt5_delivery_requests
                ADD COLUMN cancel_requested_at TEXT
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

    if command == "CHART-INIT":
        operations = payload.get("operations")

        if not isinstance(operations, list) or not operations:
            raise ValueError(
                "CHART-INIT requires a non-empty operations array."
            )

        for operation in operations:
            if not isinstance(operation, dict):
                raise ValueError(
                    "Each CHART-INIT operation must be an object."
                )

            if not isinstance(operation.get("command"), str):
                raise ValueError(
                    "Each CHART-INIT operation requires a command."
                )
                
    elif command == "SQL-DIRECT":
        operation = payload.get("operation")

        if not isinstance(operation, dict):
            raise ValueError(
                "SQL-DIRECT requires an operation object."
            )

        operation_command = operation.get("command")

        if not isinstance(operation_command, str):
            raise ValueError(
                "SQL-DIRECT operation requires a command."
            )

        operation_command = operation_command.upper()

        if operation_command not in ("LIST-TABL", "SELA"):
            raise ValueError(
                f"Unsupported SQL-DIRECT operation: {operation_command}"
            )

        if operation_command == "SELA":
            table = operation.get("table")

            if not isinstance(table, str) or not table.strip():
                raise ValueError(
                    "SELA requires a non-empty table."
                )

            columns = operation.get("columns")

            if (
                not isinstance(columns, list)
                or not columns
                or any(
                    not isinstance(column, str) or not column.strip()
                    for column in columns
                )
            ):
                raise ValueError(
                    "SELA requires a non-empty columns array of strings."
                )

            limit = operation.get("limit")

            if limit is not None:
                if (
                    isinstance(limit, bool)
                    or not isinstance(limit, int)
                    or limit < 1
                ):
                    raise ValueError(
                        "SELA limit must be a positive integer."
                    )
                    
    elif command == "CONSULT-LLM":
        inquiry = payload.get("inquiry")

        if not isinstance(inquiry, dict):
            raise ValueError(
                "CONSULT-LLM requires an inquiry object."
            )

        question = inquiry.get("question")

        if not isinstance(question, str) or not question.strip():
            raise ValueError(
                "CONSULT-LLM requires a non-empty inquiry.question."
            )

        select = payload.get("select")

        if select is not None:
            if not isinstance(select, dict):
                raise ValueError(
                    "CONSULT-LLM select must be an object."
                )

            if select.get("type") != "SELA":
                raise ValueError(
                    "CONSULT-LLM supports only SELA select type."
                )

            table = select.get("table")

            if not isinstance(table, str) or not table.strip():
                raise ValueError(
                    "SELA requires a non-empty table."
                )

            columns = select.get("columns")

            if (
                not isinstance(columns, list)
                or not columns
                or any(
                    not isinstance(column, str) or not column.strip()
                    for column in columns
                )
            ):
                raise ValueError(
                    "SELA requires a non-empty columns array of strings."
                )

            limit = select.get("limit")

            if limit is not None:
                if (
                    isinstance(limit, bool)
                    or not isinstance(limit, int)
                    or limit < 1
                ):
                    raise ValueError(
                        "SELA limit must be a positive integer."
                    )

    else:
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


def cancel_mt5_request(client_id, request_id):
    if not isinstance(client_id, str) or not client_id.strip():
        raise ValueError("Invalid client_id.")

    if not isinstance(request_id, str) or not request_id.strip():
        raise ValueError("Invalid request_id.")

    now = _now()
    response_id = secrets.token_hex(16)

    response = {
        "protocol": "mt5-gateway",
        "version": 1,
        "message_type": "POLL_RESULT",
        "client_id": client_id,
        "request_id": request_id,
        "status": "COMPLETED",
        "response_id": response_id,
        "created_at": now,
        "payload": {
            "cancelled": True,
            "message": "Request force-completed by CANCEL command."
        },
    }

    response_json = json.dumps(
        response,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )

    conn = _connect()

    try:
        conn.execute("BEGIN IMMEDIATE")

        row = conn.execute(
            """
            SELECT response_json
            FROM mt5_delivery_requests
            WHERE client_id = ?
              AND request_id = ?
            """,
            (client_id, request_id),
        ).fetchone()

        if row is not None and row["response_json"]:
            status = "ALREADY_COMPLETED"

        elif row is None:
            request_json = "{}"
            payload_hash = hashlib.sha256(
                request_json.encode("utf-8")
            ).hexdigest()

            conn.execute(
                """
                INSERT INTO mt5_delivery_requests (
                    client_id,
                    request_id,
                    payload_hash,
                    request_json,
                    status,
                    created_at,
                    registered_at,
                    response_id,
                    response_json,
                    cancel_requested_at
                )
                VALUES (?, ?, ?, ?, 'COMPLETED', ?, ?, ?, ?, ?)
                """,
                (
                    client_id,
                    request_id,
                    payload_hash,
                    request_json,
                    now,
                    now,
                    response_id,
                    response_json,
                    now,
                ),
            )

            status = "CANCEL_REQUESTED"

        else:
            conn.execute(
                """
                UPDATE mt5_delivery_requests
                SET status = 'COMPLETED',
                    cancel_requested_at = ?,
                    response_id = ?,
                    response_json = ?
                WHERE client_id = ?
                  AND request_id = ?
                  AND response_json IS NULL
                """,
                (
                    now,
                    response_id,
                    response_json,
                    client_id,
                    request_id,
                ),
            )

            status = "CANCEL_REQUESTED"

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    return {
        "protocol": "mt5-gateway",
        "version": 1,
        "message_type": "CONTROL_RESULT",
        "client_id": client_id,
        "request_id": request_id,
        "command": "CANCEL",
        "status": status,
    }


def _is_mt5_cancel_requested(client_id, request_id):
    conn = _connect()

    try:
        row = conn.execute(
            """
            SELECT cancel_requested_at
            FROM mt5_delivery_requests
            WHERE client_id = ?
              AND request_id = ?
            """,
            (client_id, request_id),
        ).fetchone()

        return bool(row and row["cancel_requested_at"])

    finally:
        conn.close()

def process_mt5_request(client_id, request_id, allow_processing=False):

    conn = _connect()

    try:
        conn.execute("BEGIN IMMEDIATE")

        row = conn.execute(
            """
            SELECT request_json, status, response_json, cancel_requested_at
            FROM mt5_delivery_requests
            WHERE client_id = ?
              AND request_id = ?
            """,
            (client_id, request_id),
        ).fetchone()

        if row is None:
            raise ValueError("Request not found.")

        if row["response_json"]:
            response = json.loads(row["response_json"])
            conn.commit()
            return response
        
        if (
            row["status"] == "PROCESSING"
            and not allow_processing
        ):
            conn.commit()
            return {
                "client_id": client_id,
                "request_id": request_id,
                "status": "PROCESSING",
                "response_id": None,
                "payload": None,
            }

        
        if row["status"] not in ("REGISTERED", "PROCESSING"):
            conn.commit()
        
            return {
                "client_id": client_id,
                "request_id": request_id,
                "status": row["status"],
                "response_id": None,
                "payload": None,
            }

        conn.execute(
            """
            UPDATE mt5_delivery_requests
            SET status = 'PROCESSING'
            WHERE client_id = ?
              AND request_id = ?
            """,
            (client_id, request_id),
        )

        request_json = row["request_json"]
        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    envelope = json.loads(request_json)
    payload = envelope["payload"]

    command = payload["command"]
    operation_results = []

    success = True

    if command == "CHART-INIT":

        for index, operation in enumerate(
            payload["operations"]
        ):
            if _is_mt5_cancel_requested(client_id, request_id):
                success = False
                break
            execution_id = f"{client_id}:{request_id}:{index}"

            result = execute_command(
                operation,
                execution_id=execution_id,
            )

            operation_results.append({
                "index": index,
                **result,
            })

            if not result.get("success"):
                success = False
                break

        
        mads_result = None

        if success:
            if _is_mt5_cancel_requested(client_id, request_id):
                success = False
            else:
                try:
                    mads_result = run_mads_debate()

                except Exception as exc:
                    success = False
                    mads_result = {
                        "success": False,
                        "error": str(exc)[:1000],
                    }


        
        response_payload = {
            "operations": operation_results,
        }

        if not success:
            response_payload["error"] = "CHART-INIT operation failed."
            
    elif command == "SQL-DIRECT":

        if _is_mt5_cancel_requested(client_id, request_id):
            success = False
            response_payload = {
                "error": "Request was cancelled."
            }

        else:
            execution_id = (
                f"{client_id}:{request_id}:SQL-DIRECT"
            )

            operation_result = execute_command(
                payload["operation"],
                execution_id=execution_id,
            )

            success = operation_result.get("success", False)

            response_payload = {
                "operation": operation_result,
            }
            
    elif command == "CONSULT-LLM":

        try:
            select_result = None
            select = payload.get("select")

            if _is_mt5_cancel_requested(client_id, request_id):
                success = False
                response_payload = {
                    "error": "Request was cancelled."
                }

            else:
                if select is not None:
                    operation = {
                        "command": select["type"],
                        "table": select["table"],
                        "columns": select["columns"],
                    }

                    if "limit" in select:
                        operation["limit"] = select["limit"]

                    execution_id = (
                        f"{client_id}:{request_id}:CONSULT-LLM:SELA"
                    )

                    select_response = execute_command(
                        operation,
                        execution_id=execution_id,
                    )

                    if not select_response.get("success"):
                        success = False
                        response_payload = {
                            "error": "CONSULT-LLM SELA failed.",
                            "details": select_response.get("error"),
                        }
                    else:
                        select_result = select_response["result"]

                if success:
                    if _is_mt5_cancel_requested(
                        client_id,
                        request_id,
                    ):
                        success = False
                        response_payload = {
                            "error": "Request was cancelled."
                        }

                    else:
                        result = consult_mt5(
                            payload["inquiry"],
                            select_result=select_result,
                        )

                        response_payload = {
                            "model_key": result["model_key"],
                            "answer": result["answer"],
                        }

        except Exception as exc:
            success = False
            response_payload = {
                "error": "CONSULT-LLM processing failed.",
                "details": str(exc)[:500],
            }

    else:
        success = False

        response_payload = {
            "error": f"Command not implemented: {command}"
        }

    conn = _connect()

    try:
        conn.execute("BEGIN IMMEDIATE")

        row = conn.execute(
            """
            SELECT cancel_requested_at, response_json
            FROM mt5_delivery_requests
            WHERE client_id = ?
              AND request_id = ?
            """,
            (client_id, request_id),
        ).fetchone()

        if row is None:
            raise ValueError("Request not found.")

        if row["response_json"]:
            response = json.loads(row["response_json"])
            conn.commit()
            return response

        if row["cancel_requested_at"]:
            status = "CANCELLED"
            response_payload["cancelled"] = True
            response_payload["error"] = "Request was cancelled."
        else:
            status = "COMPLETED" if success else "FAILED"

        response = {
            "protocol": "mt5-gateway",
            "version": 1,
            "message_type": "POLL_RESULT",
            "client_id": client_id,
            "request_id": request_id,
            "status": status,
            "response_id": secrets.token_hex(16),
            "created_at": _now(),
            "payload": response_payload,
        }

        response_json = json.dumps(
            response,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

        conn.execute(
            """
            UPDATE mt5_delivery_requests
            SET status = ?,
                response_id = ?,
                response_json = ?
            WHERE client_id = ?
              AND request_id = ?
              AND status = 'PROCESSING'
              AND response_json IS NULL
            """,
            (
                status,
                response["response_id"],
                response_json,
                client_id,
                request_id,
            ),
        )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    return response


def recover_mt5_requests():
    conn = _connect()

    try:
        rows = conn.execute(
            """
            SELECT client_id, request_id
            FROM mt5_delivery_requests
            WHERE status IN ('REGISTERED', 'PROCESSING')
              AND response_json IS NULL
            ORDER BY registered_at, client_id, request_id
            """
        ).fetchall()

    finally:
        conn.close()

    results = []

    for row in rows:
        client_id = row["client_id"]
        request_id = row["request_id"]

        try:
            response = process_mt5_request(
                client_id,
                request_id,
                allow_processing=True,
            )

            results.append({
                "client_id": client_id,
                "request_id": request_id,
                "status": response.get("status"),
            })

        except Exception as exc:
            results.append({
                "client_id": client_id,
                "request_id": request_id,
                "error": str(exc),
            })

    return results

def get_mt5_response(client_id, request_id):
    if not isinstance(client_id, str) or not client_id.strip():
        raise ValueError("Invalid client_id.")

    if not isinstance(request_id, str) or not request_id.strip():
        raise ValueError("Invalid request_id.")

    conn = _connect()

    try:
        row = conn.execute(
            """
            SELECT status, response_id, response_json
            FROM mt5_delivery_requests
            WHERE client_id = ?
              AND request_id = ?
            """,
            (client_id, request_id),
        ).fetchone()

    finally:
        conn.close()

    if row is None:
        raise ValueError("Request not found.")

    if row["response_json"]:
        return json.loads(row["response_json"])

    return {
        "protocol": "mt5-gateway",
        "version": 1,
        "message_type": "POLL_RESULT",
        "client_id": client_id,
        "request_id": request_id,
        "status": "PROCESSING",
        "response_id": None,
        "payload": None,
    }

def acknowledge_mt5_response(envelope):
    if not isinstance(envelope, dict):
        raise ValueError("ACK must be a JSON object.")

    if envelope.get("protocol") != "mt5-gateway":
        raise ValueError("Invalid protocol.")

    if envelope.get("version") != 1:
        raise ValueError("Unsupported protocol version.")

    if envelope.get("message_type") != "ACK":
        raise ValueError("Expected ACK message.")

    client_id = envelope.get("client_id")
    request_id = envelope.get("request_id")
    response_id = envelope.get("response_id")

    if not all(
        isinstance(value, str) and value.strip()
        for value in (client_id, request_id, response_id)
    ):
        raise ValueError("Invalid ACK identifiers.")

    conn = _connect()

    try:
        conn.execute("BEGIN IMMEDIATE")

        row = conn.execute(
            """
            SELECT status, response_id, response_json, acknowledged_at
            FROM mt5_delivery_requests
            WHERE client_id = ?
              AND request_id = ?
            """,
            (client_id, request_id),
        ).fetchone()

        if row is None:
            raise ValueError("Request not found.")

        if not row["response_json"]:
            raise ValueError("Response is not ready.")

        if row["response_id"] != response_id:
            raise RequestConflictError("response_id mismatch.")

        if row["acknowledged_at"] is None:
            conn.execute(
                """
                UPDATE mt5_delivery_requests
                SET status = 'ACKNOWLEDGED',
                    acknowledged_at = ?
                WHERE client_id = ?
                  AND request_id = ?
                  AND acknowledged_at IS NULL
                """,
                (_now(), client_id, request_id),
            )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    return {
        "protocol": "mt5-gateway",
        "version": 1,
        "message_type": "ACK_RESULT",
        "client_id": client_id,
        "request_id": request_id,
        "response_id": response_id,
        "status": "ACKNOWLEDGED",
    }
