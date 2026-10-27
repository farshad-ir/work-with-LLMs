import os
import csv
import json
import time
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
ENV_PATH = ROOT / ".env"

RESULTS_CSV = ROOT / "nvidia_all_model_results.csv"
SUCCESS_TXT = ROOT / "nvidia_working_models.txt"
ALL_MODELS_TXT = ROOT / "nvidia_models_live.txt"

# Parse .env without printing secrets or requiring python-dotenv.
if ENV_PATH.exists():
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(name, value)

config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
provider = config.get("providers", {}).get("nvidia_nim", {})

base_url = provider.get(
    "base_url", "https://integrate.api.nvidia.com/v1"
).rstrip("/")

key_env = provider.get("api_key_env", "NVIDIA_NIM_API_KEY")
api_key = os.environ.get(key_env)

if not api_key:
    raise SystemExit(
        f"ERROR: API key was not found in .env or environment variable {key_env}."
    )

headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json",
}

# Fetch the live model catalog from OpenRouter.
print("Fetching live model list from OpenRouter...", flush=True)

try:
    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{base_url}/models", headers=headers)
        response.raise_for_status()
        catalog = response.json()
except Exception as exc:
    raise SystemExit(
        f"Could not fetch OpenRouter model list: {type(exc).__name__}: {exc}"
    )

models_data = catalog.get("data", [])
models = [
    item["id"]
    for item in models_data
    if isinstance(item, dict) and item.get("id")
]

if not models:
    raise SystemExit("OpenRouter returned no model IDs; stopping.")

ALL_MODELS_TXT.write_text(
    "\n".join(models) + "\n",
    encoding="utf-8",
)

print(f"Models found: {len(models)}")
print(f"Live catalog saved to: {ALL_MODELS_TXT.name}")
print("Each model will receive one short Chat Completions request.")
print("Press Ctrl+C to stop; completed results are saved after every model.")
print()

fields = ["model", "status", "result", "detail"]
completed = {}

if RESULTS_CSV.exists():
    with RESULTS_CSV.open("r", encoding="utf-8", newline="") as file:
        for row in csv.DictReader(file):
            if row.get("model"):
                completed[row["model"]] = row

# Keep previous results for models that are still in the live catalog.
results = {
    model: completed[model]
    for model in models
    if model in completed
}

def save_results():
    with RESULTS_CSV.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for model in models:
            if model in results:
                writer.writerow(results[model])

    successful = [
        model for model in models
        if model in results and results[model]["result"] == "PASS"
    ]
    SUCCESS_TXT.write_text(
        "\n".join(successful) + ("\n" if successful else ""),
        encoding="utf-8",
    )

with httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0)) as client:
    try:
        for index, model in enumerate(models, 1):
            if model in results:
                print(
                    f"[{index}/{len(models)}] SKIP (already tested): {model}",
                    flush=True,
                )
                continue

            print(
                f"[{index}/{len(models)}] Testing {model}",
                flush=True,
            )

            payload = {
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": "Reply with exactly: OK",
                    }
                ],
                "max_tokens": 8,
                "stream": False,
            }

            try:
                response = client.post(
                    f"{base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )

                status = response.status_code
                detail = ""
                result = "FAIL"

                try:
                    data = response.json()
                except ValueError:
                    data = {}

                if 200 <= status < 300:
                    choices = data.get("choices", [])
                    if choices:
                        result = "PASS"
                        message = choices[0].get("message", {})
                        content = message.get("content", "")
                        detail = str(content or "Successful response")[:200]
                    else:
                        detail = "HTTP success but no choices in response"
                else:
                    error_data = data.get("error", {})
                    if isinstance(error_data, dict):
                        detail = (
                            error_data.get("message")
                            or error_data.get("code")
                            or response.text
                        )
                    else:
                        detail = str(error_data or response.text)

                    detail = " ".join(str(detail).split())[:250]

            except httpx.HTTPError as exc:
                status = 0
                result = "ERROR"
                detail = f"{type(exc).__name__}: {exc}"[:250]

            row = {
                "model": model,
                "status": status,
                "result": result,
                "detail": detail,
            }
            results[model] = row
            save_results()

            print(
                f"  HTTP {status} | {result} | {detail}",
                flush=True,
            )

            # Small delay to reduce the chance of triggering rate limits.
            time.sleep(0.25)

    except KeyboardInterrupt:
        print("\nStopped by user. Saving completed results...", flush=True)
        save_results()

save_results()

successful_count = sum(
    1 for row in results.values() if row["result"] == "PASS"
)

print("\n========== SUMMARY ==========")
print(f"Models in live catalog: {len(models)}")
print(f"Models tested or previously recorded: {len(results)}")
print(f"Successful models: {successful_count}")
print(f"All results: {RESULTS_CSV.name}")
print(f"Working models: {SUCCESS_TXT.name}")
print(f"Live model list: {ALL_MODELS_TXT.name}")
