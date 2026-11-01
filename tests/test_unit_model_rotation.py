import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Import the module under test
import sys
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
# Test fixtures
# ----------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Redirect all data files to a temporary directory."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    
    import app.model_rotation as mr
    monkeypatch.setattr(mr, "DATA_DIR", data_dir)
    monkeypatch.setattr(mr, "CATALOG_PATH", data_dir / "large_catalog.json")
    monkeypatch.setattr(mr, "ROTATION_STATE_PATH", data_dir / "rotation_state.json")
    
    # Start with empty catalog and state
    _save_catalog({"models": []})
    _save_state({})
    
    yield data_dir


@pytest.fixture
def mock_config():
    """Mock load_config to return a controlled provider configuration."""
    def _make_config(providers_dict):
        return {"providers": providers_dict}
    return _make_config


def _make_catalog(models_list):
    """Helper to create a catalog with models."""
    return {"models": models_list}


def _make_model(provider, model_id, **kwargs):
    """Helper to create a model dict."""
    m = {
        "provider": provider,
        "id": model_id,
        "test_status": "untested",
        "lifetime_chars": None,
    }
    m.update(kwargs)
    return m


# ----------------------------------------------------------------------
# Test A — Existing three providers (order follows config)
# ----------------------------------------------------------------------

def test_a_existing_three_providers_order(isolated_data_dir, mock_config, monkeypatch):
    """Rotation order must follow config order, not hard-coded order."""
    config = mock_config({
        "nvidia": {"enabled": True, "models": [], "base_url": "", "api_key_env": ""},
        "openrouter": {"enabled": True, "models": [], "base_url": "", "api_key_env": ""},
        "token_router": {"enabled": True, "models": [], "base_url": "", "api_key_env": ""},
    })
    
    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)
    
    providers = _get_dynamic_provider_order()
    assert providers == ["nvidia", "openrouter", "token_router"]
    
    groups = _get_rotation_groups()
    assert groups == ["nvidia", "openrouter", "token_router", "confirmed_models"]


# ----------------------------------------------------------------------
# Test B — Reordered providers
# ----------------------------------------------------------------------

def test_b_reordered_providers(isolated_data_dir, mock_config, monkeypatch):
    """Changing config order must change rotation order."""
    config = mock_config({
        "token_router": {"enabled": True, "models": [], "base_url": "", "api_key_env": ""},
        "nvidia": {"enabled": True, "models": [], "base_url": "", "api_key_env": ""},
        "openrouter": {"enabled": True, "models": [], "base_url": "", "api_key_env": ""},
    })
    
    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)
    
    providers = _get_dynamic_provider_order()
    assert providers == ["token_router", "nvidia", "openrouter"]
    
    groups = _get_rotation_groups()
    assert groups == ["token_router", "nvidia", "openrouter", "confirmed_models"]


# ----------------------------------------------------------------------
# Test C — New provider
# ----------------------------------------------------------------------

def test_c_new_provider(isolated_data_dir, mock_config, monkeypatch):
    """Adding a new provider must work without code changes."""
    config = mock_config({
        "nvidia": {"enabled": True, "models": [], "base_url": "", "api_key_env": ""},
        "openrouter": {"enabled": True, "models": [], "base_url": "", "api_key_env": ""},
        "token_router": {"enabled": True, "models": [], "base_url": "", "api_key_env": ""},
        "my_new_provider": {"enabled": True, "models": [], "base_url": "", "api_key_env": ""},
    })
    
    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)
    
    providers = _get_dynamic_provider_order()
    assert "my_new_provider" in providers
    assert providers == ["nvidia", "openrouter", "token_router", "my_new_provider"]
    
    groups = _get_rotation_groups()
    assert groups == ["nvidia", "openrouter", "token_router", "my_new_provider", "confirmed_models"]
    
    # Logging must not raise KeyError
    code = _get_group_code("my_new_provider")
    assert code == "MY_"
    assert isinstance(code, str)


# ----------------------------------------------------------------------
# Test D — Disabled provider
# ----------------------------------------------------------------------

def test_d_disabled_provider(isolated_data_dir, mock_config, monkeypatch):
    """Disabled providers must be excluded from ordinary rotation."""
    config = mock_config({
        "nvidia": {"enabled": True, "models": [], "base_url": "", "api_key_env": ""},
        "openrouter": {"enabled": False, "models": [], "base_url": "", "api_key_env": ""},
        "token_router": {"enabled": True, "models": [], "base_url": "", "api_key_env": ""},
    })
    
    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)
    
    providers = _get_dynamic_provider_order()
    assert providers == ["nvidia", "token_router"]
    assert "openrouter" not in providers
    
    groups = _get_rotation_groups()
    assert groups == ["nvidia", "token_router", "confirmed_models"]
    assert "openrouter" not in groups


# ----------------------------------------------------------------------
# Test E — Removed provider (stale pointer recovery)
# ----------------------------------------------------------------------

def test_e_removed_provider_stale_pointer(isolated_data_dir, mock_config, monkeypatch):
    """Removing a provider must not crash; pointer must recover safely."""
    config = mock_config({
        "nvidia": {"enabled": True, "models": [], "base_url": "", "api_key_env": ""},
        "token_router": {"enabled": True, "models": [], "base_url": "", "api_key_env": ""},
    })
    
    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)
    
    # Simulate stale state with removed provider as next group
    stale_state = {
        "next_rotation_group": "openrouter",
        "next_rotation_group_index": 0,
        "next_provider_index": 0,
        "current_model_key": None,
        "finished": False,
        "test_input_char_limit": DEFAULT_TEST_INPUT_CHAR_LIMIT,
        "round_number": 1,
        "round_total": 0,
        "round_completed": 0,
    }
    _save_state(stale_state)
    
    # Also add some models so selection proceeds
    catalog = _make_catalog([
        _make_model("nvidia", "model-1"),
        _make_model("token_router", "model-2"),
    ])
    _save_catalog(catalog)
    
    # This must not raise
    model = select_next_model()
    assert model is not None
    assert model["provider"] in ("nvidia", "token_router")
    
    # Next selection should also work
    model2 = select_next_model()
    assert model2 is not None


# ----------------------------------------------------------------------
# Test F — No enabled providers
# ----------------------------------------------------------------------

def test_f_no_enabled_providers(isolated_data_dir, mock_config, monkeypatch):
    """All providers disabled -> only confirmed_models group available."""
    config = mock_config({
        "nvidia": {"enabled": False, "models": [], "base_url": "", "api_key_env": ""},
        "openrouter": {"enabled": False, "models": [], "base_url": "", "api_key_env": ""},
        "token_router": {"enabled": False, "models": [], "base_url": "", "api_key_env": ""},
    })
    
    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)
    
    providers = _get_dynamic_provider_order()
    assert providers == []
    
    groups = _get_rotation_groups()
    assert groups == ["confirmed_models"]
    
    # With no models at all, selection should return None safely
    model = select_next_model()
    assert model is None
    
    # Confirmed models remain selectable with every ordinary provider disabled.
    catalog = _make_catalog([
        _make_model(
            "any-provider",
            "confirmed-model",
            test_status="confirmed",
            lifetime_chars=CONFIRMED_MODEL_ENTRY_CHARS,
        ),
    ])
    _save_catalog(catalog)
    
    model = select_next_model()
    assert model is not None
    assert model["test_status"] == "confirmed_in_progress"


# ----------------------------------------------------------------------
# Test G — State migration
# ----------------------------------------------------------------------

def test_g_state_migration_numeric_only(isolated_data_dir, mock_config, monkeypatch):
    """State with only numeric index must work."""
    config = mock_config({
        "nvidia": {"enabled": True, "models": [], "base_url": "", "api_key_env": ""},
        "openrouter": {"enabled": True, "models": [], "base_url": "", "api_key_env": ""},
    })
    
    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)
    
    # State with only numeric pointer (old format)
    stale_state = {
        "next_rotation_group_index": 1,
        "next_provider_index": 0,
        "current_model_key": None,
        "finished": False,
        "test_input_char_limit": DEFAULT_TEST_INPUT_CHAR_LIMIT,
        "round_number": 1,
        "round_total": 0,
        "round_completed": 0,
    }
    _save_state(stale_state)
    
    catalog = _make_catalog([
        _make_model("nvidia", "model-1"),
        _make_model("openrouter", "model-2"),
    ])
    _save_catalog(catalog)
    
    model = select_next_model()
    assert model is not None


def test_g_state_migration_valid_group_name(isolated_data_dir, mock_config, monkeypatch):
    """State with valid group name must be preferred."""
    config = mock_config({
        "nvidia": {"enabled": True, "models": [], "base_url": "", "api_key_env": ""},
        "openrouter": {"enabled": True, "models": [], "base_url": "", "api_key_env": ""},
    })
    
    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)
    
    stale_state = {
        "next_rotation_group": "openrouter",
        "next_rotation_group_index": 999,  # bogus index
        "next_provider_index": 0,
        "current_model_key": None,
        "finished": False,
        "test_input_char_limit": DEFAULT_TEST_INPUT_CHAR_LIMIT,
        "round_number": 1,
        "round_total": 0,
        "round_completed": 0,
    }
    _save_state(stale_state)
    
    catalog = _make_catalog([
        _make_model("nvidia", "model-1"),
        _make_model("openrouter", "model-2"),
    ])
    _save_catalog(catalog)
    
    model = select_next_model()
    assert model is not None
    assert model["provider"] == "openrouter"


def test_g_state_migration_stale_group_name(isolated_data_dir, mock_config, monkeypatch):
    """Stale group name must fall back to numeric index safely."""
    config = mock_config({
        "nvidia": {"enabled": True, "models": [], "base_url": "", "api_key_env": ""},
        "token_router": {"enabled": True, "models": [], "base_url": "", "api_key_env": ""},
    })
    
    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)
    
    # State references removed provider "openrouter"
    stale_state = {
        "next_rotation_group": "openrouter",
        "next_rotation_group_index": 0,
        "next_provider_index": 0,
        "current_model_key": None,
        "finished": False,
        "test_input_char_limit": DEFAULT_TEST_INPUT_CHAR_LIMIT,
        "round_number": 1,
        "round_total": 0,
        "round_completed": 0,
    }
    _save_state(stale_state)
    
    catalog = _make_catalog([
        _make_model("nvidia", "model-1"),
        _make_model("token_router", "model-2"),
    ])
    _save_catalog(catalog)
    
    # Must not crash, must select from available providers
    model = select_next_model()
    assert model is not None
    assert model["provider"] in ("nvidia", "token_router")


def test_g_state_migration_invalid_numeric_index(isolated_data_dir, mock_config, monkeypatch):
    """Numeric index out of range must be normalized safely."""
    config = mock_config({
        "nvidia": {"enabled": True, "models": [], "base_url": "", "api_key_env": ""},
    })
    
    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)
    
    stale_state = {
        "next_rotation_group_index": 999,  # way out of range
        "next_provider_index": 0,
        "current_model_key": None,
        "finished": False,
        "test_input_char_limit": DEFAULT_TEST_INPUT_CHAR_LIMIT,
        "round_number": 1,
        "round_total": 0,
        "round_completed": 0,
    }
    _save_state(stale_state)
    
    catalog = _make_catalog([
        _make_model("nvidia", "model-1"),
    ])
    _save_catalog(catalog)
    
    model = select_next_model()
    assert model is not None
    assert model["provider"] == "nvidia"


def test_g_state_migration_only_confirmed(isolated_data_dir, mock_config, monkeypatch):
    """Only confirmed_models group -> pointer must resolve to it safely."""
    config = mock_config({
        "nvidia": {"enabled": False, "models": [], "base_url": "", "api_key_env": ""},
    })
    
    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)
    
    stale_state = {
        "next_rotation_group_index": 0,
        "next_provider_index": 0,
        "current_model_key": None,
        "finished": False,
        "test_input_char_limit": DEFAULT_TEST_INPUT_CHAR_LIMIT,
        "round_number": 1,
        "round_total": 0,
        "round_completed": 0,
    }
    _save_state(stale_state)
    
    # Confirmed models remain selectable with every ordinary provider disabled.
    catalog = _make_catalog([
        _make_model(
            "any-provider",
            "confirmed-1",
            test_status="confirmed",
            lifetime_chars=CONFIRMED_MODEL_ENTRY_CHARS,
        ),
    ])
    _save_catalog(catalog)
    
    model = select_next_model()
    assert model is not None
    assert model["test_status"] == "confirmed_in_progress"


# ----------------------------------------------------------------------
# Test H — Confirmed behavior regression
# ----------------------------------------------------------------------

def test_h_confirmed_lifecycle_preserved(isolated_data_dir, mock_config, monkeypatch):
    """Confirmed lifecycle thresholds and behavior unchanged."""
    config = mock_config({
        "nvidia": {"enabled": True, "models": [], "base_url": "", "api_key_env": ""},
    })
    
    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)
    
    catalog = _make_catalog([
        _make_model("nvidia", "model-1"),
    ])
    _save_catalog(catalog)
    
    # Select and run to completion
    model = select_next_model()
    assert model is not None
    model_key = model["key"]
    
    # Successful request reaching confirmed threshold
    record_request_result(
        model_key=model_key,
        input_chars=CONFIRMED_MODEL_ENTRY_CHARS,
        output_chars=100,
        success=True,
        ends_model_test=True,
    )
    
    # Model should now be confirmed
    cat = _load_catalog()
    m = next(m for m in cat["models"] if m["key"] == model_key)
    assert m["test_status"] == "confirmed"
    
    # Confirmed turn should reset lifetime_chars
    model2 = select_next_model()
    assert model2 is not None
    assert model2["lifetime_chars"] == 0
    assert model2["test_status"] == "confirmed_in_progress"
    
    # Confirmed turn ends at CONFIRMED_MODEL_CHAR_LIMIT
    record_request_result(
        model_key=model2["key"],
        input_chars=CONFIRMED_MODEL_CHAR_LIMIT,
        output_chars=200,
        success=True,
        ends_model_test=True,
    )
    
    cat = _load_catalog()
    m = next(m for m in cat["models"] if m["key"] == model2["key"])
    assert m["test_status"] == "confirmed"


def test_h_confirmed_entry_and_turn_limits(isolated_data_dir, mock_config, monkeypatch):
    """Entry threshold 50k, turn limit 750k must be preserved."""
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
    """Failed models are retried only after all enabled providers are exhausted."""
    provider_config = {
        "enabled": True,
        "models": [],
        "base_url": "",
        "api_key_env": "",
    }

    config = mock_config({
        "nvidia": provider_config.copy(),
        "openrouter": provider_config.copy(),
    })

    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)

    _save_catalog(_make_catalog([
        _make_model("nvidia", "model-1"),
        _make_model("nvidia", "model-2"),
        _make_model("openrouter", "model-3"),
    ]))

    # First rotation: NVIDIA model 1.
    m1 = select_next_model()
    assert m1["id"] == "model-1"

    record_request_result(
        m1["key"], 100, 50,
        success=False,
        ends_model_test=True,
        error_type="test",
    )

    # Rotation advances to OpenRouter.
    m2 = select_next_model()
    assert m2["id"] == "model-3"

    record_request_result(
        m2["key"], 100, 50,
        success=False,
        ends_model_test=True,
        error_type="test",
    )

    # Rotation returns to NVIDIA and selects its second model.
    m3 = select_next_model()
    assert m3["id"] == "model-2"

    record_request_result(
        m3["key"], 100, 50,
        success=False,
        ends_model_test=True,
        error_type="test",
    )

    # All enabled ordinary models are now failed.
    # The retry round resets them and selects the first one.
    m4 = select_next_model()
    assert m4 is not None
    assert m4["id"] == "model-1"

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

    state = _load_state()
    assert state["round_number"] == 2
    assert state["round_total"] == 3
    assert state["round_completed"] == 0


def test_i_disabled_provider_failures_not_reintroduced(isolated_data_dir, mock_config, monkeypatch):
    """Failed models from disabled providers must not be retried."""
    config = mock_config({
        "nvidia": {"enabled": True, "models": [], "base_url": "", "api_key_env": ""},
        "openrouter": {"enabled": False, "models": [], "base_url": "", "api_key_env": ""},
    })
    
    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)
    
    catalog = _make_catalog([
        _make_model("nvidia", "model-1"),
        _make_model("nvidia", "model-2"),
        _make_model("openrouter", "failed-model", test_status="failed"),
    ])
    _save_catalog(catalog)
    
    # Exhaust nvidia
    m1 = select_next_model()
    record_request_result(m1["key"], 100, 50, success=False, ends_model_test=True, error_type="test")
    
    m2 = select_next_model()
    record_request_result(m2["key"], 100, 50, success=False, ends_model_test=True, error_type="test")
    
    # Retry round - openrouter failed model must NOT be reset
    m3 = select_next_model()
    assert m3 is not None
    
    cat = _load_catalog()
    failed_openrouter = next(m for m in cat["models"] if m["id"] == "failed-model")
    assert failed_openrouter["test_status"] == "failed"  # NOT reset - disabled provider excluded
    
    # But nvidia failed models should be reset (one selected -> in_progress, other untested)
    failed_nvidia_1 = next(m for m in cat["models"] if m["id"] == "model-1")
    failed_nvidia_2 = next(m for m in cat["models"] if m["id"] == "model-2")
    nvidia_statuses = {failed_nvidia_1["test_status"], failed_nvidia_2["test_status"]}
    assert nvidia_statuses == {"untested", "in_progress"}  # one reset, one selected"


# ----------------------------------------------------------------------
# Additional: logging never crashes on unknown provider
# ----------------------------------------------------------------------

def test_logging_unknown_provider(isolated_data_dir, mock_config, monkeypatch):
    """Logging with unknown provider must not KeyError."""
    config = mock_config({
        "unknown_provider": {"enabled": True, "models": [], "base_url": "", "api_key_env": ""},
    })
    
    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)
    
    catalog = _make_catalog([
        _make_model("unknown_provider", "model-1"),
    ])
    _save_catalog(catalog)
    
    # Should not raise
    model = select_next_model()
    assert model is not None
    
    # Record result should also not raise
    record_request_result(
        model_key=model["key"],
        input_chars=100,
        output_chars=50,
        success=True,
        ends_model_test=True,
    )


# ----------------------------------------------------------------------
# Test pointer synchronization
# ----------------------------------------------------------------------

def test_pointer_sync_after_selection(isolated_data_dir, mock_config, monkeypatch):
    """Both next_rotation_group and next_rotation_group_index must stay in sync."""
    config = mock_config({
        "nvidia": {"enabled": True, "models": [], "base_url": "", "api_key_env": ""},
        "openrouter": {"enabled": True, "models": [], "base_url": "", "api_key_env": ""},
    })
    
    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)
    
    catalog = _make_catalog([
        _make_model("nvidia", "model-1"),
        _make_model("openrouter", "model-2"),
    ])
    _save_catalog(catalog)
    
    # First selection (nvidia)
    m1 = select_next_model()
    state = _load_state()
    assert state["next_rotation_group"] == "openrouter"
    assert state["next_rotation_group_index"] == 1
    
    record_request_result(m1["key"], 100, 50, success=True, ends_model_test=True)
    
    # Second selection (openrouter)
    m2 = select_next_model()
    state = _load_state()
    assert state["next_rotation_group"] == "confirmed_models"
    assert state["next_rotation_group_index"] == 2
    
    record_request_result(m2["key"], 100, 50, success=True, ends_model_test=True)
    
    # Third selection starts a retry round and selects the first failed model.
    m3 = select_next_model()
    assert m3 is not None
    assert m3["id"] == "model-1"

    state = _load_state()
    assert state["next_rotation_group"] == "openrouter"
    assert state["next_rotation_group_index"] == 1


# ----------------------------------------------------------------------
# Test duplicate normalization
# ----------------------------------------------------------------------

def test_duplicate_normalization(isolated_data_dir, mock_config, monkeypatch):
    """Duplicate normalized names must be deduplicated preserving first."""
    config = mock_config({
        "nvidia_nim": {"enabled": True, "models": [], "base_url": "", "api_key_env": ""},
        "nvidia": {"enabled": True, "models": [], "base_url": "", "api_key_env": ""},
        "NVIDIA": {"enabled": True, "models": [], "base_url": "", "api_key_env": ""},
    })
    
    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)
    
    providers = _get_dynamic_provider_order()
    # Only first occurrence kept after normalization
    assert providers == ["nvidia"]


# ----------------------------------------------------------------------
# Test round_number and round_completed updates
# ----------------------------------------------------------------------

def test_round_number_increments_on_retry(isolated_data_dir, mock_config, monkeypatch):
    """Round number must increment on retry."""
    config = mock_config({
        "nvidia": {"enabled": True, "models": [], "base_url": "", "api_key_env": ""},
    })
    
    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)
    
    catalog = _make_catalog([
        _make_model("nvidia", "model-1"),
    ])
    _save_catalog(catalog)
    
    m1 = select_next_model()
    record_request_result(m1["key"], 100, 50, success=False, ends_model_test=True, error_type="test")
    
    # Next call should trigger retry round
    m2 = select_next_model()
    state = _load_state()
    assert state["round_number"] == 2
    assert state["round_total"] == 1
    assert state["round_completed"] == 0



# ----------------------------------------------------------------------
# Additional: removed-provider failures must not be reintroduced
# ----------------------------------------------------------------------

def test_removed_provider_failures_not_reintroduced(isolated_data_dir, mock_config, monkeypatch):
    """Failed models from removed (no-longer-in-config) providers must not be retried."""
    config = mock_config({
        "nvidia": {"enabled": True, "models": [], "base_url": "", "api_key_env": ""},
        "openrouter": {"enabled": True, "models": [], "base_url": "", "api_key_env": ""},
    })
    
    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)
    
    catalog = _make_catalog([
        _make_model("nvidia", "model-1"),
        _make_model("openrouter", "model-2"),
        # This provider was removed from config - its failed model must NOT be retried
        _make_model("token_router", "failed-removed-model", test_status="failed"),
    ])
    _save_catalog(catalog)
    
    # Exhaust nvidia
    m1 = select_next_model()
    record_request_result(m1["key"], 100, 50, success=False, ends_model_test=True, error_type="test")
    
    # Exhaust openrouter
    m2 = select_next_model()
    record_request_result(m2["key"], 100, 50, success=False, ends_model_test=True, error_type="test")
    
    # Retry round - token_router failed model must NOT be reset (provider removed from config)
    m3 = select_next_model()
    assert m3 is not None
    
    cat = _load_catalog()
    failed_removed = next(m for m in cat["models"] if m["id"] == "failed-removed-model")
    assert failed_removed["test_status"] == "failed"  # NOT reset - provider no longer in config
    
    # But nvidia and openrouter failed models should be reset
    failed_nvidia = next(m for m in cat["models"] if m["id"] == "model-1")
    failed_openrouter = next(m for m in cat["models"] if m["id"] == "model-2")
    nvidia_statuses = {
        failed_nvidia["test_status"],
        failed_openrouter["test_status"],
    }
    assert nvidia_statuses == {"untested", "in_progress"}


# ----------------------------------------------------------------------
# Additional: exactly one PTR event per pointer transition
# ----------------------------------------------------------------------

def test_single_ptr_event_per_transition(isolated_data_dir, mock_config, monkeypatch):
    """Each rotation pointer transition produces exactly one PTR log entry."""
    config = mock_config({
        "nvidia": {"enabled": True, "models": [], "base_url": "", "api_key_env": ""},
        "openrouter": {"enabled": True, "models": [], "base_url": "", "api_key_env": ""},
    })
    
    import app.model_rotation as mr
    monkeypatch.setattr(mr, "load_config", lambda: config)
    
    catalog = _make_catalog([
        _make_model("nvidia", "model-1"),
        _make_model("openrouter", "model-2"),
    ])
    _save_catalog(catalog)
    
    # Read initial log
    import os
    log_path = mr.DATA_DIR / "rotation.log"
    def read_log():
        if not log_path.exists():
            return []
        return log_path.read_text(encoding="utf-8").strip().split("\n")
    
    # First selection: nvidia -> openrouter (PTR event)
    m1 = select_next_model()
    record_request_result(m1["key"], 100, 50, success=True, ends_model_test=True)
    logs = read_log()
    ptr_lines = [l for l in logs if " | PTR | " in l]
    assert len(ptr_lines) == 1, f"Expected 1 PTR after first transition, got {len(ptr_lines)}: {ptr_lines}"
    assert "NVD" in ptr_lines[0]
    
    # Second selection: openrouter -> confirmed_models (PTR event)
    m2 = select_next_model()
    record_request_result(m2["key"], 100, 50, success=True, ends_model_test=True)
    logs = read_log()
    ptr_lines = [l for l in logs if " | PTR | " in l]
    assert len(ptr_lines) == 2, f"Expected 2 PTR total, got {len(ptr_lines)}: {ptr_lines}"
    assert "OPR" in ptr_lines[1]
    
    # Third selection starts a retry round and selects NVIDIA model-1 again.
    m3 = select_next_model()
    assert m3 is not None
    assert m3["id"] == "model-1"

    logs = read_log()
    ptr_lines = [l for l in logs if " | PTR | " in l]
    assert len(ptr_lines) == 3, f"Expected 3 PTR total after retry selection, got {len(ptr_lines)}: {ptr_lines}"
    assert "NVD" in ptr_lines[2]
    assert "0>1" in ptr_lines[2]
    
    # The same pointer transition may legitimately occur in different rounds.
    # Verify the chronological sequence instead of requiring unique details.
    transitions = [line.split(" | ")[-1] for line in ptr_lines]
    assert transitions == ["0>1", "1>2", "0>1"]
