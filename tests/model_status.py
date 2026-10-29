import json
from pathlib import Path

catalog_path = Path("data/large_catalog.json")

with catalog_path.open(encoding="utf-8") as f:
    models = json.load(f).get("models", [])

def status(model):
    current = model.get("test_status", "untested")

    if current == "failed":
        return "failed"

    if current == "tested" or model.get("lifetime_chars") is not None:
        return "tested"

    if current == "in_progress":
        return "in_progress"

    return "untested"

remaining = sum(status(model) == "untested" for model in models)
successful = [model for model in models if status(model) == "tested"]

print(f"تعداد مدل‌های باقی‌مانده: {remaining}")
print("\nمدل‌های موفق:")

for model in successful:
    name = model.get("id", "?")
    provider = model.get("provider", "?")
    print(f"{name} | {provider}")
