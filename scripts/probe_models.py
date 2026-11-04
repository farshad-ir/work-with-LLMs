import asyncio
import json
import sys
from pathlib import Path

import httpx


ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app.config import load_config, get_env_value


CATALOG_PATH = ROOT_DIR / "data" / "large_catalog.json"

BATCH_SIZE = 100
PROBE_TIMEOUT_SECONDS = 8

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


async def probe_model(client, model, provider):
    model_id = model["id"]
    base_url = provider.get("base_url", "").rstrip("/")

    if not base_url:
        return False, "Missing provider URL"

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

                response.raise_for_status()

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

                    collected_text += extract_text(event)

                    if len(collected_text.split()) >= 2:
                        return True, "First words received"

        return False, "Stream ended before two words"

    except TimeoutError:
        return False, "Timeout"

    except httpx.HTTPStatusError as exc:
        return False, f"HTTP {exc.response.status_code}"

    except Exception as exc:
        return False, str(exc)[:200]


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
    print("-" * 60)

    timeout = httpx.Timeout(
        PROBE_TIMEOUT_SECONDS,
        connect=5.0,
    )

    tested_since_save = 0

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

            print(
                f"[{index}/{len(models)}] Testing {model_key} ... ",
                end="",
                flush=True,
            )

            if not provider:
                success = False
                reason = "Provider not found"

            else:
                success, reason = await probe_model(
                    client,
                    model,
                    provider,
                )

            model["test_status"] = (
                "confirmed" if success else "failed"
            )

            tested_since_save += 1

            if success:
                confirmed += 1
                print("CONFIRMED")
            else:
                failed += 1
                print(f"FAILED ({reason})")

            if tested_since_save >= BATCH_SIZE:
                save_catalog(catalog)
                tested_since_save = 0
                print("  [SAVED] Catalog updated.")

    if tested_since_save > 0:
        save_catalog(catalog)
        print("  [SAVED] Final batch updated.")

    print("\n" + "=" * 60)
    print("Probe completed")
    print(f"Confirmed: {confirmed}")
    print(f"Failed: {failed}")
    print(f"Total: {len(models)}")


if __name__ == "__main__":
    asyncio.run(main())

