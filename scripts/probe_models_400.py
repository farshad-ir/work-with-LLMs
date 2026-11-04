import asyncio
import json
import re
import sys
import time
from pathlib import Path

import httpx


ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app.config import load_config, get_env_value


CATALOG_PATH = ROOT_DIR / "data" / "large_catalog.json"

PAUSE_EVERY = 5
PROBE_TIMEOUT_SECONDS = 8
MAX_ERROR_BODY_CHARS = 12000

PROMPT = "زندگی چه معنی دارد وقتی اینهمه جنگ و خونریزی و کشت و کشتار است؟"


def save_catalog(catalog):
    temp_path = CATALOG_PATH.with_suffix(".json.tmp")

    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(catalog, file, ensure_ascii=False, indent=2)
        file.write("\n")

    temp_path.replace(CATALOG_PATH)


def get_provider_config(config, provider_name):
    return config["providers"].get(provider_name)


def build_headers(provider):
    authentication = provider.get("authentication", {})
    mode = authentication.get("mode", "bearer")

    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }

    if mode == "none":
        return headers

    key_name = provider.get("api_key_env", "")
    api_key = get_env_value(key_name) if key_name else ""

    if not api_key:
        raise ValueError(f"Missing API key: {key_name}")

    if mode == "bearer":
        headers["Authorization"] = f"Bearer {api_key}"

    elif mode == "header":
        header_name = authentication.get(
            "header_name",
            "Authorization",
        )
        headers[header_name] = api_key

    else:
        raise ValueError(f"Unsupported authentication mode: {mode}")

    return headers


def get_secrets(provider):
    """
    Collect configured API keys so they can never appear in diagnostics.
    """
    secrets = []

    key_name = provider.get("api_key_env", "")
    if key_name:
        try:
            api_key = get_env_value(key_name)
            if api_key:
                secrets.append(api_key)
        except Exception:
            pass

    return secrets


def redact_sensitive_text(text, secrets=None):
    """
    Remove known API keys and common token patterns from diagnostic output.
    """
    secrets = secrets or []

    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")

    text = re.sub(
        r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s\"',}]+",
        r"\1[REDACTED]",
        text,
    )

    text = re.sub(
        r"(?i)(api[_-]?key\s*[:=]\s*)[^\s\"',}]+",
        r"\1[REDACTED]",
        text,
    )

    return text


def format_response_body(body, secrets=None):
    """
    Make the actual upstream response body readable.
    """
    if not body:
        return "(Response body is empty)"

    try:
        parsed = json.loads(body)
        formatted = json.dumps(
            parsed,
            ensure_ascii=False,
            indent=2,
        )
    except (json.JSONDecodeError, TypeError):
        formatted = body

    formatted = redact_sensitive_text(formatted, secrets)

    if len(formatted) > MAX_ERROR_BODY_CHARS:
        formatted = (
            formatted[:MAX_ERROR_BODY_CHARS]
            + "\n...[OUTPUT TRUNCATED]"
        )

    return formatted


def extract_text(event):
    choices = event.get("choices", [])

    if not choices:
        return ""

    choice = choices[0]
    delta = choice.get("delta") or {}

    content = delta.get("content")

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        return "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict)
        )

    return choice.get("text") or ""


def get_safe_response_metadata(response):
    """
    Return only useful, non-sensitive response headers.
    """
    names = (
        "content-type",
        "x-request-id",
        "request-id",
        "cf-ray",
        "retry-after",
    )

    metadata = {}

    for name in names:
        value = response.headers.get(name)
        if value:
            metadata[name] = value

    return metadata


def print_http_error(response, secrets=None):
    status = response.status_code

    # 402 is intentionally kept short.
    if status == 402:
        print(
            "FAILED (HTTP 402: Payment Required / "
            "billing, credit or subscription issue)"
        )
        return

    body = response.text
    metadata = get_safe_response_metadata(response)

    print(f"\n    HTTP STATUS: {status}")

    if metadata:
        print("    RESPONSE METADATA:")
        for name, value in metadata.items():
            print(f"      {name}: {value}")

    print("    SERVER RESPONSE BODY:")
    formatted_body = format_response_body(body, secrets)

    for line in formatted_body.splitlines():
        print(f"      {line}")


async def probe_model(client, model, provider):
    model_id = model["id"]
    base_url = provider.get("base_url", "").rstrip("/")

    if not base_url:
        return False, "Missing provider URL", 0.0

    started_at = time.monotonic()
    secrets = get_secrets(provider)

    try:
        headers = build_headers(provider)

        payload = {
            "model": model_id,
            "messages": [
                {
                    "role": "user",
                    "content": PROMPT,
                }
            ],
            "stream": True,
            "max_tokens": 24,
        }

        collected_text = ""

        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            async with client.stream(
                "POST",
                f"{base_url}/chat/completions",
                json=payload,
                headers=headers,
            ) as response:

                if response.status_code >= 400:
                    # Read the actual error body before leaving the stream.
                    await response.aread()

                    elapsed = time.monotonic() - started_at

                    print_http_error(response, secrets)

                    return (
                        False,
                        f"HTTP {response.status_code}",
                        elapsed,
                    )

                async for line in response.aiter_lines():

                    if not line.startswith("data:"):
                        continue

                    data = line[5:].strip()

                    if not data or data == "[DONE]":
                        break

                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    # Some providers send an error inside an HTTP 200 stream.
                    if isinstance(event, dict) and event.get("error"):
                        error_text = json.dumps(
                            event["error"],
                            ensure_ascii=False,
                            indent=2,
                        )
                        error_text = redact_sensitive_text(
                            error_text,
                            secrets,
                        )

                        print("\n    STREAM ERROR:")
                        for error_line in error_text.splitlines():
                            print(f"      {error_line}")

                        elapsed = time.monotonic() - started_at
                        return False, "Stream returned an error", elapsed

                    collected_text += extract_text(event)

                    if len(collected_text.split()) >= 2:
                        elapsed = time.monotonic() - started_at
                        return True, "First words received", elapsed

        elapsed = time.monotonic() - started_at
        return False, "Stream ended before two words", elapsed

    except TimeoutError:
        elapsed = time.monotonic() - started_at
        return False, "Async timeout", elapsed

    except httpx.TimeoutException as exc:
        elapsed = time.monotonic() - started_at
        return (
            False,
            f"HTTPX timeout: {type(exc).__name__}",
            elapsed,
        )

    except httpx.RequestError as exc:
        elapsed = time.monotonic() - started_at

        detail = redact_sensitive_text(
            str(exc),
            secrets,
        )

        print("\n    NETWORK ERROR:")
        print(f"      Type: {type(exc).__name__}")
        print(f"      Detail: {detail or '(No additional details)'}")

        return False, type(exc).__name__, elapsed

    except Exception as exc:
        elapsed = time.monotonic() - started_at

        detail = redact_sensitive_text(
            str(exc),
            secrets,
        )

        print("\n    UNEXPECTED ERROR:")
        print(f"      Type: {type(exc).__name__}")
        print(f"      Detail: {detail or '(No additional details)'}")

        return False, type(exc).__name__, elapsed


def ask_to_continue():
    print()
    print("-" * 60)
    print(
        f"{PAUSE_EVERY} models tested. "
        "Review and copy the output above."
    )
    print("Press Enter to continue, or type q to stop.")
    print("-" * 60)

    try:
        answer = input("> ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False

    return answer != "q"


async def main():
    config = load_config()

    if not CATALOG_PATH.exists():
        raise FileNotFoundError(CATALOG_PATH)

    with CATALOG_PATH.open("r", encoding="utf-8") as file:
        catalog = json.load(file)

    models = catalog.get("models", [])

    if not isinstance(models, list):
        raise ValueError("Invalid models list in catalog")

    confirmed = sum(
        1 for model in models
        if model.get("test_status") == "confirmed"
    )

    failed = sum(
        1 for model in models
        if model.get("test_status") == "failed"
    )

    print(f"Models: {len(models)}")
    print(f"Already confirmed: {confirmed}")
    print(f"Already failed: {failed}")
    print(f"Pause after every {PAUSE_EVERY} tested models.")
    print("-" * 60)

    timeout = httpx.Timeout(
        PROBE_TIMEOUT_SECONDS,
        connect=5.0,
    )

    tested_total = 0
    tested_since_pause = 0
    stopped_by_user = False

    async with httpx.AsyncClient(timeout=timeout) as client:

        for index, model in enumerate(models, start=1):

            if model.get("test_status") in ("confirmed", "failed"):
                continue

            model_key = model.get("key", model.get("id", "unknown"))
            provider_name = model.get("provider", "")

            provider = get_provider_config(
                config,
                provider_name,
            )

            print()
            print("=" * 60)
            print(f"[{index}/{len(models)}] {model_key}")
            print(f"Provider: {provider_name}")
            print("=" * 60)

            if not provider:
                success = False
                reason = "Provider not found"
                elapsed = 0.0

                print("    ERROR: Provider configuration not found.")

            else:
                success, reason, elapsed = await probe_model(
                    client,
                    model,
                    provider,
                )

            model["test_status"] = (
                "confirmed" if success else "failed"
            )

            tested_total += 1
            tested_since_pause += 1

            if success:
                confirmed += 1
                print(
                    f"\n    RESULT: CONFIRMED "
                    f"({elapsed:.2f}s)"
                )
            else:
                failed += 1
                print(
                    f"\n    RESULT: FAILED "
                    f"({reason}, {elapsed:.2f}s)"
                )

            # Save after each group so stopping never loses its results.
            if tested_since_pause >= PAUSE_EVERY:
                save_catalog(catalog)
                print("\n    [SAVED] Catalog updated.")

                tested_since_pause = 0

                if not ask_to_continue():
                    stopped_by_user = True
                    break

    if tested_since_pause > 0:
        save_catalog(catalog)
        print("\n[SAVED] Final results updated.")

    print("\n" + "=" * 60)

    if stopped_by_user:
        print("Probe stopped by user.")
    else:
        print("Probe completed.")

    print(f"Tested in this run: {tested_total}")
    print(f"Confirmed: {confirmed}")
    print(f"Failed: {failed}")
    print(f"Total models: {len(models)}")


if __name__ == "__main__":
    asyncio.run(main())
