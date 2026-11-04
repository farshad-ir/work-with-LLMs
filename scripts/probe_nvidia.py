import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx


ROOT_DIR = Path(__file__).resolve().parent.parent

CATALOG_FILE = ROOT_DIR / "data" / "large_catalog.json"
REPORT_FILE = ROOT_DIR / "data" / "nvidia_probe_report.json"
ENV_FILE = ROOT_DIR / ".env"

API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

TIMEOUT = httpx.Timeout(60.0, connect=15.0)
MAX_TOKENS = 64

TEST_PROMPT = "Reply with a short greeting."


def load_nvidia_key():
    key = os.environ.get("NVIDIA_NIM_API_KEY", "").strip()

    if key:
        return key

    if not ENV_FILE.exists():
        raise RuntimeError(".env file not found")

    for line in ENV_FILE.read_text(
        encoding="utf-8"
    ).splitlines():

        line = line.strip()

        if not line or line.startswith("#"):
            continue

        if line.startswith("export "):
            line = line[7:].strip()

        if "=" not in line:
            continue

        name, value = line.split("=", 1)

        if name.strip() == "NVIDIA_NIM_API_KEY":
            value = value.strip().strip("\"'")

            if value:
                return value

    raise RuntimeError(
        "NVIDIA_NIM_API_KEY was not found in .env"
    )


def load_nvidia_models():
    if not CATALOG_FILE.exists():
        raise RuntimeError(
            f"Catalog not found: {CATALOG_FILE}"
        )

    catalog = json.loads(
        CATALOG_FILE.read_text(encoding="utf-8")
    )

    models = catalog.get("models", [])

    result = []

    for model in models:
        if not isinstance(model, dict):
            continue

        provider = str(
            model.get("provider", "")
        ).lower()

        key = str(model.get("key", "")).lower()

        if provider != "nvidia" and not key.startswith("nvidia:"):
            continue

        model_id = model.get("id")

        if not model_id:
            continue

        result.append({
            "key": model.get("key"),
            "id": model_id,
            "name": model.get("name") or model_id,
            "previous_status": model.get("test_status"),
        })

    return result


def redact(text, api_key):
    if not text:
        return text

    text = str(text)

    if api_key:
        text = text.replace(api_key, "[REDACTED]")

    text = re.sub(
        r"(?i)(Bearer\s+)[^\s\"']+",
        r"\1[REDACTED]",
        text
    )

    return text


def probe_model(client, api_key, model):
    model_id = model["id"]

    payload = {
        "model": model_id,
        "messages": [
            {
                "role": "user",
                "content": TEST_PROMPT
            }
        ],
        "max_tokens": MAX_TOKENS,
        "temperature": 1,
        "top_p": 0.95,
        "stream": True,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }

    started = time.monotonic()

    result = {
        "model": model_id,
        "name": model["name"],
        "key": model["key"],
        "previous_status": model["previous_status"],
        "status": "failed",
        "http_status": None,
        "response_model": None,
        "content_received": False,
        "reasoning_received": False,
        "error": None,
        "duration_seconds": None,
    }

    try:
        with client.stream(
            "POST",
            API_URL,
            headers=headers,
            json=payload,
        ) as response:

            result["http_status"] = response.status_code

            if response.status_code != 200:
                body = response.read().decode(
                    "utf-8",
                    errors="replace"
                )

                result["error"] = redact(body, api_key)

                return result

            for line in response.iter_lines():

                if not line.startswith("data:"):
                    continue

                data = line[5:].strip()

                if data == "[DONE]":
                    break

                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue

                if result["response_model"] is None:
                    result["response_model"] = event.get("model")

                if event.get("error"):
                    result["error"] = redact(
                        json.dumps(event["error"], ensure_ascii=False),
                        api_key
                    )
                    return result

                choices = event.get("choices", [])

                for choice in choices:
                    delta = choice.get("delta", {})

                    content = delta.get("content")
                    reasoning = delta.get("reasoning_content")

                    if isinstance(content, str) and content.strip():
                        result["content_received"] = True

                    if isinstance(reasoning, str) and reasoning.strip():
                        result["reasoning_received"] = True

            if (
                result["content_received"]
                or result["reasoning_received"]
            ):
                result["status"] = "confirmed"
            else:
                result["error"] = (
                    "HTTP 200 but no content or reasoning received"
                )

    except httpx.TimeoutException as exc:
        result["error"] = f"Timeout: {type(exc).__name__}"

    except httpx.RequestError as exc:
        result["error"] = (
            f"Network error: {type(exc).__name__}: {exc}"
        )

    except Exception as exc:
        result["error"] = (
            f"Unexpected error: {type(exc).__name__}: {exc}"
        )

    finally:
        result["duration_seconds"] = round(
            time.monotonic() - started,
            2
        )

    return result


def save_report(results):
    confirmed = sum(
        1 for item in results
        if item["status"] == "confirmed"
    )

    failed = len(results) - confirmed

    report = {
        "provider": "nvidia",
        "tested_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "total_models": len(results),
        "confirmed": confirmed,
        "failed": failed,
        "models": results,
    }

    REPORT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    REPORT_FILE.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    return confirmed, failed


def main():
    print("=" * 65)
    print("              NVIDIA MODEL PROBE")
    print("=" * 65)

    api_key = load_nvidia_key()
    models = load_nvidia_models()

    if not models:
        print("No NVIDIA models found in catalog.")
        return

    print(f"Models found: {len(models)}")
    print("All NVIDIA models will be tested.")
    print("Previous failed/confirmed statuses will not be skipped.")
    print("-" * 65)

    results = []

    with httpx.Client(timeout=TIMEOUT) as client:

        for index, model in enumerate(models, 1):

            print(
                f"[{index}/{len(models)}] "
                f"{model['id']} ... ",
                end="",
                flush=True
            )

            result = probe_model(
                client,
                api_key,
                model
            )

            results.append(result)

            if result["status"] == "confirmed":
                features = []

                if result["content_received"]:
                    features.append("content")

                if result["reasoning_received"]:
                    features.append("reasoning")

                print(
                    f"OK | HTTP {result['http_status']} "
                    f"| {', '.join(features)} "
                    f"| {result['duration_seconds']}s"
                )

            else:
                print(
                    f"FAILED | HTTP {result['http_status']} "
                    f"| {result['duration_seconds']}s"
                )

                if result["error"]:
                    print(f"    Error: {result['error']}")

            # Avoid sending requests too rapidly.
            time.sleep(0.5)

    confirmed, failed = save_report(results)

    print()
    print("=" * 65)
    print("                 NVIDIA PROBE SUMMARY")
    print("=" * 65)

    print(f"Total models : {len(results)}")
    print(f"Confirmed    : {confirmed}")
    print(f"Failed       : {failed}")

    if results:
        percentage = confirmed * 100 / len(results)
        print(f"Success rate : {percentage:.1f}%")

    print("-" * 65)
    print(f"Report saved: {REPORT_FILE}")

    print()
    print("Failed models:")

    for item in results:
        if item["status"] == "failed":
            print(
                f"  - {item['model']} "
                f"(HTTP {item['http_status']})"
            )

    print("=" * 65)


if __name__ == "__main__":
    main()
