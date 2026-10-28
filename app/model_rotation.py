import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.thinker_room import LARGE_CATALOG_PATH, DATA_DIR


ROTATION_STATE_PATH = DATA_DIR / "rotation_state.json"

# ترتیب ثابت گردش ارائه‌دهندگان
PROVIDER_ORDER = [
    "openrouter",
    "nvidia",
    "token_router",
]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now_utc().isoformat()


def save_json(path: Path, data: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    os.replace(temporary_path, path)


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must contain a JSON object.")

    return data


def load_catalog() -> dict[str, Any]:
    return load_json(
        LARGE_CATALOG_PATH,
        {
            "updated_at": None,
            "model_count": 0,
            "models": [],
        },
    )


def save_catalog(catalog: dict[str, Any]) -> None:
    catalog["updated_at"] = now_iso()
    save_json(LARGE_CATALOG_PATH, catalog)


def load_state() -> dict[str, Any]:
    return load_json(
        ROTATION_STATE_PATH,
        {
            "next_provider_index": 0,
            "current_model_key": None,
            "current_model_started_at": None,
            "completed_count": 0,
            "finished": False,
        },
    )


def get_model(
    catalog: dict[str, Any],
    model_key: str,
) -> dict[str, Any] | None:
    for model in catalog.get("models", []):
        if model.get("key") == model_key:
            return model

    return None


def select_next_model() -> dict[str, Any] | None:
    """
    اگر مدلی در حال آزمایش باشد، همان مدل را برمی‌گرداند.

    در غیر این صورت، اولین مدل آزمایش‌نشده را از ارائه‌دهنده
    نوبت‌دار پیدا می‌کند. ترتیب دفتر بزرگ تغییر نمی‌کند.
    """

    catalog = load_catalog()
    state = load_state()

    if state.get("finished"):
        return None

    models = catalog.get("models", [])

    # اگر مدلی در حال آزمایش است، آن را دوباره انتخاب نکن.
    current_key = state.get("current_model_key")

    if current_key:
        current_model = get_model(catalog, current_key)

        if current_model is None:
            raise RuntimeError(
                "مدل جاری دیگر در دفتر بزرگ وجود ندارد. "
                "وضعیت گردش را بررسی کن."
            )

        return {
            **current_model,
            "started_at": state["current_model_started_at"],
        }

    if not PROVIDER_ORDER:
        return None

    start_index = (
        state.get("next_provider_index", 0)
        % len(PROVIDER_ORDER)
    )

    # حداکثر یک دور کامل بین ارائه‌دهندگان
    for offset in range(len(PROVIDER_ORDER)):
        provider_index = (
            start_index + offset
        ) % len(PROVIDER_ORDER)

        provider_name = PROVIDER_ORDER[provider_index]

        # همیشه از ابتدای دفتر بزرگ جست‌وجو می‌کنیم.
        for model in models:
            if model.get("provider") != provider_name:
                continue

            # None یعنی آزمایش‌نشده؛ صفر یعنی آزمایش‌شده.
            if model.get("lifetime_seconds") is not None:
                continue

            started_at = now_iso()

            state["current_model_key"] = model["key"]
            state["current_model_started_at"] = started_at

            state["next_provider_index"] = (
                provider_index + 1
            ) % len(PROVIDER_ORDER)

            save_json(ROTATION_STATE_PATH, state)

            return {
                **model,
                "started_at": started_at,
            }

    # هیچ مدل آزمایش‌نشده‌ای باقی نمانده است.
    state["current_model_key"] = None
    state["current_model_started_at"] = None
    state["finished"] = True

    save_json(ROTATION_STATE_PATH, state)

    return None


def finish_current_model() -> dict[str, Any]:
    """
    پایان آزمایش مدل جاری و ثبت مدت دوام آن در دفتر بزرگ.

    زمان شروع هنگام انتخاب مدل ثبت می‌شود.
    زمان پایان هنگام اعلام پایان آزمایش ثبت می‌شود.
    """

    catalog = load_catalog()
    state = load_state()

    model_key = state.get("current_model_key")
    started_at_text = state.get("current_model_started_at")

    if not model_key or not started_at_text:
        raise RuntimeError("هیچ مدل جاری برای پایان آزمایش وجود ندارد.")

    model = get_model(catalog, model_key)

    if model is None:
        raise RuntimeError(
            f"مدل جاری در دفتر بزرگ پیدا نشد: {model_key}"
        )

    if model.get("lifetime_seconds") is not None:
        raise RuntimeError(
            f"طول عمر این مدل قبلاً ثبت شده است: {model_key}"
        )

    started_at = datetime.fromisoformat(started_at_text)

    if started_at.tzinfo is None:
        raise RuntimeError("زمان شروع فاقد اطلاعات منطقه زمانی است.")

    finished_at = now_utc()

    lifetime_seconds = max(
        0.0,
        (finished_at - started_at).total_seconds(),
    )

    # فقط همان ستون در دفتر بزرگ به‌روز می‌شود.
    model["lifetime_seconds"] = round(lifetime_seconds, 3)
    model["last_tested_at"] = finished_at.isoformat()
    model["test_count"] = model.get("test_count", 0) + 1

    state["completed_count"] = (
        state.get("completed_count", 0) + 1
    )

    state["current_model_key"] = None
    state["current_model_started_at"] = None

    save_catalog(catalog)
    save_json(ROTATION_STATE_PATH, state)

    return {
        "key": model_key,
        "provider": model["provider"],
        "id": model["id"],
        "lifetime_seconds": model["lifetime_seconds"],
        "completed_count": state["completed_count"],
        "model_count": catalog.get("model_count", len(catalog["models"])),
    }


def get_rotation_status() -> dict[str, Any]:
    catalog = load_catalog()
    state = load_state()

    models = catalog.get("models", [])

    tested_count = sum(
        1
        for model in models
        if model.get("lifetime_seconds") is not None
    )

    untested_count = len(models) - tested_count

    return {
        "total": len(models),
        "tested": tested_count,
        "untested": untested_count,
        "current_model_key": state.get("current_model_key"),
        "current_model_started_at": state.get(
            "current_model_started_at"
        ),
        "finished": state.get("finished", False),
    }
