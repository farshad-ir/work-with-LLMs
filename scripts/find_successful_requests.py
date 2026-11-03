import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "data" / "large_catalog.json"

with CATALOG_PATH.open(encoding="utf-8") as f:
    catalog = json.load(f)

limit_text = input(
    "حد بالای successful_requests (خالی = بیشترین مقدار): "
).strip()

limit = int(limit_text) if limit_text else None

matches = []

def scan(obj):
    if isinstance(obj, dict):
        if "successful_requests" in obj:
            try:
                count = int(obj["successful_requests"] or 0)
            except (ValueError, TypeError):
                count = -1

            if count >= 0 and (limit is None or count < limit):
                provider = obj.get(
                    "provider",
                    obj.get("interface", "نامشخص")
                )

                model = (
                    obj.get("model_key")
                    or obj.get("model")
                    or obj.get("model_name")
                    or obj.get("name")
                    or obj.get("id")
                    or "نامشخص"
                )

                matches.append((count, str(provider), str(model)))

        for value in obj.values():
            scan(value)

    elif isinstance(obj, list):
        for item in obj:
            scan(item)

scan(catalog)

if not matches:
    print("مدلی با این شرط پیدا نشد.")
else:
    count, provider, model = max(matches, key=lambda x: x[0])

    print("\n--- نتیجه ---")
    print(f"رابط: {provider}")
    print(f"مدل: {model}")
    print(f"successful_requests: {count}")
