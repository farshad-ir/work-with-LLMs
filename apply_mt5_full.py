import re

path = "C:/Users/Rezvan/work/codex/work-with-LLMs/app/model_rotation.py"
content = open(path, encoding="utf-8").read()

# 1. Add codex_in_progress and mt5_in_progress to _initialize_model_fields
old_init = """def _initialize_model_fields(model: dict[str, Any]) -> None:
    model.setdefault("lifetime_chars", None)
    model.setdefault("successful_requests", 0)"""

new_init = """def _initialize_model_fields(model: dict[str, Any]) -> None:
    model.setdefault("lifetime_chars", None)
    model.setdefault("successful_requests", 0)
    model.setdefault("codex_in_progress", False)
    model.setdefault("mt5_in_progress", False)"""

content = content.replace(old_init, new_init)

# 2. Add MT5 rotation state functions after record_request_result
mt5_funcs = '''
# ============================================================================
# MT5-specific rotation: independent parallel rotation using same catalog order
# ============================================================================

MT5_ROTATION_STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "rotation_state_MT5.json"


def _load_mt5_state() -> dict[str, Any]:
    state = _read_json(
        MT5_ROTATION_STATE_PATH,
        {
            "next_rotation_group_index": 0,
            "next_rotation_group": None,
            "current_model_key": None,
            "test_input_char_limit": DEFAULT_TEST_INPUT_CHAR_LIMIT,
            "round_number": 1,
            "round_total": 0,
            "round_completed": 0,
            "next_provider_index": 0,
        },
    )
    if not isinstance(state, dict):
        state = {}
    state.setdefault("next_rotation_group_index", 0)
    state.setdefault("next_rotation_group", None)
    state.setdefault("current_model_key", None)
    state.setdefault("test_input_char_limit", DEFAULT_TEST_INPUT_CHAR_LIMIT)
    state.setdefault("round_number", 1)
    state.setdefault("round_total", 0)
    state.setdefault("round_completed", 0)
    state.setdefault("next_provider_index", 0)
    return state


def _save_mt5_state(state: dict[str, Any]) -> None:
    _write_json(MT5_ROTATION_STATE_PATH, state)


def _mt5_confirmed_models(catalog):
    confirmed = []
    for model in catalog["models"]:
        if model.get("test_status") == "confirmed":
            confirmed.append(model)
    return confirmed


def _mt5_untested_models(catalog, provider):
    for model in catalog["models"]:
        if _provider_key(str(model.get("provider", ""))) == provider:
            if model.get("test_status") == "untested" and not model.get("mt5_in_progress", False):
                return model
    return None


def select_next_model_mt5() -> dict[str, Any] | None:
    """Select next model for MT5 rotation using same catalog order as Codex.

    Independent rotation: MT5 only checks mt5_in_progress, not codex_in_progress.
    If mt5_in_progress == True, pick next model from same provider.
    If confirmed model is busy (mt5_in_progress), pick next confirmed model.
    """
    catalog = _load_catalog()
    state = _load_mt5_state()
    models = catalog["models"]

    if not models:
        state["current_model_key"] = None
        _save_mt5_state(state)
        return None

    current_key = state.get("current_model_key")
    if current_key:
        current_model = _find_model(catalog, str(current_key))
        if current_model is not None and current_model.get("mt5_in_progress"):
            return current_model
        state["current_model_key"] = None

    groups = _get_rotation_groups()
    provider_groups = groups[:-1]

    start_index = int(state.get("next_provider_index", 0))
    for offset in range(len(provider_groups)):
        provider = provider_groups[(start_index + offset) % len(provider_groups)]
        model = _mt5_untested_models(catalog, provider)
        if model is not None:
            model_key = _model_key(model)
            model["mt5_in_progress"] = True
            model["last_tested_at"] = _now()
            state["current_model_key"] = model_key
            state["next_provider_index"] = (start_index + offset + 1) % max(1, len(provider_groups))
            _save_catalog(catalog)
            _save_mt5_state(state)
            return model

    confirmed = _mt5_confirmed_models(catalog)
    if confirmed:
        current_index = int(state.get("confirmed_model_index", 0))
        for offset in range(len(confirmed)):
            idx = (current_index + offset) % len(confirmed)
            model = confirmed[idx]
            model_key = _model_key(model)
            if model.get("mt5_in_progress"):
                continue  # busy, skip
            model["mt5_in_progress"] = True
            state["current_model_key"] = model_key
            state["confirmed_model_index"] = (idx + 1) % len(confirmed)
            _save_catalog(catalog)
            _save_mt5_state(state)
            return model

    state["current_model_key"] = None
    _save_mt5_state(state)
    return None


def record_request_result_mt5(
    model_key: str,
    input_chars: int,
    output_chars: int = 0,
    success: bool = False,
    ends_model_test: bool = False,
    error_type: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    """Record result for MT5-specific rotation. Updates test_status and mt5_in_progress."""
    catalog = _load_catalog()
    state = _load_mt5_state()

    result_key = str(model_key)
    model = _find_model(catalog, result_key)
    if model is None:
        raise RuntimeError(f"Result model '{result_key}' was not found in the catalog.")

    previous_status = model.get("test_status")
    input_chars = max(0, int(input_chars))
    output_chars = max(0, int(output_chars))

    if success:
        previous_chars = model.get("lifetime_chars") or 0
        model["lifetime_chars"] = int(previous_chars) + input_chars
        model["output_chars"] += output_chars
        model["successful_requests"] += 1
        model["last_tested_at"] = _now()
        model["last_error_type"] = None
        model["last_error_message"] = None
    else:
        model["failed_requests"] += 1
        model["last_tested_at"] = _now()
        model["last_error_type"] = error_type
        model["last_error_message"] = error_message

    # Update test_status (shared) and mt5_in_progress (MT5-specific)
    if ends_model_test or (int(model.get("lifetime_chars") or 0) >= CONFIRMED_MODEL_ENTRY_CHARS):
        model["test_status"] = "confirmed"
    else:
        if previous_status == "in_progress":
            model["test_status"] = "confirmed_in_progress"
        else:
            model["test_status"] = "in_progress"

    # MT5-specific: clear busy flag
    model["mt5_in_progress"] = False

    if state.get("current_model_key") == result_key:
        state["current_model_key"] = None

    _save_catalog(catalog)
    _save_mt5_state(state)

    return {
        "model_key": result_key,
        "success": bool(success),
        "lifetime_chars": model.get("lifetime_chars"),
        "test_status": model.get("test_status"),
        "mt5_in_progress": model.get("mt5_in_progress"),
        "current_model_key": state.get("current_model_key"),
    }
'''

# Insert MT5 functions before get_rotation_status
marker = "def get_rotation_status() -> dict[str, Any]:"
pos = content.find(marker)
if pos >= 0:
    content = content[:pos] + mt5_funcs + "\n\n" + content[pos:]
    open(path, "w", encoding="utf-8").write(content)
    print("Inserted MT5 rotation functions")

# 3. Update select_next_model to also check codex_in_progress
# Find the function and add busy check
# Look for: if current_model is not None and current_model.get(
#            "test_status") in {"in_progress", "confirmed_in_progress"}:
old_busy = '''    current_key = state.get("current_model_key")

    if current_key:
        current_model = _find_model(catalog, str(current_key))

        if current_model is not None and current_model.get(
            "test_status"
        ) in {"in_progress", "confirmed_in_progress"}:
            return current_model

        state["current_model_key"] = None'''

new_busy = '''    current_key = state.get("current_model_key")

    if current_key:
        current_model = _find_model(catalog, str(current_key))

        if current_model is not None and current_model.get(
            "test_status"
        ) in {"in_progress", "confirmed_in_progress"} and current_model.get("codex_in_progress"):
            return current_model

        state["current_model_key"] = None'''

content = content.replace(old_busy, new_busy)

# 4. Update _select_ordinary_model to set codex_in_progress = True when selecting
old_select_ordinary = '''    for model in catalog["models"]:
        _initialize_model_fields(model)

        if _provider_key(str(model.get("provider", ""))) != provider:
            continue

        if model.get("test_status") != "untested":
            continue

        model_key = _model_key(model)
        model["key"] = model_key
        model["test_status"] = "in_progress"
        model["last_tested_at"] = _now()'''

new_select_ordinary = '''    for model in catalog["models"]:
        _initialize_model_fields(model)

        if _provider_key(str(model.get("provider", ""))) != provider:
            continue

        if model.get("test_status") != "untested":
            continue

        if model.get("codex_in_progress"):
            continue  # busy for Codex, skip

        model_key = _model_key(model)
        model["key"] = model_key
        model["test_status"] = "in_progress"
        model["codex_in_progress"] = True
        model["last_tested_at"] = _now()'''

content = content.replace(old_select_ordinary, new_select_ordinary)

# 5. Update _select_confirmed_model to set codex_in_progress = True
old_select_confirmed = '''    model = confirmed[start_index]
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
    state["finished"] = False'''

new_select_confirmed = '''    model = confirmed[start_index]
    model_key = _model_key(model)

    if model.get("codex_in_progress"):
        # This confirmed model is busy for Codex, skip to next
        start_index = (start_index + 1) % len(confirmed)
        model = confirmed[start_index]
        model_key = _model_key(model)

    model["key"] = model_key
    model["lifetime_chars"] = 0
    model["test_status"] = "confirmed_in_progress"
    model["codex_in_progress"] = True
    model["last_tested_at"] = _now()
    model["last_error_type"] = None
    model["last_error_message"] = None

    state["current_model_key"] = model_key
    state["confirmed_model_key"] = model_key
    state["confirmed_model_index"] = start_index
    state["finished"] = False'''

content = content.replace(old_select_confirmed, new_select_confirmed)

# 6. Update record_request_result to clear codex_in_progress and set test_status correctly
old_record = '''    if ends_model_test:
        if int(model.get("lifetime_chars") or 0) >= CONFIRMED_MODEL_ENTRY_CHARS:
            model["test_status"] = "confirmed"
            model["failure_at"] = None
        else:
            model["test_status"] = "failed"
            model["failure_at"] = _now()

        if state.get("current_model_key") == result_key:
            state["current_model_key"] = None'''

new_record = '''    if ends_model_test:
        if int(model.get("lifetime_chars") or 0) >= CONFIRMED_MODEL_ENTRY_CHARS:
            model["test_status"] = "confirmed"
            model["failure_at"] = None
        else:
            model["test_status"] = "failed"
            model["failure_at"] = _now()

        # Clear codex_in_progress for both success and failure
        model["codex_in_progress"] = False

        if state.get("current_model_key") == result_key:
            state["current_model_key"] = None'''

content = content.replace(old_record, new_record)

# Write back
open(path, "w", encoding="utf-8").write(content)
print("All patches applied")
