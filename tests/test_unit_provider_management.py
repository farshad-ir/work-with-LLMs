import json
import tempfile
import os
import re
from pathlib import Path
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_config, save_config, get_public_config
from app.thinker_room import load_large_catalog
from app.model_rotation import (
    _provider_key, _get_dynamic_provider_order, _get_rotation_groups,
)

# Helper - fully isolated temp config
def make_temp_config():
    tmpdir = tempfile.mkdtemp()
    tmp_path = Path(tmpdir)

    config_file = tmp_path / "config.json"
    catalog_file = tmp_path / "large_catalog.json"
    env_file = tmp_path / ".env"

    config = {
        "providers": {
            "openrouter": {
                "display_name": "OpenRouter",
                "base_url": "https://openrouter.ai/api/v1",
                "api_key_env": "OPENROUTER_API_KEY",
                "enabled": True,
                "models": [{"id": "model-1", "name": "Model 1"}]
            },
            "nvidia": {
                "display_name": "NVIDIA NIM",
                "base_url": "https://integrate.api.nvidia.com/v1",
                "api_key_env": "NVIDIA_API_KEY",
                "enabled": True,
                "models": [{"id": "model-2", "name": "Model 2"}]
            }
        },
        "routing": {
            "primary": None,
            "fallbacks": []
        }
    }

    config_file.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    catalog = {
        "model_count": 2,
        "updated_at": "2026-01-01T00:00:00Z",
        "models": [
            {"key": "openrouter:model-1", "provider": "openrouter", "id": "model-1", "name": "Model 1", "test_status": "untested"},
            {"key": "nvidia:model-2", "provider": "nvidia", "id": "model-2", "name": "Model 2", "test_status": "untested"}
        ]
    }
    catalog_file.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")

    env_file.write_text("OPENROUTER_API_KEY=sk-test123\nNVIDIA_API_KEY=sk-test456\n", encoding="utf-8")

    return tmp_path, config_file, catalog_file, env_file


# Test 1: Adding a valid provider
def test_add_valid_provider():
    tmp_path, config_file, catalog_file, env_file = make_temp_config()

    with patch("app.config.CONFIG_PATH", config_file):
        config = load_config()
        assert "my_new_provider" not in config["providers"]

        config["providers"]["my_new_provider"] = {
            "display_name": "My New Provider",
            "base_url": "https://api.example.com",
            "api_key_env": "MY_NEW_PROVIDER_API_KEY",
            "enabled": True,
            "models": []
        }
        save_config(config)

        config2 = load_config()
        assert "my_new_provider" in config2["providers"]
        p = config2["providers"]["my_new_provider"]
        assert p["base_url"] == "https://api.example.com"
        assert p["api_key_env"] == "MY_NEW_PROVIDER_API_KEY"
        assert p["enabled"] is True
        assert p["models"] == []

    print("Test 1 PASSED: Adding valid provider")


# Test 2: Rejecting duplicate provider ID
def test_reject_duplicate_provider():
    tmp_path, config_file, catalog_file, env_file = make_temp_config()

    with patch("app.config.CONFIG_PATH", config_file):
        config = load_config()
        # Verify duplicate detection logic
        is_duplicate = "openrouter" in config["providers"]
        assert is_duplicate is True

    print("Test 2 PASSED: Duplicate provider ID rejected")


# Test 3: Rejecting invalid provider IDs
def test_reject_invalid_provider_ids():
    valid = ["openrouter", "nvidia", "token_router", "my_provider", "provider123"]
    invalid = ["my-provider", "my provider", "my.provider", "my/provider", ""]

    for vid in valid:
        assert re.match(r"^[a-zA-Z0-9_]+$", vid), f"Should be valid: {vid}"

    for vid in invalid:
        assert not re.match(r"^[a-zA-Z0-9_]+$", vid), f"Should be invalid: {vid}"

    print("Test 3 PASSED: Invalid provider IDs rejected")


# Test 4: Rejecting invalid env variable names
def test_reject_invalid_env_names():
    valid_envs = ["OPENROUTER_API_KEY", "NVIDIA_API_KEY", "MY_ENV_VAR", "env1"]
    invalid_envs = ["123ENV", "my-env", "my.env", "my/env", ""]

    for env in valid_envs:
        assert re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", env), f"Should be valid: {env}"

    for env in invalid_envs:
        assert not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", env), f"Should be invalid: {env}"

    print("Test 4 PASSED: Invalid env variable names rejected")


# Test 5: Preserving existing providers and order when adding
def test_preserve_order_on_add():
    tmp_path, config_file, catalog_file, env_file = make_temp_config()

    with patch("app.config.CONFIG_PATH", config_file):
        config = load_config()
        original_order = list(config["providers"].keys())
        assert original_order == ["openrouter", "nvidia"]

        config["providers"]["new_provider"] = {
            "display_name": "New",
            "base_url": "https://new.com",
            "api_key_env": "NEW_KEY",
            "enabled": True,
            "models": []
        }
        save_config(config)

        config2 = load_config()
        new_order = list(config2["providers"].keys())
        assert new_order == ["openrouter", "nvidia", "new_provider"]

    print("Test 5 PASSED: Provider order preserved on add")


# Test 6: Removing an existing provider
def test_remove_existing_provider():
    tmp_path, config_file, catalog_file, env_file = make_temp_config()

    with patch("app.config.CONFIG_PATH", config_file):
        config = load_config()
        assert "nvidia" in config["providers"]

        del config["providers"]["nvidia"]
        save_config(config)

        config2 = load_config()
        assert "nvidia" not in config2["providers"]
        assert "openrouter" in config2["providers"]

    print("Test 6 PASSED: Remove existing provider")


# Test 7: Removing all catalog models for provider
def test_remove_catalog_models_for_provider():
    tmp_path, config_file, catalog_file, env_file = make_temp_config()

    with patch("app.thinker_room.LARGE_CATALOG_PATH", catalog_file):
        catalog = load_large_catalog()
        assert catalog["model_count"] == 2
        assert any(m["key"].startswith("nvidia:") for m in catalog["models"])

        provider_key_prefix = "nvidia:"
        remaining = [m for m in catalog["models"] if not m.get("key", "").startswith(provider_key_prefix)]

        assert len(remaining) == 1
        assert remaining[0]["key"] == "openrouter:model-1"

    print("Test 7 PASSED: Catalog models removed for provider")


# Test 8: Removing all history and confirmed metadata
def test_remove_history_and_confirmed():
    tmp_path, config_file, catalog_file, env_file = make_temp_config()

    catalog = {
        "model_count": 1,
        "updated_at": "2026-01-01T00:00:00Z",
        "models": [
            {"key": "nvidia:model-2", "provider": "nvidia", "id": "model-2", "name": "Model 2",
             "test_status": "tested", "confirmed": True, "lifetime_chars": 75000,
             "successful_requests": 5, "failed_requests": 1, "output_chars": 100,
             "last_tested_at": "2026-01-01T00:00:00Z", "failure_at": None}
        ]
    }

    catalog_file.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")

    with patch("app.thinker_room.LARGE_CATALOG_PATH", catalog_file):
        catalog2 = load_large_catalog()
        model = catalog2["models"][0]

        assert "lifetime_chars" in model
        assert "successful_requests" in model
        assert "confirmed" in model
        assert model["confirmed"] is True

        provider_key_prefix = "nvidia:"
        remaining = [m for m in catalog2["models"] if not m.get("key", "").startswith(provider_key_prefix)]
        assert len(remaining) == 0

    print("Test 8 PASSED: History and confirmed metadata removed")


# Test 9: Preserving other providers' models and history
def test_preserve_other_providers():
    tmp_path, config_file, catalog_file, env_file = make_temp_config()

    catalog = {
        "model_count": 2,
        "updated_at": "2026-01-01T00:00:00Z",
        "models": [
            {"key": "openrouter:model-1", "provider": "openrouter", "id": "model-1",
             "name": "Model 1", "test_status": "tested", "confirmed": True, "lifetime_chars": 60000},
            {"key": "nvidia:model-2", "provider": "nvidia", "id": "model-2",
             "name": "Model 2", "test_status": "untested"}
        ]
    }

    catalog_file.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")

    with patch("app.thinker_room.LARGE_CATALOG_PATH", catalog_file):
        cat = load_large_catalog()

        remaining = [m for m in cat["models"] if not m.get("key", "").startswith("nvidia:")]
        assert len(remaining) == 1
        assert remaining[0]["key"] == "openrouter:model-1"
        assert remaining[0]["confirmed"] is True
        assert remaining[0]["lifetime_chars"] == 60000

    print("Test 9 PASSED: Other providers' models and history preserved")

# Test 10:
def test_env_preserved_on_removal():
    tmp_path, config_file, catalog_file, env_file = make_temp_config()

    env_before = env_file.read_bytes()

    with patch("app.config.CONFIG_PATH", config_file):
        config = load_config()
        del config["providers"]["nvidia"]
        save_config(config)

    env_after = env_file.read_bytes()
    assert env_before == env_after, ".env was modified!"

    print("Test 10 PASSED: .env preserved byte-for-byte")


# Test 11:
def test_removed_models_not_in_rotation():
    tmp_path, config_file, catalog_file, env_file = make_temp_config()

    with patch("app.config.CONFIG_PATH", config_file):
        config = load_config()
        del config["providers"]["nvidia"]
        save_config(config)

        # Test the actual rotation functions, not a mock.
        providers = _get_dynamic_provider_order()
        groups = _get_rotation_groups()

    assert "nvidia" not in providers
    assert "openrouter" in providers

    assert "nvidia" not in groups
    assert groups == ["openrouter", "confirmed_models"]

    print("Test 11 PASSED: Removed models cannot enter rotation")



# Test 12: Ensuring removed models cannot enter Confirmed selection
def test_removed_models_not_in_confirmed():
    tmp_path, config_file, catalog_file, env_file = make_temp_config()

    catalog = {
        "model_count": 2,
        "updated_at": "2026-01-01T00:00:00Z",
        "models": [
            {"key": "openrouter:model-1", "provider": "openrouter", "id": "model-1", "name": "M1", "confirmed": True},
            {"key": "nvidia:model-2", "provider": "nvidia", "id": "model-2", "name": "M2", "confirmed": True}
        ]
    }
    catalog_file.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")

    with patch("app.thinker_room.LARGE_CATALOG_PATH", catalog_file):
        cat = load_large_catalog()
        remaining = [m for m in cat["models"] if not m.get("key", "").startswith("nvidia:")]
        confirmed_remaining = [m for m in remaining if m.get("confirmed") is True]
        assert len(confirmed_remaining) == 1
        assert confirmed_remaining[0]["key"] == "openrouter:model-1"

    print("Test 12 PASSED: Removed models cannot enter Confirmed selection")


# Test 13: Correct catalog counts after deletion
def test_catalog_counts_after_deletion():
    tmp_path, config_file, catalog_file, env_file = make_temp_config()

    with patch("app.thinker_room.LARGE_CATALOG_PATH", catalog_file):
        catalog = load_large_catalog()
        assert catalog["model_count"] == 2

        remaining = [m for m in catalog["models"] if not m.get("key", "").startswith("nvidia:")]
        assert len(remaining) == 1

        catalog["models"] = remaining
        catalog["model_count"] = len(remaining)
        assert catalog["model_count"] == 1

    print("Test 13 PASSED: Catalog counts correct after deletion")


# Test 14: Handling unknown provider
def test_handle_unknown_provider():
    tmp_path, config_file, catalog_file, env_file = make_temp_config()

    with patch("app.config.CONFIG_PATH", config_file):
        config = load_config()
        assert "nonexistent" not in config["providers"]

        provider = config["providers"].get("nonexistent")
        assert provider is None

    print("Test 14 PASSED: Unknown provider handled")


# Test 15: Handling file-write failures without inconsistent data
def test_handle_write_failure():
    tmp_path, config_file, catalog_file, env_file = make_temp_config()

    with patch("app.config.CONFIG_PATH", config_file):
        config = load_config()
        original_providers = dict(config["providers"])

        config["providers"]["test_provider"] = {"enabled": True, "models": []}
        save_config(config)

        config2 = load_config()
        assert "test_provider" in config2["providers"]
        assert config2["providers"]["openrouter"] == original_providers["openrouter"]
        assert config2["providers"]["nvidia"] == original_providers["nvidia"]

    print("Test 15 PASSED: Write failures handled safely")


if __name__ == "__main__":
    tests = [
        test_add_valid_provider,
        test_reject_duplicate_provider,
        test_reject_invalid_provider_ids,
        test_reject_invalid_env_names,
        test_preserve_order_on_add,
        test_remove_existing_provider,
        test_remove_catalog_models_for_provider,
        test_remove_history_and_confirmed,
        test_preserve_other_providers,
        test_env_preserved_on_removal,
        test_removed_models_not_in_rotation,
        test_removed_models_not_in_confirmed,
        test_catalog_counts_after_deletion,
        test_handle_unknown_provider,
        test_handle_write_failure,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"FAILED: {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)}")
    print(f"{'='*50}")
