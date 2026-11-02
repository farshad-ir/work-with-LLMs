import json
import shutil
from pathlib import Path
from datetime import datetime

CATALOG = Path("data/large_catalog.json")

if not CATALOG.exists():
    print("Catalog file not found:", CATALOG)
    raise SystemExit(1)

provider = input("Provider name: ").strip().lower()

print("\nAvailable statuses:")
print("1. untested")
print("2. failed")
print("3. confirmed")

choices = {
    "1": "untested",
    "2": "failed",
    "3": "confirmed",
}

choice = input("\nSelect status (1/2/3): ").strip()

if choice not in choices:
    print("Invalid status.")
    raise SystemExit(1)

new_status = choices[choice]

with CATALOG.open(encoding="utf-8") as f:
    data = json.load(f)

models = [
    m for m in data["models"]
    if m.get("provider", "").lower() == provider
]

if not models:
    print(f"No models found for provider: {provider}")
    raise SystemExit(1)

print(f"\nProvider: {provider}")
print(f"Models found: {len(models)}")
print(f"New status: {new_status}")

confirm = input("Apply changes? (yes/no): ").strip().lower()

if confirm != "yes":
    print("Cancelled. No changes made.")
    raise SystemExit(0)

for model in models:
    model["test_status"] = new_status

with CATALOG.open("w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"\nUpdated {len(models)} models.")
print(f"New status: {new_status}")
