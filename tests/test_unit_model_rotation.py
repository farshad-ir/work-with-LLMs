import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.model_rotation import (
    _get_dynamic_provider_order,
    _get_rotation_groups,
    _get_group_code,
    _provider_key,
    _advance_rotation_group,
    _select_ordinary_model,
    _select_confirmed_model,
    select_next_model,
    record_request_result,
    get_rotation_status,
    set_test_input_char_limit,
    _load_catalog,
    _save_catalog,
    _load_state,
    _save_state,
    DEFAULT_TEST_INPUT_CHAR_LIMIT,
    CONFIRMED_MODEL_ENTRY_CHARS,
    CONFIRMED_MODEL_CHAR_LIMIT,
)


# ----------------------------------------------------------------------
# Fixtures and helpers
# ----------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Redirect all data files to a temporary directory."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    import app.model_rotation as mr

    monkeypatch.setattr(mr, "DATA_DIR", data_dir)
    monkeypatch.setattr(mr, "CATALOG_PATH", data_dir / "large_catalog.json")
    monkeypatch.setattr(
        mr,
        "ROTATION_STATE_PATH",
        data_dir / "rotation_state.json",
    )

    _save_catalog({"models": []})
    _save_state({})

    yield data_dir


@pytest.fixture
def mock_config():
    """Create a controlled provider configuration."""

    def _make_config(providers_dict):
        return {"providers": providers_dict}

    return _make_config


def _make_catalog(models_list):
    return {"models": models_list}


def _make_model(provider, model_id, **kwargs):
    """Create a model using the version 2 status contract."""
    model = {
        "provider": provider,
        "id": model_id,
        "test_status": "untested",
        "lifetime_chars": None,
    }
    model.update(kwargs)
    return model


def _provider_config(enabled=True):
    return {
        "enabled": enabled,
        "models": [],
        "base_url": "",
        "api_key_env": "",
    }


# ----------------------------------------------------------------------
# Test A — Existing three providers
# ----------------------------------------------------------------------

def test_a_existing_three_providers_order(
    isolated_data_dir,
    mock_config,
    monkeypatch,
):
    config = mock_config({
        "nvidia": _provider_config(),
        "openrouter": _provider_config(),
        "token_router": _provider_config(),
    })

    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)

    providers = _get_dynamic_provider_order()

    assert providers == [
        "nvidia",
        "openrouter",
        "token_router",
    ]

    assert _get_rotation_groups() == [
        "nvidia",
        "openrouter",
        "token_router",
        "confirmed_models",
    ]


# ----------------------------------------------------------------------
# Test B — Reordered providers
# ----------------------------------------------------------------------

def test_b_reordered_providers(
    isolated_data_dir,
    mock_config,
    monkeypatch,
):
    config = mock_config({
        "token_router": _provider_config(),
        "nvidia": _provider_config(),
        "openrouter": _provider_config(),
    })

    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)

    assert _get_dynamic_provider_order() == [
        "token_router",
        "nvidia",
        "openrouter",
    ]

    assert _get_rotation_groups() == [
        "token_router",
        "nvidia",
        "openrouter",
        "confirmed_models",
    ]


# ----------------------------------------------------------------------
# Test C — New provider
# ----------------------------------------------------------------------

def test_c_new_provider(
    isolated_data_dir,
    mock_config,
    monkeypatch,
):
    config = mock_config({
        "nvidia": _provider_config(),
        "openrouter": _provider_config(),
        "token_router": _provider_config(),
        "my_new_provider": _provider_config(),
    })

    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)

    providers = _get_dynamic_provider_order()

    assert providers == [
        "nvidia",
        "openrouter",
        "token_router",
        "my_new_provider",
    ]

    assert _get_rotation_groups() == [
        "nvidia",
        "openrouter",
        "token_router",
        "my_new_provider",
        "confirmed_models",
    ]

    assert _get_group_code("my_new_provider") == "MY_"


# ----------------------------------------------------------------------
# Test D — Disabled provider
# ----------------------------------------------------------------------

def test_d_disabled_provider(
    isolated_data_dir,
    mock_config,
    monkeypatch,
):
    config = mock_config({
        "nvidia": _provider_config(True),
        "openrouter": _provider_config(False),
        "token_router": _provider_config(True),
    })

    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)

    assert _get_dynamic_provider_order() == [
        "nvidia",
        "token_router",
    ]

    assert _get_rotation_groups() == [
        "nvidia",
        "token_router",
        "confirmed_models",
    ]


# ----------------------------------------------------------------------
# Test E — Removed provider / stale pointer recovery
# ----------------------------------------------------------------------

def test_e_removed_provider_stale_pointer(
    isolated_data_dir,
    mock_config,
    monkeypatch,
):
    config = mock_config({
        "nvidia": _provider_config(),
        "token_router": _provider_config(),
    })

    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)

    _save_state({
        "next_rotation_group": "openrouter",
        "next_rotation_group_index": 0,
        "next_provider_index": 0,
        "current_model_key": None,
        "finished": False,
        "test_input_char_limit": DEFAULT_TEST_INPUT_CHAR_LIMIT,
        "round_number": 1,
        "round_total": 0,
        "round_completed": 0,
    })

    _save_catalog(_make_catalog([
        _make_model("nvidia", "model-1"),
        _make_model("token_router", "model-2"),
    ]))

    model = select_next_model()

    assert model is not None
    assert model["provider"] in ("nvidia", "token_router")

    # The current model remains selected until its result is recorded.
    model2 = select_next_model()

    assert model2 is not None
    assert model2["key"] == model["key"]


# ----------------------------------------------------------------------
# Test F — No enabled providers
# ----------------------------------------------------------------------

def test_f_no_enabled_providers(
    isolated_data_dir,
    mock_config,
    monkeypatch,
):
    config = mock_config({
        "nvidia": _provider_config(False),
        "openrouter": _provider_config(False),
        "token_router": _provider_config(False),
    })

    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)

    assert _get_dynamic_provider_order() == []
    assert _get_rotation_groups() == ["confirmed_models"]

    assert select_next_model() is None

    # Confirmed models remain selectable even when all ordinary
    # providers are disabled.
    _save_catalog(_make_catalog([
        _make_model(
            "any-provider",
            "confirmed-model",
            test_status="confirmed",
            lifetime_chars=CONFIRMED_MODEL_ENTRY_CHARS,
        ),
    ]))

    model = select_next_model()

    assert model is not None
    assert model["id"] == "confirmed-model"
    assert model["test_status"] == "confirmed_in_progress"


# ----------------------------------------------------------------------
# Test G — State migration
# ----------------------------------------------------------------------

def test_g_state_migration_numeric_only(
    isolated_data_dir,
    mock_config,
    monkeypatch,
):
    config = mock_config({
        "nvidia": _provider_config(),
        "openrouter": _provider_config(),
    })

    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)

    _save_state({
        "next_rotation_group_index": 1,
        "next_provider_index": 0,
        "current_model_key": None,
        "finished": False,
        "test_input_char_limit": DEFAULT_TEST_INPUT_CHAR_LIMIT,
        "round_number": 1,
        "round_total": 0,
        "round_completed": 0,
    })

    _save_catalog(_make_catalog([
        _make_model("nvidia", "model-1"),
        _make_model("openrouter", "model-2"),
    ]))

    model = select_next_model()

    assert model is not None
    assert model["provider"] == "openrouter"


def test_g_state_migration_valid_group_name(
    isolated_data_dir,
    mock_config,
    monkeypatch,
):
    config = mock_config({
        "nvidia": _provider_config(),
        "openrouter": _provider_config(),
    })

    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)

    _save_state({
        "next_rotation_group": "openrouter",
        "next_rotation_group_index": 999,
        "next_provider_index": 0,
        "current_model_key": None,
        "finished": False,
        "test_input_char_limit": DEFAULT_TEST_INPUT_CHAR_LIMIT,
        "round_number": 1,
        "round_total": 0,
        "round_completed": 0,
    })

    _save_catalog(_make_catalog([
        _make_model("nvidia", "model-1"),
        _make_model("openrouter", "model-2"),
    ]))

    model = select_next_model()

    assert model is not None
    assert model["provider"] == "openrouter"


def test_g_state_migration_stale_group_name(
    isolated_data_dir,
    mock_config,
    monkeypatch,
):
    config = mock_config({
        "nvidia": _provider_config(),
        "token_router": _provider_config(),
    })

    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)

    _save_state({
        "next_rotation_group": "openrouter",
        "next_rotation_group_index": 0,
        "next_provider_index": 0,
        "current_model_key": None,
        "finished": False,
        "test_input_char_limit": DEFAULT_TEST_INPUT_CHAR_LIMIT,
        "round_number": 1,
        "round_total": 0,
        "round_completed": 0,
    })

    _save_catalog(_make_catalog([
        _make_model("nvidia", "model-1"),
        _make_model("token_router", "model-2"),
    ]))

    model = select_next_model()

    assert model is not None
    assert model["provider"] in ("nvidia", "token_router")


def test_g_state_migration_invalid_numeric_index(
    isolated_data_dir,
    mock_config,
    monkeypatch,
):
    config = mock_config({
        "nvidia": _provider_config(),
    })

    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)

    _save_state({
        "next_rotation_group_index": 999,
        "next_provider_index": 0,
        "current_model_key": None,
        "finished": False,
        "test_input_char_limit": DEFAULT_TEST_INPUT_CHAR_LIMIT,
        "round_number": 1,
        "round_total": 0,
        "round_completed": 0,
    })

    _save_catalog(_make_catalog([
        _make_model("nvidia", "model-1"),
    ]))

    model = select_next_model()

    assert model is not None
    assert model["provider"] == "nvidia"


def test_g_state_migration_only_confirmed(
    isolated_data_dir,
    mock_config,
    monkeypatch,
):
    config = mock_config({
        "nvidia": _provider_config(False),
    })

    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)

    _save_state({
        "next_rotation_group_index": 0,
        "next_provider_index": 0,
        "current_model_key": None,
        "finished": False,
        "test_input_char_limit": DEFAULT_TEST_INPUT_CHAR_LIMIT,
        "round_number": 1,
        "round_total": 0,
        "round_completed": 0,
    })

    _save_catalog(_make_catalog([
        _make_model(
            "any-provider",
            "confirmed-1",
            test_status="confirmed",
            lifetime_chars=CONFIRMED_MODEL_ENTRY_CHARS,
        ),
    ]))

    model = select_next_model()

    assert model is not None
    assert model["id"] == "confirmed-1"
    assert model["test_status"] == "confirmed_in_progress"


# ----------------------------------------------------------------------
# Test H — Confirmed lifecycle
# ----------------------------------------------------------------------

def test_h_confirmed_lifecycle_preserved(
    isolated_data_dir,
    mock_config,
    monkeypatch,
):
    config = mock_config({
        "nvidia": _provider_config(),
    })

    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)

    _save_catalog(_make_catalog([
        _make_model("nvidia", "model-1"),
    ]))

    model = select_next_model()

    assert model is not None

    model_key = model["key"]

    record_request_result(
        model_key=model_key,
        input_chars=CONFIRMED_MODEL_ENTRY_CHARS,
        output_chars=100,
        success=True,
        ends_model_test=True,
    )

    # The initial test must move the model into confirmed status.
    cat = _load_catalog()
    confirmed_model = next(
        m for m in cat["models"]
        if m["key"] == model_key
    )

    assert confirmed_model["test_status"] == "confirmed"
    assert confirmed_model["lifetime_chars"] == CONFIRMED_MODEL_ENTRY_CHARS

    # The confirmed turn starts with a fresh lifetime counter.
    model2 = select_next_model()

    assert model2 is not None
    assert model2["key"] == model_key
    assert model2["lifetime_chars"] == 0
    assert model2["test_status"] == "confirmed_in_progress"

    # A confirmed turn uses the 750k character limit.
    record_request_result(
        model_key=model2["key"],
        input_chars=CONFIRMED_MODEL_CHAR_LIMIT,
        output_chars=200,
        success=True,
        ends_model_test=True,
    )

    cat = _load_catalog()
    confirmed_model = next(
        m for m in cat["models"]
        if m["key"] == model2["key"]
    )

    assert confirmed_model["test_status"] == "confirmed"
    assert confirmed_model["lifetime_chars"] == CONFIRMED_MODEL_CHAR_LIMIT


def test_h_confirmed_entry_and_turn_limits(
    isolated_data_dir,
    mock_config,
    monkeypatch,
):
    assert CONFIRMED_MODEL_ENTRY_CHARS == 50_000
    assert CONFIRMED_MODEL_CHAR_LIMIT == 750_000
    assert DEFAULT_TEST_INPUT_CHAR_LIMIT == 250_000


# ----------------------------------------------------------------------
# Test I — Failed retry regression
# ----------------------------------------------------------------------

def test_i_failed_retry_only_after_enabled_exhausted(
    isolated_data_dir,
    mock_config,
    monkeypatch,
):
    config = mock_config({
        "nvidia": _provider_config(),
        "openrouter": _provider_config(),
    })

    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)

    _save_catalog(_make_catalog([
        _make_model("nvidia", "model-1"),
        _make_model("nvidia", "model-2"),
        _make_model("openrouter", "model-3"),
    ]))

    m1 = select_next_model()
    assert m1["id"] == "model-1"

    record_request_result(
        m1["key"], 100, 50,
        success=False,
        ends_model_test=True,
        error_type="test",
    )

    m2 = select_next_model()
    assert m2["id"] == "model-2"

    record_request_result(
        m2["key"], 100, 50,
        success=False,
        ends_model_test=True,
        error_type="test",
    )

    m3 = select_next_model()
    assert m3["id"] == "model-3"

    record_request_result(
        m3["key"], 100, 50,
        success=False,
        ends_model_test=True,
        error_type="test",
    )

    # All enabled ordinary providers are exhausted.
    # Failed models are reset and a new retry round begins.
    m4 = select_next_model()

    assert m4 is not None

    cat = _load_catalog()

    untested_count = sum(
        1 for m in cat["models"]
        if m["test_status"] == "untested"
    )

    in_progress_count = sum(
        1 for m in cat["models"]
        if m["test_status"] == "in_progress"
    )

    assert untested_count == 2
    assert in_progress_count == 1
    assert untested_count + in_progress_count == 3

    for model in cat["models"]:
        assert model["failure_at"] is None


def test_i_disabled_provider_failures_not_reintroduced(
    isolated_data_dir,
    mock_config,
    monkeypatch,
):
    config = mock_config({
        "nvidia": _provider_config(),
        "openrouter": _provider_config(False),
    })

    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)

    _save_catalog(_make_catalog([
        _make_model("nvidia", "model-1"),
        _make_model("nvidia", "model-2"),
        _make_model(
            "openrouter",
            "failed-model",
            test_status="failed",
        ),
    ]))

    m1 = select_next_model()

    record_request_result(
        m1["key"], 100, 50,
        success=False,
        ends_model_test=True,
        error_type="test",
    )

    m2 = select_next_model()

    record_request_result(
        m2["key"], 100, 50,
        success=False,
        ends_model_test=True,
        error_type="test",
    )

    m3 = select_next_model()

    assert m3 is not None

    cat = _load_catalog()

    failed_openrouter = next(
        m for m in cat["models"]
        if m["id"] == "failed-model"
    )

    assert failed_openrouter["test_status"] == "failed"

    nvidia_models = [
        m for m in cat["models"]
        if m["provider"] == "nvidia"
    ]

    nvidia_statuses = {
        m["test_status"]
        for m in nvidia_models
    }

    assert nvidia_statuses == {
        "untested",
        "in_progress",
    }


# ----------------------------------------------------------------------
# Logging with unknown provider
# ----------------------------------------------------------------------

def test_logging_unknown_provider(
    isolated_data_dir,
    mock_config,
    monkeypatch,
):
    config = mock_config({
        "unknown_provider": _provider_config(),
    })

    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)

    _save_catalog(_make_catalog([
        _make_model("unknown_provider", "model-1"),
    ]))

    model = select_next_model()

    assert model is not None

    result = record_request_result(
        model_key=model["key"],
        input_chars=100,
        output_chars=50,
        success=True,
        ends_model_test=True,
    )

    assert result["model_key"] == model["key"]


# ----------------------------------------------------------------------
# Pointer synchronization
# ----------------------------------------------------------------------

def test_pointer_sync_after_selection(
    isolated_data_dir,
    mock_config,
    monkeypatch,
):
    config = mock_config({
        "nvidia": _provider_config(),
        "openrouter": _provider_config(),
    })

    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)

    _save_catalog(_make_catalog([
        _make_model("nvidia", "model-1"),
        _make_model("openrouter", "model-2"),
    ]))

    # First selection: nvidia.
    m1 = select_next_model()

    assert m1["provider"] == "nvidia"

    state = _load_state()

    assert state["next_rotation_group"] == "openrouter"
    assert state["next_rotation_group_index"] == 1

    record_request_result(
        m1["key"],
        CONFIRMED_MODEL_ENTRY_CHARS,
        50,
        success=True,
        ends_model_test=True,
    )

    # Second selection: openrouter.
    m2 = select_next_model()

    assert m2["provider"] == "openrouter"

    state = _load_state()

    assert state["next_rotation_group"] == "confirmed_models"
    assert state["next_rotation_group_index"] == 2

    record_request_result(
        m2["key"],
        CONFIRMED_MODEL_ENTRY_CHARS,
        50,
        success=True,
        ends_model_test=True,
    )

    # Both ordinary models are now confirmed.
    # The next selection must come from confirmed_models.
    m3 = select_next_model()

    assert m3 is not None
    assert m3["test_status"] == "confirmed_in_progress"

    state = _load_state()

    assert state["next_rotation_group"] == "nvidia"
    assert state["next_rotation_group_index"] == 0


# ----------------------------------------------------------------------
# Duplicate provider normalization
# ----------------------------------------------------------------------

def test_duplicate_normalization(
    isolated_data_dir,
    mock_config,
    monkeypatch,
):
    config = mock_config({
        "nvidia_nim": _provider_config(),
        "nvidia": _provider_config(),
        "NVIDIA": _provider_config(),
    })

    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)

    assert _get_dynamic_provider_order() == ["nvidia"]


# ----------------------------------------------------------------------
# Round number and round completion
# ----------------------------------------------------------------------

def test_round_number_increments_on_retry(
    isolated_data_dir,
    mock_config,
    monkeypatch,
):
    config = mock_config({
        "nvidia": _provider_config(),
    })

    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)

    _save_catalog(_make_catalog([
        _make_model("nvidia", "model-1"),
    ]))

    m1 = select_next_model()

    record_request_result(
        m1["key"],
        100,
        50,
        success=False,
        ends_model_test=True,
        error_type="test",
    )

    m2 = select_next_model()

    assert m2 is not None

    state = _load_state()

    assert state["round_number"] == 2
    assert state["round_total"] == 1
    assert state["round_completed"] == 0


# ----------------------------------------------------------------------
# Removed-provider failures
# ----------------------------------------------------------------------

def test_removed_provider_failures_not_reintroduced(
    isolated_data_dir,
    mock_config,
    monkeypatch,
):
    config = mock_config({
        "nvidia": _provider_config(),
        "openrouter": _provider_config(),
    })

    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)

    _save_catalog(_make_catalog([
        _make_model("nvidia", "model-1"),
        _make_model("openrouter", "model-2"),
        _make_model(
            "token_router",
            "failed-removed-model",
            test_status="failed",
        ),
    ]))

    m1 = select_next_model()

    record_request_result(
        m1["key"],
        100,
        50,
        success=False,
        ends_model_test=True,
        error_type="test",
    )

    m2 = select_next_model()

    record_request_result(
        m2["key"],
        100,
        50,
        success=False,
        ends_model_test=True,
        error_type="test",
    )

    m3 = select_next_model()

    assert m3 is not None

    cat = _load_catalog()

    failed_removed = next(
        m for m in cat["models"]
        if m["id"] == "failed-removed-model"
    )

    assert failed_removed["test_status"] == "failed"

    ordinary_models = [
        m for m in cat["models"]
        if m["provider"] in ("nvidia", "openrouter")
    ]

    statuses = {
        m["test_status"]
        for m in ordinary_models
    }

    assert statuses == {
        "untested",
        "in_progress",
    }


# ----------------------------------------------------------------------
# Exactly one PTR event per pointer transition
# ----------------------------------------------------------------------

def test_single_ptr_event_per_transition(
    isolated_data_dir,
    mock_config,
    monkeypatch,
):
    config = mock_config({
        "nvidia": _provider_config(),
        "openrouter": _provider_config(),
    })

    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)

    _save_catalog(_make_catalog([
        _make_model("nvidia", "model-1"),
        _make_model("openrouter", "model-2"),
    ]))

    log_path = mr.DATA_DIR / "rotation.log"

    def read_log():
        if not log_path.exists():
            return []

        content = log_path.read_text(encoding="utf-8").strip()

        return content.splitlines() if content else []

    # First transition: nvidia -> openrouter.
    m1 = select_next_model()

    record_request_result(
        m1["key"],
        CONFIRMED_MODEL_ENTRY_CHARS,
        50,
        success=True,
        ends_model_test=True,
    )

    logs = read_log()

    ptr_lines = [
        line for line in logs
        if " | PTR | " in line
    ]

    assert len(ptr_lines) == 1
    assert "NVD" in ptr_lines[0]

    # Second transition: openrouter -> confirmed_models.
    m2 = select_next_model()

    record_request_result(
        m2["key"],
        CONFIRMED_MODEL_ENTRY_CHARS,
        50,
        success=True,
        ends_model_test=True,
    )

    logs = read_log()

    ptr_lines = [
        line for line in logs
        if " | PTR | " in line
    ]

    assert len(ptr_lines) == 2
    assert "OPR" in ptr_lines[1]

    # Third transition: confirmed_models -> nvidia.
    m3 = select_next_model()

    assert m3 is not None
    assert m3["test_status"] == "confirmed_in_progress"

    logs = read_log()

    ptr_lines = [
        line for line in logs
        if " | PTR | " in line
    ]

    assert len(ptr_lines) == 3
    assert "CFM" in ptr_lines[2]

    # Every pointer transition must be logged exactly once.
    transition_counts = {}

    for line in ptr_lines:
        detail = line.split(" | ")[-1]
        transition_counts[detail] = (
            transition_counts.get(detail, 0) + 1
        )

    for detail, count in transition_counts.items():
        assert count == 1, (
            f"Duplicate PTR for transition {detail}: "
            f"count={count}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
