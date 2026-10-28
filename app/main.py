import json
import os
import asyncio

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
)

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



@app.get("/api/thinker-room/catalog")
async def large_catalog():
    return load_large_catalog()


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

            _record_rotation_result(
                model_key=model_key,
                input_chars=input_chars,
                output_chars=output_chars,
                success=stream_completed,
                error_type=(
                    None
                    if stream_completed
                    else "incomplete_stream"
                ),
                error_message=(
                    None
                    if stream_completed
                    else stream_error or "Stream ended without [DONE]."
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

