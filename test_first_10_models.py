import json
import urllib.request
import urllib.error
from pathlib import Path

models = [
    line.strip()
    for line in Path("working_models.txt").read_text(encoding="utf-8").splitlines()
    if line.strip() and not line.strip().startswith("#")
][:10]

url = "http://127.0.0.1:8088/v1/responses"
results = []

for index, model in enumerate(models, 1):
    print(f"\n[{index}/10] Testing: {model}", flush=True)

    payload = json.dumps({
        "model": model,
        "input": "Reply with exactly: GATEWAY_OK",
        "stream": False
    }).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            status = response.status
            raw = response.read().decode("utf-8", errors="replace")

    except urllib.error.HTTPError as error:
        status = error.code
        raw = error.read().decode("utf-8", errors="replace")

    except Exception as error:
        status = 0
        raw = str(error)

    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        data = {}

    if status == 200 and isinstance(data, dict) and not data.get("success") is False:
        text = data.get("output_text", "")
        if not text:
            for item in data.get("output", []):
                for part in item.get("content", []):
                    if part.get("type") == "output_text":
                        text += part.get("text", "")
        result = "PASS"
        detail = f"Response: {text[:200]}" if text else "HTTP 200; response received"
    else:
        result = "FAIL"
        if isinstance(data, dict):
            detail = str(data.get("error") or data.get("detail") or data.get("message") or raw)
        else:
            detail = raw
        detail = " ".join(detail.split())[:250]

    print(f"  Status: {status} | {result}", flush=True)
    print(f"  {detail}", flush=True)
    results.append({
        "model": model,
        "status": status,
        "result": result,
        "detail": detail
    })

Path("first_10_model_results.json").write_text(
    json.dumps(results, indent=2, ensure_ascii=False),
    encoding="utf-8"
)

passed = sum(item["result"] == "PASS" for item in results)
print(f"\nFinished: {passed}/10 models passed.")
print("Full results saved to first_10_model_results.json")
