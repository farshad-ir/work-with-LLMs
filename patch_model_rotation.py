import json
from pathlib import Path

path = Path("C:/Users/Rezvan/work/codex/work-with-LLMs/app/model_rotation.py")
content = path.read_text(encoding="utf-8")

# Add MT5-specific rotation functions after record_request_result
mt5_code = '''
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
        if model.get("mt5_status") == "mt5_confirmed":
            confirmed.append(model)
    return confirmed


def _mt5_untested_models(catalog, provider):
    for model in catalog["models"]:
        if _provider_key(str(model.get("provider", ""))) == provider:
            if model.get("mt5_status") == "pending":
                return model
    return None


def select_next_model_mt5() -> dict[str, Any] | None:
    \"\"\"Select next model for MT5 rotation using same catalog order as Codex.
    
    Independent rotation: MT5 only checks mt5_status, not test_status.
    If mt5_status == "mt5_in_progress", pick next model from same provider.
    If confirmed model is busy (mt5_in_progress), pick next confirmed model.
    \"\"\"
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
        if current_model is not None and current_model.get("mt5_status") == "mt5_in_progress":
            # Already in progress for MT5 - return the same model (busy channel)
            return current_model
        # Model finished for MT5, clear cursor
        state["current_model_key"] = None

    # Get providers in order (same as Codex rotation)
    groups = _get_rotation_groups()
    provider_groups = groups[:-1]  # all except confirmed_models

    # Try ordinary providers in order
    start_index = int(state.get("next_provider_index", 0))
    for offset in range(len(provider_groups)):
        provider = provider_groups[(start_index + offset) % len(provider_groups)]
        model = _mt5_untested_models(catalog, provider)
        if model is not None:
            model_key = _model_key(model)
            model["mt5_status"] = "mt5_in_progress"
            model["last_tested_at"] = _now()
            state["current_model_key"] = model_key
            state["next_provider_index"] = (start_index + offset + 1) % max(1, len(provider_groups))
            _save_catalog(catalog)
            _save_mt5_state(state)
            return model

    # Try confirmed models for MT5
    confirmed = _mt5_confirmed_models(catalog)
    if confirmed:
        current_index = int(state.get("confirmed_model_index", 0))
        for offset in range(len(confirmed)):
            idx = (current_index + offset) % len(confirmed)
            model = confirmed[idx]
            model_key = _model_key(model)
            if model.get("mt5_status") == "mt5_in_progress":
                continue  # busy, skip
            model["mt5_status"] = "mt5_confirmed_in_progress"
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
    \"\"\"Record result for MT5-specific rotation. Updates mt5_status independently.\"\"\"
    catalog = _load_catalog()
    state = _load_mt5_state()

    result_key = str(model_key)
    model = _find_model(catalog, result_key)
    if model is None:
        raise RuntimeError(f"Result model '{result_key}' was not found in the catalog.")

    previous_status = model.get("mt5_status")
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

    # Update mt5_status independently
    if ends_model_test or (int(model.get("lifetime_chars") or 0) >= CONFIRMED_MODEL_ENTRY_CHARS):
        model["mt5_status"] = "mt5_confirmed"
    else:
        model["mt5_status"] = "mt5_confirmed_in_progress" if previous_status == "mt5_in_progress" else "mt5_in_progress"

    if state.get("current_model_key") == result_key:
        state["current_model_key"] = None

    _save_catalog(catalog)
    _save_mt5_state(state)

    return {
        "model_key": result_key,
        "success": bool(success),
        "lifetime_chars": model.get("lifetime_chars"),
        "mt5_status": model.get("mt5_status"),
        "current_model_key": state.get("current_model_key"),
    }
'''

# Insert MT5 code before the last function (get_rotation_status)
marker = "def get_rotation_status() -> dict[str, Any]:"
insert_pos = content.find(marker)
if insert_pos == -1:
    raise RuntimeError("Could not find get_rotation_status marker")
content = content[:insert_pos] + mt5_code + "\n\n" + content[insert_pos:]

path.write_text(content, encoding="utf-8")
print("model_rotation.py patched with MT5 rotation functions")
