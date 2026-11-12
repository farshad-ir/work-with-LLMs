from threading import Lock
import tempfile
import sqlite3
import json
import os
import secrets
import asyncio
import re
from datetime import datetime, timezone

from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from app.responses_adapter import (
    chat_to_responses_text,
    parse_json_object,
    responses_to_chat,
    sse_event,
)


from app.config import (
    get_env_value,
    get_public_config,
    load_config,
    save_config,
)
from app.thinker_room import (
    rebuild_large_catalog,
    load_large_catalog,
)
from app.model_rotation import (
    select_next_model,
    record_request_result,
    get_rotation_status,
    _provider_key,
)

GATEWAY_LOG_ENABLED = os.getenv(
    "GATEWAY_LOG_ENABLED", "false"
).lower() in ("1", "true", "yes", "on")


def _gateway_log(*args, **kwargs):
    if GATEWAY_LOG_ENABLED:
        print(*args, **kwargs)


RESPONSE_BUFFER_MODE = (
    get_env_value("GATEWAY_RESPONSE_BUFFER_MODE").strip().lower()
    or "direct"
)

if RESPONSE_BUFFER_MODE not in ("direct", "buffered"):
    raise ValueError(
        "GATEWAY_RESPONSE_BUFFER_MODE must be direct or buffered."
    )
    
_response_buffer_path = get_env_value(
    "GATEWAY_RESPONSE_BUFFER_PATH"
).strip()

if RESPONSE_BUFFER_MODE == "buffered" and not _response_buffer_path:
    raise ValueError(
        "GATEWAY_RESPONSE_BUFFER_PATH is required in buffered mode."
    )

RESPONSE_BUFFER_PATH = (
    Path(_response_buffer_path).expanduser()
    if _response_buffer_path
    else None
)


BUFFERED_RESPONSE_ACTIVE = False
BUFFERED_RESPONSE_ERROR = None
BACKGROUND_RESPONSE_TASKS = set()

RESPONSE_BUFFER_TOKEN = get_env_value(
    "GATEWAY_RESPONSE_BUFFER_TOKEN"
).strip()

if RESPONSE_BUFFER_MODE == "buffered" and not RESPONSE_BUFFER_TOKEN:
    raise ValueError(
        "GATEWAY_RESPONSE_BUFFER_TOKEN is required in buffered mode."
    )





_SHORT_LOG_LOCK = Lock()


def _short_gateway_log(
    model: str,
    provider: str,
    value: int | str,
) -> None:
    enabled = get_env_value("GATEWAY_SHORT_LOG_ENABLED").strip().lower()

    if enabled not in ("1", "true", "yes", "on"):
        return

    log_dir = Path(__file__).resolve().parent.parent / "logs"
    log_path = log_dir / "gateway.log"

    model = str(model).replace(",", "_").replace("\n", " ")
    provider = str(provider).replace(",", "_").replace("\n", " ")
    value = str(value).replace(",", "_").replace("\n", " ")

    if value == "provider_connection_error":
        value = "(WebErr)"
    elif value.isdigit():
        if len(value) == 3 and value[0] in ("4", "5"):
            value = f"({value})"
        else:
            value = f"{int(value):,}"
    elif value in ("TiOut", "WebErr"):
        value = f"({value})"
    elif value.startswith("(") and value.endswith(")"):
        pass
    elif value:
        value = f"({value[:8]})"

    new_line = f"{value:<10} {provider:<15} {model}"

    temp_path = None

    try:
        log_dir.mkdir(parents=True, exist_ok=True)

        with _SHORT_LOG_LOCK:

            if log_path.exists():
                lines = log_path.read_text(
                    encoding="utf-8"
                ).splitlines()
            else:
                lines = []

            # Keep the newest 39 lines and append the new one.
            lines = (lines + [new_line])[-40:]

            # Write atomically to avoid a partially written log.
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=log_dir,
                prefix=".gateway.log.",
                suffix=".tmp",
                delete=False,
            ) as file:

                temp_path = Path(file.name)

                file.write("\n".join(lines) + "\n")
                file.flush()
                os.fsync(file.fileno())

            os.chmod(temp_path,0o640)
            os.replace(temp_path, log_path)

    except OSError as exc:
        _gateway_log(f"[SHORT LOG] Could not write log: {exc}")

    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)




class ProviderResponseBuffer:
    """Bounded response buffer that spills from RAM to a temporary file."""

    def __init__(self) -> None:
        self.ram_limit = int(
            os.getenv("GATEWAY_BUFFER_RAM_LIMIT", str(2 * 1024 * 1024))
        )
        self.max_bytes = int(
            os.getenv("GATEWAY_BUFFER_MAX_BYTES", str(50 * 1024 * 1024))
        )

        self.file = tempfile.SpooledTemporaryFile(
            max_size=self.ram_limit,
            mode="w+b",
        )
        self.size = 0

    def write(self, chunk: bytes) -> None:
        new_size = self.size + len(chunk)

        if new_size > self.max_bytes:
            raise ValueError(
                f"Provider response exceeded the {self.max_bytes}-byte limit."
            )

        self.file.write(chunk)
        self.size = new_size

    def read(self) -> bytes:
        self.file.seek(0)
        return self.file.read()

    def close(self) -> None:
        self.file.close()

def _responses_to_sse_events(response: dict) -> list[str]:
    """Convert a complete Responses API object into SSE events."""
    response_id = response.get("id", "resp_gateway")
    output = response.get("output", [])

    events = [
        sse_event("response.created", {
            "response": {
                **response,
                "status": "in_progress",
                "output": [],
            }
        }),
        sse_event("response.in_progress", {
            "response": {
                **response,
                "status": "in_progress",
                "output": [],
            }
        }),
    ]

    for output_index, item in enumerate(output):
        if not isinstance(item, dict):
            continue

        item_id = item.get("id", f"item_{output_index}")

        events.append(sse_event("response.output_item.added", {
            "response_id": response_id,
            "output_index": output_index,
            "item": {
                **item,
                "status": "in_progress",
            },
        }))

        if item.get("type") == "message":
            content = item.get("content", [])

            for content_index, part in enumerate(content):
                if not isinstance(part, dict):
                    continue

                text = part.get("text", "")

                events.append(sse_event("response.content_part.added", {
                    "response_id": response_id,
                    "item_id": item_id,
                    "output_index": output_index,
                    "content_index": content_index,
                    "part": {
                        **part,
                        "text": "",
                    },
                }))

                if text:
                    events.append(sse_event("response.output_text.delta", {
                        "response_id": response_id,
                        "item_id": item_id,
                        "output_index": output_index,
                        "content_index": content_index,
                        "delta": text,
                    }))

                events.append(sse_event("response.output_text.done", {
                    "response_id": response_id,
                    "item_id": item_id,
                    "output_index": output_index,
                    "content_index": content_index,
                    "text": text,
                }))

                events.append(sse_event("response.content_part.done", {
                    "response_id": response_id,
                    "item_id": item_id,
                    "output_index": output_index,
                    "content_index": content_index,
                    "part": part,
                }))

        elif item.get("type") == "function_call":
            arguments = item.get("arguments", "")

            events.append(sse_event("response.function_call_arguments.delta", {
                "response_id": response_id,
                "item_id": item_id,
                "output_index": output_index,
                "delta": arguments,
            }))

            events.append(sse_event("response.function_call_arguments.done", {
                "response_id": response_id,
                "item_id": item_id,
                "output_index": output_index,
                "arguments": arguments,
            }))

        events.append(sse_event("response.output_item.done", {
            "response_id": response_id,
            "output_index": output_index,
            "item": item,
        }))

    terminal_event = (
        "response.incomplete"
        if response.get("status") == "incomplete"
        else "response.completed"
    )

    events.append(sse_event(terminal_event, {
        "response": response,
    }))

    return events

def _clear_final_response_buffer():
    RESPONSE_BUFFER_PATH.unlink(missing_ok=True)


def _write_final_response_buffer(response: dict):
    path = RESPONSE_BUFFER_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            temp_path = Path(file.name)

            json.dump(
                response,
                file,
                ensure_ascii=False,
            )

            file.flush()
            os.fsync(file.fileno())

        os.replace(temp_path, path)

    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)



# Aliases for provider normalization
def _normalize_provider_name(name: str) -> str:
    """Normalize provider name the same way the catalog does."""
    name = str(name).strip().lower()
    if not name:
        return name
    # These are the same aliases as in thinker_room._normalize_provider
    aliases = {
        "nvidia_nim": "nvidia",
        "nvidia-nim": "nvidia",
        "tokenrouter": "token_router",
        "token-router": "token_router",
    }
    return aliases.get(name, name)

def _validate_discovery_spec(spec: dict) -> dict:
    """Validate and normalize a provider discovery specification."""

    if not isinstance(spec, dict):
        raise ValueError("Provider specification must be a JSON object.")

    provider_id = str(spec.get("provider_id", "")).strip()
    if not re.fullmatch(r"[a-zA-Z0-9_]+", provider_id):
        raise ValueError("Invalid provider_id.")

    display_name = str(spec.get("display_name", "")).strip() or provider_id

    base_url = str(spec.get("base_url", "")).strip().rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise ValueError("base_url must be an HTTP or HTTPS URL.")

    api_key_env = str(spec.get("api_key_env", "")).strip()
    if api_key_env and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", api_key_env):
        raise ValueError("Invalid api_key_env.")

    authentication = spec.get("authentication", {})
    if not isinstance(authentication, dict):
        raise ValueError("authentication must be an object.")

    auth_mode = authentication.get("mode", "bearer")
    if auth_mode not in ("none", "bearer", "header"):
        raise ValueError("Unsupported authentication mode.")

    header_name = str(
        authentication.get("header_name", "Authorization")
    ).strip()

    if auth_mode == "header" and not header_name:
        raise ValueError("header_name is required for header authentication.")

    discovery = spec.get("discovery", {})
    if not isinstance(discovery, dict):
        raise ValueError("discovery must be an object.")

    normalized_routes = {}

    for route_name in ("public", "authenticated"):
        route = discovery.get(route_name, {})
        if not isinstance(route, dict):
            raise ValueError(f"discovery.{route_name} must be an object.")

        enabled = bool(route.get("enabled", False))
        path = str(route.get("path", "/models")).strip()

        if enabled:
            if not path.startswith("/") or path.startswith("//"):
                raise ValueError(f"Invalid discovery path: {route_name}")

            if route_name == "authenticated" and auth_mode != "none" and not api_key_env:
                raise ValueError("api_key_env is required for authenticated discovery.")

        normalized_routes[route_name] = {
            "enabled": enabled,
            "path": path,
        }

    if not any(route["enabled"] for route in normalized_routes.values()):
        raise ValueError("At least one discovery route must be enabled.")

    parser = spec.get("response_parser", {})
    if not isinstance(parser, dict):
        raise ValueError("response_parser must be an object.")

    return {
        "provider_id": provider_id,
        "display_name": display_name,
        "base_url": base_url,
        "api_key_env": api_key_env,
        "enabled": bool(spec.get("enabled", True)),
        "authentication": {
            "mode": auth_mode,
            "header_name": header_name,
        },
        "discovery": normalized_routes,
        "response_parser": {
            "models_key": str(parser.get("models_key", "data")),
            "id_field": str(parser.get("id_field", "id")),
            "name_field": str(parser.get("name_field", "name")),
            "items_mode": str(parser.get("items_mode", "list")),
        },
    }


def _extract_discovered_models(payload: object, parser: dict) -> list:
    """Extract normalized model records from a provider response."""

    items = payload

    if parser["models_key"]:
        for key in parser["models_key"].split("."):
            if not isinstance(items, dict):
                items = None
                break
            items = items.get(key)

    items_mode = parser.get("items_mode", "list")

    if items_mode == "object_keys":
        if not isinstance(items, dict):
            raise ValueError("Model object was not found in the provider response.")

        return [
            {"id": str(key), "name": str(key)}
            for key in items
            if str(key).strip()
        ]

    if items_mode != "list":
        raise ValueError(f"Unsupported items_mode: {items_mode}")

    if not isinstance(items, list):
        raise ValueError("Model list was not found in the provider response.")

    models = []
    seen = set()

    for item in items:
        if not isinstance(item, dict):
            continue

        model_id = item.get(parser["id_field"])
        if not isinstance(model_id, str) or not model_id.strip():
            continue

        model_id = model_id.strip()
        if model_id in seen:
            continue

        seen.add(model_id)

        name = item.get(parser["name_field"])
        models.append({
            "id": model_id,
            "name": name.strip() if isinstance(name, str) and name.strip() else model_id,
        })

    return models


async def _discover_provider_models(spec: dict) -> dict:
    """Test public and authenticated discovery routes independently."""

    spec = _validate_discovery_spec(spec)

    route_results = {}
    all_models = {}
    auth = spec["authentication"]

    api_key = ""
    if spec["api_key_env"]:
        api_key = get_env_value(spec["api_key_env"])

    async with httpx.AsyncClient(timeout=30.0) as client:
        for route_name, route in spec["discovery"].items():
            if not route["enabled"]:
                route_results[route_name] = {
                    "enabled": False,
                    "success": False,
                    "model_count": 0,
                    "samples": [],
                    "error": "Disabled",
                }
                continue

            headers = {}

            if route_name == "authenticated" and auth["mode"] != "none":
                if not api_key:
                    route_results[route_name] = {
                        "enabled": True,
                        "success": False,
                        "model_count": 0,
                        "samples": [],
                        "error": "API key is not configured on the server.",
                    }
                    continue

                if auth["mode"] == "bearer":
                    headers["Authorization"] = f"Bearer {api_key}"
                elif auth["mode"] == "header":
                    headers[auth["header_name"]] = api_key

            url = spec["base_url"] + route["path"]

            try:
                response = await client.get(url, headers=headers)
                response.raise_for_status()

                models = _extract_discovered_models(
                    response.json(),
                    spec["response_parser"],
                )

                route_results[route_name] = {
                    "enabled": True,
                    "success": bool(models),
                    "model_count": len(models),
                    "samples": models[:3],
                    "error": None if models else "No valid models were returned.",
                }

                for model in models:
                    all_models.setdefault(model["id"], model)

            except httpx.HTTPStatusError as exc:
                route_results[route_name] = {
                    "enabled": True,
                    "success": False,
                    "model_count": 0,
                    "samples": [],
                    "error": f"HTTP {exc.response.status_code}",
                }

            
            except ValueError as exc:
                route_results[route_name] = {
                    "enabled": True,
                    "success": False,
                    "model_count": 0,
                    "samples": [],
                    "error": f"Parser error: {exc}",
                }
            
            except httpx.HTTPError as exc:
                route_results[route_name] = {
                    "enabled": True,
                    "success": False,
                    "model_count": 0,
                    "samples": [],
                    "error": f"HTTP request error: {type(exc).__name__}: {exc}",
                }

    models = list(all_models.values())

    return {
        "provider_id": spec["provider_id"],
        "display_name": spec["display_name"],
        "routes": route_results,
        "models": models,
        "unique_model_count": len(models),
        "can_add": len(models) > 0,
    }



BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


class SequentialResponsesMiddleware:
    """Serialize Codex requests to /v1/responses."""

    LOCK = asyncio.Lock()

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope.get("path") != "/v1/responses"
        ):
            await self.app(scope, receive, send)
            return

        await self.LOCK.acquire()

        try:
            await self.app(scope, receive, send)
        finally:
            self.LOCK.release()

MT5_REQUEST_LOCK = asyncio.Lock()

MT5_CLIENT_ID = "mt5_terminal_01"


MT5_STATS_DB = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "mt5_stats.sqlite3"
)


def _init_mt5_stats_db():
    MT5_STATS_DB.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(MT5_STATS_DB) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mt5_stats (
                client_id TEXT PRIMARY KEY,
                requests INTEGER NOT NULL DEFAULT 0,
                bytes INTEGER NOT NULL DEFAULT 0,
                characters INTEGER NOT NULL DEFAULT 0,
                words INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT
            )
        """)


def _record_mt5_stats(raw_body: bytes):
    text = raw_body.decode("utf-8")
    byte_count = len(raw_body)
    character_count = len(text)
    word_count = len(text.split())
    updated_at = datetime.now(timezone.utc).isoformat()

    _init_mt5_stats_db()

    with sqlite3.connect(MT5_STATS_DB) as conn:
        conn.execute("""
            INSERT INTO mt5_stats (
                client_id,
                requests,
                bytes,
                characters,
                words,
                updated_at
            )
            VALUES (?, 1, ?, ?, ?, ?)
            ON CONFLICT(client_id) DO UPDATE SET
                requests = requests + 1,
                bytes = bytes + excluded.bytes,
                characters = characters + excluded.characters,
                words = words + excluded.words,
                updated_at = excluded.updated_at
        """, (
            MT5_CLIENT_ID,
            byte_count,
            character_count,
            word_count,
            updated_at,
        ))


def _get_mt5_stats():
    _init_mt5_stats_db()

    with sqlite3.connect(MT5_STATS_DB) as conn:
        conn.row_factory = sqlite3.Row

        row = conn.execute(
            """
            SELECT requests, bytes, characters, words, updated_at
            FROM mt5_stats
            WHERE client_id = ?
            """,
            (MT5_CLIENT_ID,),
        ).fetchone()

    if row is None:
        return {
            "requests": 0,
            "bytes": 0,
            "characters": 0,
            "words": 0,
            "updated_at": None,
        }

    return dict(row)


app = FastAPI(
    title="MyCode Gateway",
    description="A private model-routing gateway for coding assistants.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(SequentialResponsesMiddleware)

@app.post("/api/internal/responses/consume")
async def consume_buffered_response(request: Request):
    global BUFFERED_RESPONSE_ACTIVE
    global BUFFERED_RESPONSE_ERROR

    supplied_token = request.headers.get(
        "X-Gateway-Internal-Token",
        "",
    )

    if not RESPONSE_BUFFER_TOKEN or not secrets.compare_digest(
        supplied_token,
        RESPONSE_BUFFER_TOKEN,
    ):
        return JSONResponse(
            status_code=401,
            content={
                "status": "unauthorized",
                "message": "Invalid internal token.",
            },
        )

    if not BUFFERED_RESPONSE_ACTIVE:
        return JSONResponse(
            status_code=404,
            content={
                "status": "not_found",
                "message": "No active buffered response.",
            },
        )

    if BUFFERED_RESPONSE_ERROR:
        error_message = BUFFERED_RESPONSE_ERROR

        BUFFERED_RESPONSE_ACTIVE = False
        BUFFERED_RESPONSE_ERROR = None

        return JSONResponse(
            status_code=502,
            content={
                "status": "failed",
                "error": error_message,
            },
        )

    if not RESPONSE_BUFFER_PATH.exists():
        return JSONResponse(
            status_code=202,
            content={
                "status": "processing",
            },
        )

    try:
        response_payload = json.loads(
            RESPONSE_BUFFER_PATH.read_text(
                encoding="utf-8",
            )
        )

    except (OSError, ValueError) as exc:
        return JSONResponse(
            status_code=500,
            content={
                "status": "buffer_read_error",
                "error": str(exc),
            },
        )

    RESPONSE_BUFFER_PATH.unlink(missing_ok=True)

    BUFFERED_RESPONSE_ACTIVE = False
    BUFFERED_RESPONSE_ERROR = None

    return JSONResponse(
        status_code=200,
        content=response_payload,
    )


@app.get("/health")
async def health():
    return {"status": "ok", "app": "MyCode Gateway", "version": "0.1.0"}

@app.post("/v1/mt5/ingest")
async def mt5_ingest(request: Request):
    async with MT5_REQUEST_LOCK:
        try:
            raw_body = await request.body()
            payload = json.loads(raw_body)

        except Exception:
            raise HTTPException(
                status_code=400,
                detail="Request body must be valid JSON.",
            ) from None

        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=400,
                detail="Request body must be a JSON object.",
            )

        _record_mt5_stats(raw_body)

        return {
            "success": True,
            "consumer": "mt5",
            "client_id": MT5_CLIENT_ID,
            "received": True,
        }



@app.get("/v1/mt5/response/{client_id}")
async def mt5_response(client_id: str):
    if client_id != MT5_CLIENT_ID:
        raise HTTPException(
            status_code=404,
            detail="MT5 client not found.",
        )

    return {
        "success": True,
        "client_id": MT5_CLIENT_ID,
        "statistics": _get_mt5_stats(),
    }
    
@app.get("/", response_class=HTMLResponse)
async def dashboard():
    page = TEMPLATES_DIR / "index.html"
    return HTMLResponse(page.read_text(encoding="utf-8"))


@app.get("/api/config")
async def public_config():
    return get_public_config()


@app.get("/api/providers")
async def providers():
    return get_public_config()["providers"]



@app.post("/api/providers/discover")
async def discover_provider(request: Request):
    """Test provider discovery routes without saving configuration."""

    try:
        spec = await request.json()
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Request body must be valid JSON.",
        )

    if not isinstance(spec, dict):
        raise HTTPException(
            status_code=400,
            detail="Request body must be a JSON object.",
        )

    try:
        result = await _discover_provider_models(spec)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from None

    return result



@app.post("/api/providers")
async def add_provider(request: Request):
    """Add a provider after server-side discovery and validation."""

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Request body must be valid JSON.",
        )

    if not isinstance(body, dict):
        raise HTTPException(
            status_code=400,
            detail="Request body must be a JSON object.",
        )

    try:
        spec = _validate_discovery_spec(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from None

    provider_id = spec["provider_id"]

    config = load_config()

    if provider_id in config["providers"]:
        raise HTTPException(
            status_code=409,
            detail=f"Provider '{provider_id}' already exists.",
        )

    # Always rediscover models on the server.
    # Never trust model data submitted by the browser.
    result = await _discover_provider_models(spec)

    models = result["models"]

    if not models:
        raise HTTPException(
            status_code=400,
            detail="Provider returned no valid models. Provider was not added.",
        )

    provider = {
        "display_name": spec["display_name"],
        "base_url": spec["base_url"],
        "api_key_env": spec["api_key_env"],
        "enabled": spec["enabled"],
        "authentication": spec["authentication"],
        "discovery": spec["discovery"],
        "response_parser": spec["response_parser"],
        "models": models,
    }

    config["providers"][provider_id] = provider

    save_config(config)

    catalog = rebuild_large_catalog(config)

    return {
        "success": True,
        "provider": {
            "id": provider_id,
            "display_name": spec["display_name"],
            "base_url": spec["base_url"],
            "api_key_env": spec["api_key_env"],
            "enabled": spec["enabled"],
            "model_count": len(models),
        },
        "large_catalog_count": catalog["model_count"],
        "large_catalog_updated_at": catalog["updated_at"],
    }





@app.delete("/api/providers/{provider_name}")
async def remove_provider(provider_name: str):
    """Remove a provider and all its associated data."""
    config = load_config()

    if provider_name not in config["providers"]:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_name}' not found")

    # Get models belonging to this provider for reporting
    provider_models = config["providers"].get(provider_name, {}).get("models", [])
    removed_model_count = len(provider_models)

    # Remove provider from config
    del config["providers"][provider_name]
    save_config(config)

    # Remove models from large catalog
    catalog_path = Path(__file__).resolve().parent.parent / "data" / "large_catalog.json"

    try:
        with catalog_path.open("r", encoding="utf-8") as f:
            catalog = json.load(f)
    except (json.JSONDecodeError, OSError):
        catalog = {"model_count": 0, "updated_at": None, "models": []}

    models = catalog.get("models", [])
    normalized_provider = _normalize_provider_name(provider_name)
    provider_key_prefix = normalized_provider + ":"

    remaining_models = []
    for m in models:
        key = m.get("key", "")
        if key and key.startswith(provider_key_prefix):
            continue
        remaining_models.append(m)

    catalog["models"] = remaining_models
    catalog["model_count"] = len(remaining_models)
    catalog["updated_at"] = datetime.now(timezone.utc).isoformat()

    with catalog_path.open("w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)
        f.write("\n")

    return {
        "success": True,
        "removed_provider": provider_name,
        "removed_model_count": removed_model_count,
        "catalog_model_count": len(remaining_models),
    }


@app.get("/api/thinker-room/catalog")
async def large_catalog():
    return load_large_catalog()

@app.get("/api/rotation/status")
async def rotation_status():
    return get_rotation_status()

@app.post("/api/providers/{provider_name}/refresh-models")
async def refresh_models(provider_name: str):
    config = load_config()
    provider = config["providers"].get(provider_name)

    if not provider:
        raise HTTPException(status_code=404, detail="Unknown provider.")

    base_url = provider.get("base_url", "").rstrip("/")
    if not base_url:
        raise HTTPException(status_code=400, detail="Provider base URL is empty.")

    key_name = provider.get("api_key_env", "")
    api_key = get_env_value(key_name) if key_name else ""
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail=f"API key is missing. Configure {key_name} in the local .env file.",
        )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{base_url}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Provider returned HTTP {exc.response.status_code}. Check the API key and provider settings.",
        ) from None
    except (httpx.HTTPError, ValueError):
        raise HTTPException(
            status_code=502,
            detail="Could not retrieve a valid model list from the provider.",
        ) from None

    items = payload.get("data", []) if isinstance(payload, dict) else []
    if not isinstance(items, list):
        raise HTTPException(status_code=502, detail="Unexpected model-list response.")

    models = []
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            models.append({
                "id": item["id"],
                "name": item.get("name") or item["id"],
            })

    provider["models"] = models
    provider["enabled"] = True

    # Save the refreshed provider list.
    save_config(config)

    # Rebuild the large catalog from all current provider lists.
    catalog = rebuild_large_catalog(config)

    return {
        "provider": provider_name,
        "model_count": len(models),
        "models": models,
        "large_catalog_count": catalog["model_count"],
        "large_catalog_updated_at": catalog["updated_at"],
    }


def _record_rotation_result(
    model_key: str,
    input_chars: int,
    consumer_id: str,
    output_chars: int = 0,
    success: bool = False,
    ends_model_test: bool = False,
    error_type: str | None = None,
    error_message: str | None = None,
    log_value: int | str | None = None,
) -> None:
    """ثبت نتیجه Rotation و نوشتن لاگ سه‌ستونی."""
    try:
        result = record_request_result(
            model_key=model_key,
            input_chars=input_chars,
            output_chars=output_chars,
            success=success,
            ends_model_test=ends_model_test,
            error_type=error_type,
            error_message=error_message,
            consumer_id=consumer_id,  # MODIFIED: Pass consumer_id
        )

        provider_name, separator, model_name = (
            str(result["model_key"]).partition(":")
        )

        if not separator:
            model_name = str(result["model_key"])
            provider_name = ""

        if log_value is not None:
            value = log_value
        elif success:
            value = result["lifetime_chars"]
        else:
            value = error_type or "ERROR"

        _short_gateway_log(
            model=model_name,
            provider=provider_name,
            value=value,
        )

        _gateway_log(
            "[ROTATION] "
            f"model={result['model_key']} "
            f"success={result['success']} "
            f"chars={result['lifetime_chars']} "
            f"status={result['test_status']}"
        )

    except (RuntimeError, ValueError, OSError) as exc:
        _gateway_log(f"[ROTATION] Could not record result: {exc}")



def _is_permanent_model_error(status_code: int, content: bytes) -> bool:
    """فقط خطاهایی که به‌وضوح به مدل ناموجود یا نامعتبر مربوط‌اند."""
    if status_code in (404, 410):
        return True

    if status_code != 400:
        return False

    message = content.decode("utf-8", errors="replace").lower()

    model_error_phrases = (
        "model not found",
        "model does not exist",
        "unknown model",
        "unsupported model",
        "invalid model",
    )

    return any(phrase in message for phrase in model_error_phrases)


def _response_output_char_count(response: dict) -> int:
    """شمارش کاراکترهای متن خروجی و آرگومان‌های فراخوانی ابزارها."""
    total = 0

    for item in response.get("output", []):
        if not isinstance(item, dict):
            continue

        if item.get("type") == "message":
            for part in item.get("content", []):
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    total += len(part["text"])

        elif item.get("type") == "function_call":
            arguments = item.get("arguments", "")
            if isinstance(arguments, str):
                total += len(arguments)

    return total


@app.post("/v1/responses")
async def codex_responses(request: Request):

    print("[CODEX] Waiting for request body", flush=True)

    try:
        raw_body = await request.body()

        
        print(
            f"[CODEX] Request body received: {len(raw_body)} bytes",
            flush=True
        )
        print(
            f"[CODEX] Request ID: {request.headers.get('x-gateway-request-id', 'MISSING')}",
            flush=True
        )
        
        body = parse_json_object(raw_body)
        input_chars = len(raw_body.decode("utf-8"))
        # MODIFIED: Extract consumer identifier
        consumer_id = "codex"


    except (ValueError, UnicodeDecodeError):
        raise HTTPException(
            status_code=400,
            detail="Request body must be a valid JSON object.",
        ) from None

    global BUFFERED_RESPONSE_ACTIVE
    global BUFFERED_RESPONSE_ERROR

    chat_body = responses_to_chat(body)
    streaming = bool(chat_body.get("stream"))

    if RESPONSE_BUFFER_MODE == "buffered":

        if BUFFERED_RESPONSE_ACTIVE:
            return JSONResponse(
                status_code=409,
                content={
                    "status": "consumer_busy",
                    "message": (
                        "A previous buffered response "
                        "has not been consumed yet."
                    ),
                },
            )

        _clear_final_response_buffer()

        BUFFERED_RESPONSE_ERROR = None
        BUFFERED_RESPONSE_ACTIVE = True

    

    async def fetch_with_retries():

        attempt = 0

        # چرخه Retry عمداً نامحدود است.
        while True:

            attempt += 1

            selected_model = select_next_model(consumer_id)

            # اگر فعلاً مدلی انتخاب نشد، کمی صبر می‌کنیم
            # و دوباره Rotation را امتحان می‌کنیم.
            if selected_model is None:
                await asyncio.sleep(1)
                continue

            provider_name = _normalize_provider_name(
                selected_model.get("provider", "")
            )

            model_id = str(selected_model.get("id", ""))

            model_key = str(
                selected_model.get("key")
                or f"{provider_name}:{model_id}"
            )

            config = load_config()
            providers = config.get("providers", {})

            provider = next(
                (
                    value
                    for name, value in providers.items()
                    if _normalize_provider_name(name) == provider_name
                ),
                {},
            )

            base_url = str(
                provider.get("base_url", "")
            ).rstrip("/")

            key_name = provider.get("api_key_env", "")
            api_key = get_env_value(key_name) if key_name else ""

            # Provider غیرفعال یا ناقص هم یک شکست محسوب می‌شود.
            if (
                not provider.get("enabled", False)
                or not base_url
                or not api_key
                or not model_id
            ):

                error_message = (
                    f"Provider '{provider_name}' is disabled "
                    "or not fully configured."
                )

                _record_rotation_result(
                    model_key=model_key,
                    input_chars=input_chars,
                    success=False,
                    ends_model_test=True,
                    error_type="provider_not_configured",
                    error_message=error_message,
                consumer_id=consumer_id,)


                _gateway_log(
                    f"[RETRY] attempt={attempt} "
                    f"model={model_key} "
                    "reason=provider_not_configured"
                )

                continue

            buffer = ProviderResponseBuffer()

            client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    180.0,
                    connect=15.0,
                )
            )

            upstream = None

            try:

                # درخواست اصلی ثابت می‌ماند.
                # فقط مدل مقصد تغییر می‌کند.
                request_body = dict(chat_body)

                request_body["model"] = model_id

                # برای امکان Retry، پاسخ upstream
                # باید کامل دریافت شود.
                request_body["stream"] = False
                request_body.pop("stream_options", None)

                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                }

                upstream_request = client.build_request(
                    "POST",
                    f"{base_url}/chat/completions",
                    json=request_body,
                    headers=headers,
                )

                upstream = await client.send(
                    upstream_request,
                    stream=True,
                )

                # دریافت قطعه‌ای پاسخ در بافر.
                # تا ۲ مگابایت RAM؛ سپس فایل موقت دیسک.
                # حداکثر حجم کل ۵۰ مگابایت.
                async for chunk in upstream.aiter_bytes():
                    buffer.write(chunk)

                # هر خطای HTTP باعث انتخاب مدل بعدی می‌شود.
                if upstream.status_code >= 400:

                    content = buffer.read()

                    status_code = upstream.status_code

                    content_type = upstream.headers.get(
                        "content-type",
                        "application/json",
                    )

                    error_message = content.decode(
                        "utf-8",
                        errors="replace",
                    )[:500]

                    _record_rotation_result(
                        model_key=model_key,
                        input_chars=input_chars,
                        success=False,
                        ends_model_test=True,
                        error_type="provider_http_error",
                        error_message=error_message,
                        log_value=status_code,
                    consumer_id=consumer_id,)

                    _gateway_log(
                        f"[RETRY] attempt={attempt} "
                        f"model={model_key} "
                        f"HTTP={status_code}; trying next model."
                    )

                    continue

                # HTTP موفق است؛ حالا JSON را بررسی می‌کنیم.
                provider_payload = parse_json_object(
                    buffer.read()
                )

                choices = provider_payload.get("choices")

                if (
                    not isinstance(choices, list)
                    or not choices
                    or not isinstance(choices[0], dict)
                    or not isinstance(
                        choices[0].get("message"),
                        dict,
                    )
                ):
                    raise ValueError(
                        "Invalid Chat Completions response."
                    )

                converted = chat_to_responses_text(
                    provider_payload
                )

                if (
                    not isinstance(converted, dict)
                    or not isinstance(
                        converted.get("output"),
                        list,
                    )
                    or converted.get("status")
                    not in ("completed", "incomplete")
                ):
                    raise ValueError(
                        "Invalid converted Responses object."
                    )

                output_chars = _response_output_char_count(
                    converted
                )

                # فقط پاسخ کامل و معتبر موفق محسوب می‌شود.
                _record_rotation_result(
                    model_key=model_key,
                    input_chars=input_chars,
                    output_chars=output_chars,
                    success=True,
                consumer_id=consumer_id,)

                _gateway_log(
                    f"[RETRY] attempt={attempt} "
                    f"model={model_key} "
                    f"success=True "
                    f"output_chars={output_chars}"
                )

                return {
                    "success": True,
                    "response": converted,
                    "model_key": model_key,
                }

            except asyncio.CancelledError:
                # درخواست لغو شده؛ چرخه Retry متوقف می‌شود.
                raise

            except Exception as exc:

                if isinstance(exc, httpx.HTTPError):
                    error_type = "provider_connection_error"

                elif isinstance(exc, ValueError):
                    error_type = "invalid_provider_response"

                else:
                    error_type = "provider_attempt_error"

                error_message = str(exc)[:500]

                _record_rotation_result(
                    model_key=model_key,
                    input_chars=input_chars,
                    success=False,
                    ends_model_test=True,
                    error_type=error_type,
                    error_message=error_message,
                consumer_id=consumer_id,)

                _gateway_log(
                    f"[RETRY] attempt={attempt} "
                    f"model={model_key} "
                    f"error={error_type}: {error_message}; "
                    "trying next model."
                )

            finally:

                if upstream is not None:
                    try:
                        await upstream.aclose()
                    except Exception:
                        pass

                try:
                    await client.aclose()
                except Exception:
                    pass

                try:
                    buffer.close()
                except Exception:
                    pass

    # -------------------------------------------------
    # Buffered response for Laravel
    # -------------------------------------------------

    if RESPONSE_BUFFER_MODE == "buffered":

        async def run_buffered_response():
            global BUFFERED_RESPONSE_ERROR

            try:
                result = await fetch_with_retries()

                _write_final_response_buffer(
                    result["response"]
                )

                _gateway_log(
                    "[BUFFERED] Final response saved successfully."
                )

            except asyncio.CancelledError:
                BUFFERED_RESPONSE_ERROR = (
                    "Background response task was cancelled."
                )
                raise

            except Exception as exc:
                BUFFERED_RESPONSE_ERROR = str(exc)

                _gateway_log(
                    f"[BUFFERED] Background task failed: {exc}"
                )

        task = asyncio.create_task(
            run_buffered_response()
        )

        BACKGROUND_RESPONSE_TASKS.add(task)
        task.add_done_callback(
            BACKGROUND_RESPONSE_TASKS.discard
        )

        return JSONResponse(
            status_code=202,
            content={
                "status": "processing",
                "message": "Response processing started.",
            },
        )

    # -------------------------------------------------
    # Original direct streaming response to Codex
    # -------------------------------------------------

    if streaming:

        async def stream_response():

            task = asyncio.create_task(
                fetch_with_retries()
            )

            try:

                while not task.done():

                    done, _ = await asyncio.wait(
                        {task},
                        timeout=15.0,
                    )

                    if not done:
                        yield ": heartbeat\n\n"

                result = await task

                for event in _responses_to_sse_events(
                    result["response"]
                ):
                    yield event

            except asyncio.CancelledError:

                if not task.done():
                    task.cancel()

                await asyncio.gather(
                    task,
                    return_exceptions=True,
                )

                raise

        return StreamingResponse(
            stream_response(),
            status_code=200,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # -------------------------------------------------
    # Original direct non-streaming response
    # -------------------------------------------------

    result = await fetch_with_retries()

    return Response(
        content=json.dumps(
            result["response"],
            ensure_ascii=False,
        ),
        media_type="application/json",
    )




if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8088")),
        reload=True,
    )

