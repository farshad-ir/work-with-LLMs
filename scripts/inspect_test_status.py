import json
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent
path = ROOT / "data" / "large_catalog.json"

with path.open(encoding="utf-8") as f:
    catalog = json.load(f)

statuses = Counter()
examples = {}

def scan(obj):
    if isinstance(obj, dict):
        if "test_status" in obj:
            status = str(obj.get("test_status"))
            statuses[status] += 1
            examples.setdefault(status, obj)

        for value in obj.values():
            scan(value)

    elif isinstance(obj, list):
        for item in obj:
            scan(item)

scan(catalog)

print("\n--- توزیع وضعیت مدل‌ها ---")
for status, count in statuses.most_common():
    print(f"{status}: {count}")

print("\n--- نمونه مدل از هر وضعیت ---")
for status, model in examples.items():
    print(f"\nStatus: {status}")
    print(f"Provider: {model.get('provider')}")
    print(f"Model: {model.get('model_key') or model.get('model') or model.get('name')}")
    print(f"Successful requests: {model.get('successful_requests')}")
    print(f"Lifetime chars: {model.get('lifetime_chars')}")
