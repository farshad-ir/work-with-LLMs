from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

CATALOG_PATH = DATA_DIR / "large_catalog.json"
ROTATION_STATE_PATH = DATA_DIR / "rotation_state.json"

PROVIDER_ORDER = [
    "openrouter",
    "nvidia",
    "token_router",
]

# مجموع کاراکترهای ورودی درخواست‌های موفق برای پایان دورهٔ آزمایش مدل.
# مقدار را می‌توان بعداً از تنظیمات پروژه خواند.
DEFAULT_TEST_INPUT_CHAR_LIMIT = 100_000


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


def _load_catalog() -> dict[str, Any]:
    catalog = _read_json(CATALOG_PATH, {"models": []})

    if not isinstance(catalog, dict):
        catalog = {"models": []}

    if not isinstance(catalog.get("models"), list):
        catalog["models"] = []

    return catalog


def _save_catalog(catalog: dict[str, Any]) -> None:
    _write_json(CATALOG_PATH, catalog)


def _load_state() -> dict[str, Any]:
    state = _read_json(
        ROTATION_STATE_PATH,
        {
            "next_provider_index": 0,
            "current_model_key": None,
            "finished": False,
            "test_input_char_limit": DEFAULT_TEST_INPUT_CHAR_LIMIT,
        },
    )

    if not isinstance(state, dict):
        state = {}

    state.setdefault("next_provider_index", 0)
    state.setdefault("current_model_key", None)
    state.setdefault("finished", False)
    state.setdefault("test_input_char_limit", DEFAULT_TEST_INPUT_CHAR_LIMIT)

    return state


def _save_state(state: dict[str, Any]) -> None:
    _write_json(ROTATION_STATE_PATH, state)


def _provider_key(provider: str) -> str:
    aliases = {
        "nvidia_nim": "nvidia",
        "nvidia-nim": "nvidia",
        "tokenrouter": "token_router",
        "token-router": "token_router",
    }

    normalized = provider.strip().lower()
    return aliases.get(normalized, normalized)


def _model_key(model: dict[str, Any]) -> str:
    existing_key = model.get("key")
    if existing_key:
        return str(existing_key)

    provider = _provider_key(str(model.get("provider", "")))
    model_id = str(model.get("id", ""))

    return f"{provider}:{model_id}"


def _initialize_model_fields(model: dict[str, Any]) -> None:
    # None یعنی هنوز دورهٔ آزمایش مدل تمام نشده و نتیجه‌ای ثبت نشده است.
    model.setdefault("lifetime_chars", None)
    model.setdefault("successful_requests", 0)
    model.setdefault("failed_requests", 0)
    model.setdefault("output_chars", 0)
    model.setdefault("test_status", "untested")
    model.setdefault("last_tested_at", None)
    model.setdefault("last_error_type", None)
    model.setdefault("last_error_message", None)
    model.setdefault("failure_at", None)


def _find_model(
    catalog: dict[str, Any],
    model_key: str,
) -> dict[str, Any] | None:
    for model in catalog["models"]:
        if _model_key(model) == model_key:
            return model

    return None

def _provider_has_untested_model(
    catalog: dict[str, Any],
    provider: str,
) -> bool:
    provider = _provider_key(provider)

    for model in catalog["models"]:
        _initialize_model_fields(model)

        if _provider_key(str(model.get("provider", ""))) != provider:
            continue

        if model.get("test_status") == "untested":
            return True

    return False



def select_next_model() -> dict[str, Any] | None:
    """
    مدل جاری را حفظ می‌کند تا دورهٔ آزمایش آن تمام شود.

    در نبود مدل جاری، ارائه‌دهندهٔ نوبت‌دار را انتخاب می‌کند و از ابتدای
    دفتر بزرگ به دنبال اولین مدل آزمایش‌نشدهٔ همان ارائه‌دهنده می‌گردد.

    اگر همهٔ مدل‌ها آزمایش شده باشند، None برمی‌گرداند.
    """
    catalog = _load_catalog()
    state = _load_state()

    models = catalog["models"]

    for model in models:
        _initialize_model_fields(model)

    current_key = state.get("current_model_key")

    if current_key:
        current_model = _find_model(catalog, str(current_key))

        if current_model is not None:
            if current_model.get("test_status") == "in_progress":
                return current_model

        # مدل جاری دیگر در دفتر نیست یا وضعیت آن معتبر نیست.
        state["current_model_key"] = None

    provider_index = int(state.get("next_provider_index", 0))
    provider_index %= len(PROVIDER_ORDER)

    # هر ارائه‌دهنده حداکثر یک بار در این جست‌وجو بررسی می‌شود.
    for offset in range(len(PROVIDER_ORDER)):
        index = (provider_index + offset) % len(PROVIDER_ORDER)
        provider = PROVIDER_ORDER[index]

        if not _provider_has_untested_model(catalog, provider):
            continue

        # ترتیب دفتر بزرگ حفظ می‌شود؛ هیچ مرتب‌سازی تازه‌ای انجام نمی‌شود.
        for model in models:
            if _provider_key(str(model.get("provider", ""))) != provider:
                continue

            if model.get("test_status") != "untested":
                continue

            model_key = _model_key(model)
            model["key"] = model_key
            model["test_status"] = "in_progress"
            model["last_tested_at"] = _now()

            state["current_model_key"] = model_key
            state["next_provider_index"] = (
                index + 1
            ) % len(PROVIDER_ORDER)
            state["finished"] = False

            _save_catalog(catalog)
            _save_state(state)

            return model     
    

    state["current_model_key"] = None
    state["finished"] = True

    _save_catalog(catalog)
    _save_state(state)

    return None


def record_request_result(
    model_key: str,
    input_chars: int,
    output_chars: int = 0,
    success: bool = False,
    ends_model_test: bool = False,
    error_type: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    """
    نتیجهٔ یک درخواست را برای مدل جاری ثبت می‌کند.

    موفقیت:
      - input_chars به lifetime_chars اضافه می‌شود.
      - output_chars و successful_requests افزایش می‌یابند.

    شکست:
      - failed_requests افزایش می‌یابد.
      - خطای موقت به‌تنهایی مدل را از چرخه خارج نمی‌کند.
      - شکست نهایی باید با ends_model_test=True مشخص شود.

    توجه:
      این تابع خودش نوع خطا را تشخیص نمی‌دهد؛ فراخواننده باید مشخص کند
      آیا شکست نهایی مدل است یا خطای موقت شبکه/درگاه.
    """
    catalog = _load_catalog()
    state = _load_state()
    # نتیجه متعلق به مدل همین درخواست است، نه لزوماً مدل جاری.
    
    current_key = state.get("current_model_key")
    result_key = str(model_key)

    model = _find_model(catalog, result_key)

    if model is None:
        raise RuntimeError(
            f"Result model '{result_key}' was not found in the catalog."
        )

    _initialize_model_fields(model)

    input_chars = max(0, int(input_chars))
    output_chars = max(0, int(output_chars))

    if success:
        previous_chars = model.get("lifetime_chars")

        if previous_chars is None:
            previous_chars = 0

        model["lifetime_chars"] = int(previous_chars) + input_chars
        model["output_chars"] += output_chars
        model["successful_requests"] += 1
        model["last_tested_at"] = _now()
        model["last_error_type"] = None
        model["last_error_message"] = None

        limit = int(
            state.get(
                "test_input_char_limit",
                DEFAULT_TEST_INPUT_CHAR_LIMIT,
            )
        )

        reached_limit = model["lifetime_chars"] >= limit

        if ends_model_test or reached_limit:
            model["test_status"] = "tested"

            if str(state.get("current_model_key")) == result_key:
                state["current_model_key"] = None
        


    else:
        model["failed_requests"] += 1
        model["last_tested_at"] = _now()
        model["last_error_type"] = error_type
        model["last_error_message"] = error_message
        
        if ends_model_test:
            model["test_status"] = "failed"
            model["failure_at"] = _now()

            if str(state.get("current_model_key")) == result_key:
                state["current_model_key"] = None
        

    _save_catalog(catalog)
    _save_state(state)

    return {
        "model_key": result_key,
        "success": bool(success),
        "lifetime_chars": model.get("lifetime_chars"),
        "successful_requests": model.get("successful_requests", 0),
        "failed_requests": model.get("failed_requests", 0),
        "output_chars": model.get("output_chars", 0),
        "test_status": model.get("test_status"),
        "current_model_key": state.get("current_model_key"),
        "finished": state.get("finished", False),
    }


def get_rotation_status() -> dict[str, Any]:
    catalog = _load_catalog()
    state = _load_state()

    models = catalog["models"]

    total = len(models)
    tested = 0
    failed = 0
    untested = 0
    in_progress = 0

    for model in models:
        _initialize_model_fields(model)

        status = model.get("test_status")
        
        if status == "failed":
            failed += 1
        elif status == "tested" or model.get("lifetime_chars") is not None:
            tested += 1
        elif status == "in_progress":
            in_progress += 1
        else:
            untested += 1


    return {
        "total": total,
        "tested": tested,
        "failed": failed,
        "untested": untested,
        "in_progress": in_progress,
        "current_model_key": state.get("current_model_key"),
        "finished": bool(state.get("finished", False)),
        "test_input_char_limit": int(
            state.get(
                "test_input_char_limit",
                DEFAULT_TEST_INPUT_CHAR_LIMIT,
            )
        ),
    }


def set_test_input_char_limit(limit: int) -> dict[str, Any]:
    """
    تنظیم حد کاراکترهای ورودی برای هر مدل.
    فقط مقدار مثبت پذیرفته می‌شود.
    """
    limit = int(limit)

    if limit <= 0:
        raise ValueError("The character limit must be greater than zero.")

    state = _load_state()
    state["test_input_char_limit"] = limit
    _save_state(state)

    return get_rotation_status()

