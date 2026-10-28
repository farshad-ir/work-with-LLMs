import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data"
LARGE_CATALOG_PATH = DATA_DIR / "large_catalog.json"


def rebuild_large_catalog(config: dict[str, Any]) -> dict[str, Any]:
    """
    Rebuild the large catalog from the current model lists
    of all configured providers.
    Removed provider models are not retained.
    """
    previous_models = {}

    if LARGE_CATALOG_PATH.exists():
        try:
            with LARGE_CATALOG_PATH.open("r", encoding="utf-8") as file:
                previous_catalog = json.load(file)

            for item in previous_catalog.get("models", []):
                if isinstance(item, dict) and item.get("key"):
                    previous_models[item["key"]] = item

        except (json.JSONDecodeError, OSError):
            previous_models = {}


    catalog_models = []
    seen = set()

    for provider_name, provider in config["providers"].items():
        for model in provider.get("models", []):
            if not isinstance(model, dict):
                continue

            model_id = model.get("id")
            if not isinstance(model_id, str) or not model_id:
                continue

            key = f"{provider_name}:{model_id}"

            if key in seen:
                continue

            seen.add(key)

            previous = previous_models.get(key, {})

            catalog_models.append({
                "key": key,
                "provider": provider_name,
                "id": model_id,
                "name": model.get("name") or model_id,

                # None یعنی هنوز آزمایش نشده است.
                # صفر یعنی آزمایش شده و دوام آن صفر ثانیه بوده است.
                "lifetime_seconds": previous.get("lifetime_seconds"),

                # زمان پایان آخرین آزمایش
                "last_tested_at": previous.get("last_tested_at"),

                # تعداد آزمایش‌های ثبت‌شده
                "test_count": previous.get("test_count", 0),
            })




    catalog = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "model_count": len(catalog_models),
        "models": catalog_models,
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    temporary_path = LARGE_CATALOG_PATH.with_suffix(".tmp")

    temporary_path.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    os.replace(temporary_path, LARGE_CATALOG_PATH)

    return catalog


def load_large_catalog() -> dict[str, Any]:
    if not LARGE_CATALOG_PATH.exists():
        return {
            "updated_at": None,
            "model_count": 0,
            "models": [],
        }

    with LARGE_CATALOG_PATH.open("r", encoding="utf-8") as file:
        catalog = json.load(file)

    if not isinstance(catalog, dict):
        raise ValueError("Large catalog must be a JSON object.")

    return catalog
