import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "data" / "large_catalog.json"

with CATALOG_PATH.open(encoding="utf-8") as f:
    catalog = json.load(f)

confirmed = []

def scan(obj):
    if isinstance(obj, dict):

        if obj.get("test_status") == "confirmed":
            provider = (
                obj.get("provider")
                or obj.get("interface")
                or "نامشخص"
            )

            model = (
                obj.get("model_key")
                or obj.get("model")
                or obj.get("model_name")
                or obj.get("name")
                or obj.get("id")
                or "نامشخص"
            )

            confirmed.append({
                "provider": provider,
                "model": model,
                "successful_requests": obj.get("successful_requests", 0),
                "failed_requests": obj.get("failed_requests", 0),
                "lifetime_chars": obj.get("lifetime_chars", 0),
            })

        for value in obj.values():
            scan(value)

    elif isinstance(obj, list):
        for item in obj:
            scan(item)

scan(catalog)

confirmed.sort(
    key=lambda x: int(x["successful_requests"] or 0),
    reverse=True
)

print(f"\nتعداد کل مدل‌های Confirmed: {len(confirmed)}\n")

for index, item in enumerate(confirmed, 1):
    print(f"{index}. رابط: {item['provider']}")
    print(f"   مدل: {item['model']}")
    print(f"   درخواست موفق: {item['successful_requests']}")
    print(f"   درخواست ناموفق: {item['failed_requests']}")
    print(f"   کاراکتر طول عمر: {item['lifetime_chars']}")
    print("-" * 60)
