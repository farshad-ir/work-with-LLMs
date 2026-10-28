from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
LARGE_CATALOG_PATH = DATA_DIR / "large_catalog.json"


# اطلاعاتی که با Refresh ارائه‌دهندگان باید حفظ شوند.
PRESERVED_MODEL_FIELDS = (
    "lifetime_chars",
    "successful_requests",
    "failed_requests",
    "output_chars",
    "test_status",
    "last_tested_at",
    "last_error_type",
    "last_error_message",
    "failure_at",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default

    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, data: Any) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    temporary_path = path.with_suffix(path.suffix + ".tmp")

    with temporary_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")

    temporary_path.replace(path)


def _normalize_provider(provider_name: str) -> str:
    name = provider_name.strip().lower()

    aliases = {
        "nvidia_nim": "nvidia",
        "nvidia-nim": "nvidia",
        "tokenrouter": "token_router",
        "token-router": "token_router",
    }

    return aliases.get(name, name)


def _model_id(model: dict[str, Any]) -> str:
    value = model.get("id")

    if value is None:
        value = model.get("model_id")

    return str(value or "").strip()


def _model_key(provider: str, model_id: str) -> str:
    return f"{_normalize_provider(provider)}:{model_id}"


def _load_previous_catalog() -> dict[str, Any]:
    catalog = _read_json(
        LARGE_CATALOG_PATH,
        {
            "model_count": 0,
            "updated_at": None,
            "models": [],
        },
    )

    if not isinstance(catalog, dict):
        return {
            "model_count": 0,
            "updated_at": None,
            "models": [],
        }

    models = catalog.get("models")

    if not isinstance(models, list):
        models = []

    return {
        **catalog,
        "models": models,
    }


def _index_previous_models(
    previous_models: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}

    for model in previous_models:
        if not isinstance(model, dict):
            continue

        key = model.get("key")

        if not key:
            provider = str(model.get("provider", ""))
            model_id = _model_id(model)

            if provider and model_id:
                key = _model_key(provider, model_id)

        if key:
            indexed[str(key)] = model

    return indexed


def _copy_test_history(
    new_model: dict[str, Any],
    previous_model: dict[str, Any] | None,
) -> None:
    """
    تاریخچهٔ آزمایش را از نسخهٔ قبلی مدل حفظ می‌کند.

    None برای lifetime_chars به معنی آزمایش‌نشده است.
    صفر یک مقدار معتبر است و نباید با None جایگزین شود.
    """
    if previous_model is None:
        new_model.setdefault("lifetime_chars", None)
        new_model.setdefault("successful_requests", 0)
        new_model.setdefault("failed_requests", 0)
        new_model.setdefault("output_chars", 0)
        new_model.setdefault("test_status", "untested")
        new_model.setdefault("last_tested_at", None)
        new_model.setdefault("last_error_type", None)
        new_model.setdefault("last_error_message", None)
        new_model.setdefault("failure_at", None)
        return

    for field in PRESERVED_MODEL_FIELDS:
        if field in previous_model:
            new_model[field] = previous_model[field]

    new_model.setdefault("lifetime_chars", None)
    new_model.setdefault("successful_requests", 0)
    new_model.setdefault("failed_requests", 0)
    new_model.setdefault("output_chars", 0)
    new_model.setdefault("test_status", "untested")
    new_model.setdefault("last_tested_at", None)
    new_model.setdefault("last_error_type", None)
    new_model.setdefault("last_error_message", None)
    new_model.setdefault("failure_at", None)


def rebuild_large_catalog(config: dict[str, Any]) -> dict[str, Any]:
    """
    دفتر بزرگ را از فهرست فعلی مدل‌های ارائه‌دهندگان می‌سازد.

    - ترتیب مدل‌ها مطابق ترتیب ارائه‌دهندگان و مدل‌های config حفظ می‌شود.
    - مدل‌هایی که دیگر در فهرست ارائه‌دهندگان نیستند حذف می‌شوند.
    - تاریخچهٔ آزمایش مدل‌های باقی‌مانده حفظ می‌شود.
    - کلید هر مدل به شکل provider:model_id است.
    """
    previous_catalog = _load_previous_catalog()
    previous_by_key = _index_previous_models(
        previous_catalog["models"]
    )

    providers = config.get("providers", {})

    if not isinstance(providers, dict):
        providers = {}

    catalog_models: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for provider_name, provider_config in providers.items():
        if not isinstance(provider_config, dict):
            continue

        provider = _normalize_provider(str(provider_name))
        provider_models = provider_config.get("models", [])

        if not isinstance(provider_models, list):
            continue

        for source_model in provider_models:
            if not isinstance(source_model, dict):
                continue

            model_id = _model_id(source_model)

            if not model_id:
                continue

            key = _model_key(provider, model_id)

            # از ثبت دوبارهٔ یک مدل جلوگیری می‌کنیم.
            if key in seen_keys:
                continue

            seen_keys.add(key)

            model = {
                "key": key,
                "provider": provider,
                "id": model_id,
                "name": str(
                    source_model.get("name") or model_id
                ),
            }

            previous_model = previous_by_key.get(key)
            _copy_test_history(model, previous_model)

            catalog_models.append(model)

    catalog = {
        "model_count": len(catalog_models),
        "updated_at": _now(),
        "models": catalog_models,
    }

    _write_json(LARGE_CATALOG_PATH, catalog)

    return catalog


def load_large_catalog() -> dict[str, Any]:
    """
    دفتر بزرگ ذخیره‌شده را می‌خواند.

    این تابع به‌تنهایی دفتر را بازسازی نمی‌کند؛
    بازسازی فقط هنگام Refresh ارائه‌دهنده انجام می‌شود.
    """
    catalog = _load_previous_catalog()

    models = catalog["models"]

    return {
        "model_count": len(models),
        "updated_at": catalog.get("updated_at"),
        "models": models,
    }

