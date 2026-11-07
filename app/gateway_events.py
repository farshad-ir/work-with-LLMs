import os
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"
EVENT_LOG_PATH = LOG_DIR / "gateway-events.jsonl"

_write_lock = threading.Lock()


def emit_gateway_event(
    event: str,
    request_id: str | None = None,
    attempt: int | None = None,
    provider: str | None = None,
    model: str | None = None,
    **details: Any,
) -> None:

    if os.getenv("GATEWAY_EVENTS_ENABLED", "false").lower() not in (
        "1", "true", "yes", "on"
    ):
        return

    """Append one structured Gateway event to the JSONL event log."""
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "request_id": request_id,
        "attempt": attempt,
        "provider": provider,
        "model": model,
        **details,
    }

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)

        line = json.dumps(
            record,
            ensure_ascii=False,
            default=str,
        )

        with _write_lock:
            with EVENT_LOG_PATH.open("a", encoding="utf-8") as file:
                file.write(line + "\n")

    except OSError as exc:
        print(f"[GATEWAY EVENTS] Could not write event: {exc}")
