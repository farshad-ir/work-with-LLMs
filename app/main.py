import json
import os
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

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="MyCode Gateway",
    description="A private model-routing gateway for coding assistants.",
    version="0.1.0",
    lifespan=lifespan,
)


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
    save_config(config)

    return {
        "provider": provider_name,
        "model_count": len(models),
        "models": models,
    }



@app.post("/v1/responses")
async def codex_responses(request: Request):
    config = load_config()
    provider = config["providers"].get("openrouter", {})

    base_url = provider.get("base_url", "").rstrip("/")
    key_name = provider.get("api_key_env", "OPENROUTER_API_KEY")
    api_key = get_env_value(key_name)

    if not base_url:
        raise HTTPException(
            status_code=503,
            detail="OpenRouter base URL is not configured.",
        )

    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="OpenRouter API key is not configured on the gateway.",
        )

    try:
        body = parse_json_object(await request.body())
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(
            status_code=400,
            detail="Request body must be a valid JSON object.",
        ) from None

    chat_body = responses_to_chat(body)
    streaming = bool(chat_body.get("stream"))

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream" if streaming else "application/json",
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
    except httpx.HTTPError:
        await client.aclose()
        raise HTTPException(
            status_code=502,
            detail="Could not connect to OpenRouter Chat Completions API.",
        ) from None

    if upstream.status_code >= 400:
        content = await upstream.aread()
        status_code = upstream.status_code
        content_type = upstream.headers.get("content-type", "application/json")
        await upstream.aclose()
        await client.aclose()
        return Response(
            content=content,
            status_code=status_code,
            headers={"Content-Type": content_type},
        )

    if not streaming:
        try:
            upstream_payload = upstream.json()
            converted = chat_to_responses_text(upstream_payload)
            content = json.dumps(converted, ensure_ascii=False)
        except (ValueError, TypeError, AttributeError):
            await upstream.aclose()
            await client.aclose()
            raise HTTPException(
                status_code=502,
                detail="OpenRouter returned an invalid Chat Completions response.",
            ) from None

        await upstream.aclose()
        await client.aclose()
        return Response(content=content, media_type="application/json")

    async def convert_stream():
        converter = ResponsesStreamConverter()
        event_lines = []

        try:
            async for line in upstream.aiter_lines():
                if line == "":
                    if event_lines:
                        parsed = parse_chat_sse_event("\n".join(event_lines))
                        event_lines = []
                        if parsed:
                            for output_event in converter.feed(parsed):
                                yield output_event
                else:
                    event_lines.append(line)

            if event_lines:
                parsed = parse_chat_sse_event("\n".join(event_lines))
                if parsed:
                    for output_event in converter.feed(parsed):
                        yield output_event

            for output_event in converter.finish():
                yield output_event

        finally:
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
