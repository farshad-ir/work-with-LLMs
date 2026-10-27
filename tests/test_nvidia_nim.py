import os
import csv
from pathlib import Path
from datetime import datetime

import httpx

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

# Load environment variables from the project .env file.
if ENV_PATH.exists():
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            os.environ.setdefault(
                name.strip(),
                value.strip().strip("\"'")
            )

API_KEY = os.getenv("NVIDIA_NIM_API_KEY", "").strip()
BASE_URL = "https://integrate.api.nvidia.com/v1"
TIMEOUT = httpx.Timeout(600.0, connect=30.0)

if not API_KEY:
    raise SystemExit("ERROR: NVIDIA_NIM_API_KEY not found in .env")

try:
    count = int(input("How many models should be tested? "))
    if count < 1:
        raise ValueError
except ValueError:
    raise SystemExit("Please enter a positive integer.")

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

# Fetch the model catalog.
print("\nFetching NVIDIA model catalog...")

try:
    with httpx.Client(timeout=TIMEOUT) as client:
        response = client.get(
            f"{BASE_URL}/models",
            headers=headers,
        )

    print("Catalog HTTP status:", response.status_code)

    if not response.is_success:
        print("Catalog request failed:")
        print(response.text[:1000])
        raise SystemExit(
            "Cannot retrieve the model list. "
            "No model tests were started."
        )

    catalog = response.json()
    models = catalog.get("data", [])

    if not models:
        raise SystemExit("The API returned an empty model list.")

    selected = models[:count]
    print(f"Models returned: {len(models)}")
    print(f"Models selected for testing: {len(selected)}")

except httpx.HTTPError as exc:
    raise SystemExit(f"Catalog network error: {type(exc).__name__}: {exc}")

# Test each selected model.
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
csv_path = ROOT / f"nvidia_model_results_{timestamp}.csv"
txt_path = ROOT / f"nvidia_model_results_{timestamp}.txt"

results = []

with httpx.Client(timeout=TIMEOUT) as client:
    for index, item in enumerate(selected, start=1):
        model_id = item.get("id", "")

        if not model_id:
            continue

        print(f"\n[{index}/{len(selected)}] Testing: {model_id}")

        payload = {
            "model": model_id,
            "messages": [
                {
                    "role": "user",
                    "content": "Reply with exactly: OK",
                }
            ],
            "max_tokens": 16,
            "stream": False,
        }

        started = datetime.now()

        try:
            response = client.post(
                f"{BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
            )

            elapsed = (datetime.now() - started).total_seconds()

            if response.is_success:
                data = response.json()
                reply = (
                    data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )
                status = "PASS"
                error = ""
                print(f"PASS ({elapsed:.1f}s): {reply!r}")
            else:
                status = f"HTTP_{response.status_code}"
                error = response.text[:500]
                reply = ""
                print(f"FAIL ({elapsed:.1f}s): {status}")
                print(error[:250])

        except httpx.HTTPError as exc:
            elapsed = (datetime.now() - started).total_seconds()
            status = "NETWORK_ERROR"
            error = f"{type(exc).__name__}: {exc}"
            reply = ""
            print(f"FAIL ({elapsed:.1f}s): {error}")

        results.append({
            "model": model_id,
            "status": status,
            "elapsed_seconds": round(elapsed, 2),
            "reply": reply,
            "error": error,
        })

# Save results without overwriting earlier runs.
with csv_path.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(
        f,
        fieldnames=[
            "model",
            "status",
            "elapsed_seconds",
            "reply",
            "error",
        ],
    )
    writer.writeheader()
    writer.writerows(results)

with txt_path.open("w", encoding="utf-8") as f:
    for result in results:
        f.write(
            f"{result['model']}\t"
            f"{result['status']}\t"
            f"{result['elapsed_seconds']}s\n"
        )

passed = sum(r["status"] == "PASS" for r in results)

print("\n========== SUMMARY ==========")
print(f"Tested: {len(results)}")
print(f"Passed: {passed}")
print(f"Failed: {len(results) - passed}")
print(f"CSV: {csv_path}")
print(f"TXT: {txt_path}")

