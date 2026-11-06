import asyncio
import sys
from pathlib import Path

import httpx

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from app.config import PROJECT_DIR, load_config, save_config, get_env_value
from app.thinker_room import rebuild_large_catalog

from app.ultra_models import (
    ULTRA_TRANSPORT_PROVIDER,
    get_ultra_models,
    is_ultra_model,
)

CONFIG_PATH = PROJECT_DIR / "config.json"
CATALOG_PATH = PROJECT_DIR / "data" / "large_catalog.json"


async def main():
    config = load_config()

    # پاک کردن مدل‌های قبلی، حفظ اسکلت و نام Providerها
    for provider_name, provider in config["providers"].items():
        provider["models"] = []
        provider["enabled"] = False


    save_config(config)

    # پاک کردن دفتر بزرگ قبلی؛ تاریخچه مدل‌ها هم از نو ساخته می‌شود
    CATALOG_PATH.unlink(missing_ok=True)

    async with httpx.AsyncClient(timeout=30.0) as client:
        for provider_name, provider in config["providers"].items():
            base_url = provider.get("base_url", "").rstrip("/")
            key_name = provider.get("api_key_env", "")
            api_key = get_env_value(key_name) if key_name else ""

            print(f"\n[{provider_name}]")

            if not base_url:
                print("SKIP: base_url is empty")
                continue

            if not api_key:
                print(f"SKIP: API key missing ({key_name})")
                continue

            try:
                response = await client.get(
                    f"{base_url}/models",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                    },
                )
                response.raise_for_status()

                payload = response.json()
                items = payload.get("data", [])

                if not isinstance(items, list):
                    raise ValueError("Unexpected model-list format")

                models = []

                for item in items:
                    if not isinstance(item, dict):
                        continue

                    model_id = item.get("id")

                    if not isinstance(model_id, str) or not model_id.strip():
                        continue

                    # مدل‌های Ultra در فهرست عادی NVIDIA ثبت نمی‌شوند.
                    if (
                        provider_name.strip().lower().replace("-", "_")
                        in {ULTRA_TRANSPORT_PROVIDER, "nvidia_nim"}
                        and is_ultra_model(model_id)
                    ):
                        continue

                    models.append({
                        "id": model_id,
                        "name": item.get("name") or model_id,
                    })

                provider["models"] = models


                is_ultra_provider = (
                    provider_name.strip().lower().replace("-", "_")
                    in {ULTRA_TRANSPORT_PROVIDER, "nvidia_nim"}
                )

                provider["enabled"] = bool(models) or (
                    is_ultra_provider and bool(get_ultra_models())
                )


                print(f"OK: {len(models)} models")

            except Exception as exc:
                provider["models"] = []
                provider["enabled"] = False
                print(f"ERROR: {type(exc).__name__}: {exc}")

            # ذخیره پس از هر Provider
            save_config(config)

    catalog = rebuild_large_catalog(config)

    print("\nRebuild completed")
    print(f"Providers: {len(config['providers'])}")
    print(f"Catalog models: {catalog['model_count']}")
    print(f"Catalog file: {CATALOG_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
