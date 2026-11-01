import json
import os
import asyncio
import re
from datetime import datetime, timezone

from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse

from app.responses_adapter import (
    ResponsesStreamConverter,
    chat_to_responses_text,
    parse_chat_sse_event,
    parse_json_object,
    responses_to_chat,
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
    """Serialize complete /v1/responses requests, including streaming."""

    def __init__(self, app):
        self.app = app
        self.lock = asyncio.Lock()

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope.get("path") != "/v1/responses"
        ):
            await self.app(scope, receive, send)
            return

        await self.lock.acquire()

        try:
            await self.app(scope, receive, send)
        finally:
            self.lock.release()

app = FastAPI(
    title="MyCode Gateway",
    description="A private model-routing gateway for coding assistants.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(SequentialResponsesMiddleware)

@app.get("/health")
async def health():
    return {"status": "ok", "app": "MyCode Gateway", "version": "0.1.0"}


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
    output_chars: int = 0,
    success: bool = False,
    ends_model_test: bool = False,
    error_type: str | None = None,
    error_message: str | None = None,
) -> None:
    """ثبت نتیجه؛ خطای ثبت نباید پاسخ جاری Codex را خراب کند."""
    try:
        result = record_request_result(
            model_key=model_key,
            input_chars=input_chars,
            output_chars=output_chars,
            success=success,
            ends_model_test=ends_model_test,
            error_type=error_type,
            error_message=error_message,
        )
        print(
            "[ROTATION] "
            f"model={result['model_key']} "
            f"success={result['success']} "
            f"chars={result['lifetime_chars']} "
            f"status={result['test_status']}"
        )
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"[ROTATION] Could not record result: {exc}")


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
    config = load_config()

    try:
        raw_body = await request.body()
        body = parse_json_object(raw_body)
        input_chars = len(raw_body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(
            status_code=400,
            detail="Request body must be a valid JSON object.",
        ) from None


    # تبدیل درخواست ورودی؛ محتوای درخواست در تمام تلاش‌ها ثابت می‌ماند.
    chat_body = responses_to_chat(body)
    streaming = bool(chat_body.get("stream"))

    provider_aliases = {
        "nvidia_nim": "nvidia",
        "nvidia-nim": "nvidia",
        "tokenrouter": "token_router",
        "token-router": "token_router",
    }

    last_provider_error = None
    upstream = None
    client = None

    while True:

        # انتخاب مدل برای این تلاش
        selected_model = select_next_model()

        if selected_model is None:
            # اگر مدل‌های قبلی خطای قطعی داده‌اند، آخرین خطای واقعی
            # ارائه‌دهنده را برگردان؛ در غیر این صورت چرخه تمام شده است.
            if last_provider_error is not None:
                content, status_code, content_type = last_provider_error

                return Response(
                    content=content,
                    status_code=status_code,
                    headers={"Content-Type": content_type},
                )

            raise HTTPException(
                status_code=503,
                detail="All models have completed their tests.",
            )

        provider_name = str(
            selected_model.get("provider", "")
        ).strip().lower()

        provider_name = provider_aliases.get(
            provider_name,
            provider_name,
        )

        model_id = str(selected_model.get("id", ""))

        model_key = str(
            selected_model.get("key")
            or f"{provider_name}:{model_id}"
        )

        provider = config["providers"].get(provider_name, {})

        if not provider.get("enabled", False):
            raise HTTPException(
                status_code=503,
                detail=f"Provider '{provider_name}' is disabled.",
            )

        base_url = str(
            provider.get("base_url", "")
        ).rstrip("/")

        key_name = provider.get("api_key_env", "")
        api_key = get_env_value(key_name) if key_name else ""

        if not base_url or not api_key or not model_id:
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Provider '{provider_name}' is not fully configured. "
                    "Check its base URL, API key and model ID."
                ),
            )

        # در هر تلاش فقط مدل مقصد تغییر می‌کند.
        chat_body["model"] = model_id

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": (
                "text/event-stream"
                if streaming
                else "application/json"
            ),
        }

        client = httpx.AsyncClient(
            timeout=httpx.Timeout(180.0, connect=15.0)
        )

        try:
            upstream_request = client.build_request(
                "POST",
                f"{base_url}/chat/completions",
                json=chat_body,
                headers=headers,
            )

            upstream = await client.send(
                upstream_request,
                stream=streaming,
            )


        except httpx.HTTPError as exc:
            await client.aclose()

            _record_rotation_result(
                model_key=model_key,
                input_chars=input_chars,
                success=False,
                ends_model_test=True,
                error_type="provider_connection_error",
                error_message=str(exc)[:500],
            )

            print(
                "[ROTATION] "
                f"Model failed: {model_key}; "
                f"connection error; trying next model."
            )

            continue

        # خطای ارائه‌دهنده؛ هنوز هیچ پاسخی به Codex ارسال نشده است.
        if upstream.status_code >= 400:
            try:
                content = await upstream.aread()
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
                )
        
                last_provider_error = (
                    content,
                    status_code,
                    content_type,
                )
        
                print(
                    "[ROTATION] "
                    f"Model failed: {model_key}; "
                    f"HTTP {status_code}; trying next model."
                )
        
            finally:
                await upstream.aclose()
                await client.aclose()
        
            continue
        

        # پاسخ موفق HTTP داریم؛ ادامهٔ پردازش با همین مدل انجام می‌شود.
        break

    # پاسخ غیرجریانی
    if not streaming:
        try:
            upstream_payload = upstream.json()
            converted = chat_to_responses_text(upstream_payload)

            if not isinstance(converted, dict):
                raise ValueError("Unexpected response format.")

            content = json.dumps(converted, ensure_ascii=False)
            output_chars = _response_output_char_count(converted)

        except (ValueError, TypeError, AttributeError) as exc:
            _record_rotation_result(
                model_key=model_key,
                input_chars=input_chars,
                success=False,
                ends_model_test=True,
                error_type="invalid_provider_response",
                error_message=str(exc)[:500],
            )

            raise HTTPException(
                status_code=502,
                detail=f"Provider '{provider_name}' returned an invalid response.",
            ) from None

        finally:
            await upstream.aclose()
            await client.aclose()

        _record_rotation_result(
            model_key=model_key,
            input_chars=input_chars,
            output_chars=output_chars,
            success=True,
        )

        return Response(
            content=content,
            media_type="application/json",
        )

    # پاسخ جریانی
    async def convert_stream():
        converter = ResponsesStreamConverter()
        event_lines = []
        stream_completed = False
        stream_error = None

        try:
            async for line in upstream.aiter_lines():
                if line == "":
                    if event_lines:
                        parsed = parse_chat_sse_event(
                            "\n".join(event_lines)
                        )
                        event_lines = []

                        if parsed:
                            if parsed.get("type") == "done":
                                stream_completed = True
                            elif (
                                parsed.get("type") == "delta"
                                and parsed.get("finish_reason") is not None
                            ):
                                stream_completed = True

                            for output_event in converter.feed(parsed):
                                yield output_event

                else:
                    event_lines.append(line)

            if event_lines:
                parsed = parse_chat_sse_event(
                    "\n".join(event_lines)
                )

                if parsed:
                    if parsed.get("type") == "done":
                        stream_completed = True
                    elif (
                        parsed.get("type") == "delta"
                        and parsed.get("finish_reason") is not None
                    ):
                        stream_completed = True


                    for output_event in converter.feed(parsed):
                        yield output_event

            # تبدیل جریان را مانند قبل خاتمه می‌دهیم.
            for output_event in converter.finish():
                yield output_event

        except httpx.HTTPError as exc:
            stream_error = str(exc)[:500]

        finally:
            output_chars = len(converter.text)

            for tool in converter.tool_calls.values():
                arguments = tool.get("arguments", "")
                if isinstance(arguments, str):
                    output_chars += len(arguments)

            print(
                "[STREAM DEBUG] "
                f"model={model_key} "
                f"completed={stream_completed} "
                f"error={stream_error!r} "
                f"text_chars={len(converter.text)} "
                f"tool_calls={len(converter.tool_calls)}"
            )

            _record_rotation_result(
                model_key=model_key,
                input_chars=input_chars,
                output_chars=output_chars,
                success=stream_completed,
                ends_model_test=not stream_completed,
                error_type=(
                    None
                    if stream_completed
                    else "incomplete_stream"
                ),
                error_message=(
                    None
                    if stream_completed
                    else stream_error or "Stream ended without a completion event."
                ),
            )


            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        convert_stream(),
        status_code=upstream.status_code,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8088")),
        reload=True,
    )

