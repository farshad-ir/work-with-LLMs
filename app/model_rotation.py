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

ROTATION_GROUP_ORDER = [
    "openrouter",
    "nvidia",
    "token_router",
    "confirmed_models",
]

DEFAULT_TEST_INPUT_CHAR_LIMIT = 100_000
CONFIRMED_MODEL_ENTRY_CHARS = 50_000
CONFIRMED_MODEL_CHAR_LIMIT = 500_000


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

    state.setdefault("next_rotation_group_index", 0)
    state.setdefault("confirmed_model_key", None)
    state.setdefault("confirmed_model_index", 0)
    state.setdefault("next_provider_index", 0)
    state.setdefault("current_model_key", None)
    state.setdefault("finished", False)
    state.setdefault(
        "test_input_char_limit",
        DEFAULT_TEST_INPUT_CHAR_LIMIT,
    )
    state.setdefault("round_number", 1)
    state.setdefault("round_total", 0)
    state.setdefault("round_completed", 0)

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
    model.setdefault("lifetime_chars", None)
    model.setdefault("successful_requests", 0)
    model.setdefault("failed_requests", 0)
    model.setdefault("output_chars", 0)
    model.setdefault("test_status", "untested")
    model.setdefault("last_tested_at", None)
    model.setdefault("last_error_type", None)
    model.setdefault("last_error_message", None)
    model.setdefault("failure_at", None)
    model.setdefault("confirmed", False)


def _find_model(
    catalog: dict[str, Any],
    model_key: str,
) -> dict[str, Any] | None:
    for model in catalog["models"]:
        if _model_key(model) == model_key:
            return model

    return None


def _confirmed_models(
    catalog: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return models with persistent confirmed-group membership."""
    confirmed = []

    for model in catalog["models"]:
        _initialize_model_fields(model)

        # Membership is permanent once earned.
        # lifetime_chars may be reset for each confirmed turn.
        if model.get("confirmed") is True:
            confirmed.append(model)

    return confirmed


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


def _select_confirmed_model(
    catalog: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any] | None:
    """
    Start the next confirmed-model turn.

    confirmed_model_key is the persistent cursor. If it no longer
    exists in the confirmed group, selection starts with the first
    confirmed model.
    """
    confirmed = _confirmed_models(catalog)

    if not confirmed:
        state["confirmed_model_key"] = None
        state["confirmed_model_index"] = 0
        _save_catalog(catalog)
        _save_state(state)
        return None

    previous_key = state.get("confirmed_model_key")
    start_index = 0

    if previous_key:
        matching_index = next(
            (
                index
                for index, model in enumerate(confirmed)
                if _model_key(model) == str(previous_key)
            ),
            None,
        )

        if matching_index is not None:
            start_index = (matching_index + 1) % len(confirmed)

    model = confirmed[start_index]
    model_key = _model_key(model)

    model["key"] = model_key
    model["lifetime_chars"] = 0
    model["test_status"] = "confirmed_in_progress"
    model["last_tested_at"] = _now()
    model["last_error_type"] = None
    model["last_error_message"] = None

    state["current_model_key"] = model_key
    state["confirmed_model_key"] = model_key
    state["confirmed_model_index"] = start_index
    state["finished"] = False

    _save_catalog(catalog)
    _save_state(state)

    return model


def _advance_rotation_group(state: dict[str, Any]) -> None:
    group_count = len(ROTATION_GROUP_ORDER)

    if group_count == 0:
        state["next_rotation_group_index"] = 0
        return

    current_index = int(
        state.get("next_rotation_group_index", 0)
    )

    state["next_rotation_group_index"] = (
        current_index + 1
    ) % group_count


def _select_ordinary_model(
    catalog: dict[str, Any],
    state: dict[str, Any],
    provider: str,
    provider_index: int,
) -> dict[str, Any] | None:
    """Select the first untested model for a provider."""
    for model in catalog["models"]:
        _initialize_model_fields(model)

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
            provider_index + 1
        ) % len(PROVIDER_ORDER)
        state["finished"] = False

        _advance_rotation_group(state)

        _save_catalog(catalog)
        _save_state(state)

        return model

    return None

def refresh_confirmed_models(catalog):
    """Refresh confirmation without touching models in ordinary testing."""
    for model in catalog["models"]:
        if model.get("test_status") == "in_progress":
            continue

        model["confirmed"] = (
            (model.get("lifetime_chars") or 0)
            >= CONFIRMED_MODEL_ENTRY_CHARS
        )

def select_next_model() -> dict[str, Any] | None:
    """
    Select the next model according to:
    openrouter -> nvidia -> token_router -> confirmed_models.

    An in-progress request survives process restarts because its
    current_model_key is persisted. Empty groups are skipped safely.
    """
    catalog = _load_catalog()
    refresh_confirmed_models(catalog)
    state = _load_state()
    models = catalog["models"]

    if not models:
        state["current_model_key"] = None
        state["finished"] = True
        _save_state(state)
        return None

    for model in models:
        _initialize_model_fields(model)

    if int(state.get("round_total", 0)) <= 0:
        state["round_total"] = len(models)
        state["round_completed"] = sum(
            1
            for model in models
            if model.get("test_status") in {"tested", "failed"}
        )
        _save_state(state)

    current_key = state.get("current_model_key")

    if current_key:
        current_model = _find_model(catalog, str(current_key))

        if current_model is not None and current_model.get(
            "test_status"
        ) in {"in_progress", "confirmed_in_progress"}:
            return current_model

        state["current_model_key"] = None

    # Preserve the ordinary failed-model retry behavior.
    #
    # Retry failed ordinary models only after all ordinary providers
    # have no untested models. Confirmed models are not failed out of
    # their group by ordinary retry handling.
    provider_index = int(state.get("next_provider_index", 0))
    provider_index %= len(PROVIDER_ORDER)

    group_count = len(ROTATION_GROUP_ORDER)
    start_group = int(
        state.get("next_rotation_group_index", 0)
    ) % group_count

    # Examine at most one complete rotation. Empty groups are skipped.
    for offset in range(group_count):
        group_index = (start_group + offset) % group_count
        group = ROTATION_GROUP_ORDER[group_index]

        if group == "confirmed_models":
            confirmed = _confirmed_models(catalog)

            if not confirmed:
                continue

            # The cursor points to the next group after selection.
            model = _select_confirmed_model(catalog, state)

            if model is not None:
                _advance_rotation_group(state)
                _save_state(state)
                return model

            continue

        provider = group

        if not _provider_has_untested_model(catalog, provider):
            continue

        index = PROVIDER_ORDER.index(provider)
        model = _select_ordinary_model(
            catalog,
            state,
            provider,
            index,
        )

        if model is not None:
            return model

    # No group has an untested/available model.
    # Retry only ordinary failures, preserving prior behavior.
    failed_models = [
        model
        for model in models
        if (
            model.get("test_status") == "failed"
            and model.get("confirmed") is not True
        )
    ]

    if failed_models:
        for model in failed_models:
            model["test_status"] = "untested"
            model["failure_at"] = None

        state["round_number"] = int(
            state.get("round_number", 1)
        ) + 1
        state["round_total"] = len(failed_models)
        state["round_completed"] = 0
        state["current_model_key"] = None
        state["finished"] = False

        # Begin the retry round at the first ordinary provider.
        state["next_rotation_group_index"] = 0
        state["next_provider_index"] = 0

        _save_catalog(catalog)
        _save_state(state)

        return select_next_model()

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
    Record one request result.

    Ordinary models:
      - Accumulate successful input characters.
      - Become confirmed at 50,000 successful input characters.
      - Finish ordinary testing at the configured limit or when the
        caller reports a terminal result.

    Confirmed models:
      - lifetime_chars measures the current confirmed turn only.
      - Finish the turn at 500,000 successful input characters or
        a terminal error.
      - Remain confirmed after the turn ends.
    """
    catalog = _load_catalog()
    state = _load_state()

    result_key = str(model_key)
    model = _find_model(catalog, result_key)

    if model is None:
        raise RuntimeError(
            f"Result model '{result_key}' was not found in the catalog."
        )

    _initialize_model_fields(model)

    previous_status = model.get("test_status")
    was_confirmed_turn = previous_status == "confirmed_in_progress"

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

        if not was_confirmed_turn:
            if ends_model_test or (
                model["lifetime_chars"]
                >= int(state.get("test_input_char_limit", DEFAULT_TEST_INPUT_CHAR_LIMIT))
            ):
                model["confirmed"] = (
                    model["lifetime_chars"] >= CONFIRMED_MODEL_ENTRY_CHARS
                )

            limit = int(
                state.get(
                    "test_input_char_limit",
                    DEFAULT_TEST_INPUT_CHAR_LIMIT,
                )
            )

            reached_limit = model["lifetime_chars"] >= limit

            if ends_model_test or reached_limit:
                model["test_status"] = (
                    "confirmed_ready"
                    if model.get("confirmed") is True
                    else "tested"
                )

                if state.get("current_model_key") == result_key:
                    state["current_model_key"] = None

        else:
            # The counter is scoped to this confirmed turn.
            reached_confirmed_limit = (
                model["lifetime_chars"] >= CONFIRMED_MODEL_CHAR_LIMIT
            )

            if ends_model_test or reached_confirmed_limit:
                model["test_status"] = "confirmed_ready"

                # Keep confirmed membership and the persistent cursor.
                if state.get("current_model_key") == result_key:
                    state["current_model_key"] = None

    else:
        model["failed_requests"] += 1
        model["last_tested_at"] = _now()
        model["last_error_type"] = error_type
        model["last_error_message"] = error_message

        if ends_model_test:
            if was_confirmed_turn or model.get("confirmed") is True:
                # A terminal error ends this confirmed turn only.
                model["test_status"] = "confirmed_ready"
            else:
                model["test_status"] = "failed"
                model["failure_at"] = _now()

            if state.get("current_model_key") == result_key:
                state["current_model_key"] = None

        # A temporary failure leaves the model in its current state.
        # It does not add characters or end the confirmed turn.

    terminal_statuses = {"tested", "failed"}

    if (
        previous_status not in terminal_statuses
        and model.get("test_status") in terminal_statuses
    ):
        state["round_completed"] = int(
            state.get("round_completed", 0)
        ) + 1

    # Confirmed turns do not contribute to ordinary round completion.
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
        "confirmed": model.get("confirmed", False),
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
    confirmed_count = 0
    confirmed_in_progress = 0

    for model in models:
        _initialize_model_fields(model)
        status = model.get("test_status")

        if model.get("confirmed") is True:
            confirmed_count += 1

        if status == "failed":
            failed += 1
        elif status == "in_progress":
            in_progress += 1
        elif status == "confirmed_in_progress":
            confirmed_in_progress += 1
        elif status in {"tested", "confirmed_ready"}:
            tested += 1
        elif status == "untested":
            untested += 1
        else:
            untested += 1

    round_number = int(state.get("round_number", 1))
    round_total = int(state.get("round_total", total))
    round_completed = int(state.get("round_completed", 0))

    group_count = len(ROTATION_GROUP_ORDER)
    next_group_index = (
        int(state.get("next_rotation_group_index", 0)) % group_count
        if group_count
        else 0
    )

    return {
        "round_number": round_number,
        "round_total": round_total,
        "round_completed": round_completed,
        "total": total,
        "tested": tested,
        "failed": failed,
        "untested": untested,
        "in_progress": in_progress,
        "confirmed_count": confirmed_count,
        "confirmed_in_progress": confirmed_in_progress,
        "current_model_key": state.get("current_model_key"),
        "confirmed_model_key": state.get("confirmed_model_key"),
        "next_rotation_group_index": next_group_index,
        "next_rotation_group": (
            ROTATION_GROUP_ORDER[next_group_index]
            if group_count
            else None
        ),
        "finished": bool(state.get("finished", False)),
        "test_input_char_limit": int(
            state.get(
                "test_input_char_limit",
                DEFAULT_TEST_INPUT_CHAR_LIMIT,
            )
        ),
        "confirmed_entry_char_limit": CONFIRMED_MODEL_ENTRY_CHARS,
        "confirmed_turn_char_limit": CONFIRMED_MODEL_CHAR_LIMIT,
    }


def set_test_input_char_limit(limit: int) -> dict[str, Any]:
    """Set the ordinary per-model successful-input character limit."""
    limit = int(limit)

    if limit <= 0:
        raise ValueError(
            "The character limit must be greater than zero."
        )

    state = _load_state()
    state["test_input_char_limit"] = limit
    _save_state(state)

    return get_rotation_status()

