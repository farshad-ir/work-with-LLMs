from fastapi.testclient import TestClient
import app.main as main
import asyncio
import pytest
import httpx

from unittest.mock import patch

from app.main import (
    _validate_discovery_spec,
    _extract_discovered_models,
    _discover_provider_models,
)


@pytest.fixture
def provider_spec():
    return {
        "provider_id": "test_provider",
        "display_name": "Test Provider",
        "base_url": "https://api.example.com/v1",
        "api_key_env": "TEST_API_KEY",
        "enabled": True,
        "authentication": {
            "mode": "bearer",
            "header_name": "Authorization",
        },
        "discovery": {
            "public": {
                "enabled": True,
                "path": "/models",
            },
            "authenticated": {
                "enabled": True,
                "path": "/models",
            },
        },
        "response_parser": {
            "models_key": "data",
            "id_field": "id",
            "name_field": "name",
        },
    }


def test_validate_provider_discovery_spec(provider_spec):
    normalized = _validate_discovery_spec(provider_spec)

    assert normalized["provider_id"] == "test_provider"
    assert normalized["discovery"]["public"]["enabled"] is True
    assert normalized["discovery"]["authenticated"]["enabled"] is True


def test_public_discovery_can_work_without_api_key(provider_spec):
    provider_spec["api_key_env"] = ""
    provider_spec["discovery"]["authenticated"]["enabled"] = False

    normalized = _validate_discovery_spec(provider_spec)

    assert normalized["api_key_env"] == ""
    assert normalized["discovery"]["public"]["enabled"] is True


def test_extract_models_and_remove_duplicate_ids():
    payload = {
        "data": [
            {"id": "model-a", "name": "Model A"},
            {"id": "model-b", "name": "Model B"},
            {"id": "model-a", "name": "Duplicate Model A"},
            {"name": "Missing ID"},
        ]
    }

    models = _extract_discovered_models(
        payload,
        {
            "models_key": "data",
            "id_field": "id",
            "name_field": "name",
        },
    )

    assert models == [
        {"id": "model-a", "name": "Model A"},
        {"id": "model-b", "name": "Model B"},
    ]


def test_extract_models_from_nested_response():
    payload = {
        "result": {
            "models": [
                {"model_id": "model-x", "title": "Model X"},
            ]
        }
    }

    models = _extract_discovered_models(
        payload,
        {
            "models_key": "result.models",
            "id_field": "model_id",
            "name_field": "title",
        },
    )

    assert models == [{"id": "model-x", "name": "Model X"}]


def test_reject_invalid_discovery_path(provider_spec):
    provider_spec["discovery"]["public"]["path"] = "models"

    with pytest.raises(ValueError):
        _validate_discovery_spec(provider_spec)


def test_reject_provider_without_enabled_routes(provider_spec):
    provider_spec["discovery"]["public"]["enabled"] = False
    provider_spec["discovery"]["authenticated"]["enabled"] = False

    with pytest.raises(ValueError):
        _validate_discovery_spec(provider_spec)


def test_public_and_authenticated_discovery(provider_spec, monkeypatch):
    monkeypatch.setattr(
        "app.main.get_env_value",
        lambda name: "test-secret",
    )

    calls = []

    async def mock_get(self, url, headers=None):
        calls.append((url, headers or {}))

        if len(calls) == 1:
            payload = {
                "data": [
                    {"id": "model-a", "name": "Model A"},
                    {"id": "model-b", "name": "Model B"},
                ]
            }
        else:
            payload = {
                "data": [
                    {"id": "model-b", "name": "Model B"},
                    {"id": "model-c", "name": "Model C"},
                ]
            }

        return httpx.Response(
            200,
            json=payload,
            request=httpx.Request("GET", url),
        )

    with patch("app.main.httpx.AsyncClient.get", new=mock_get):
        result = asyncio.run(
            _discover_provider_models(provider_spec)
        )

    assert result["routes"]["public"]["success"] is True
    assert result["routes"]["authenticated"]["success"] is True

    assert result["routes"]["public"]["model_count"] == 2
    assert result["routes"]["authenticated"]["model_count"] == 2

    assert result["unique_model_count"] == 3
    assert {m["id"] for m in result["models"]} == {
        "model-a", "model-b", "model-c"
    }

    assert calls[0][1] == {}
    assert calls[1][1]["Authorization"] == "Bearer test-secret"

    assert "test-secret" not in str(result)


def test_public_success_when_authenticated_fails(provider_spec, monkeypatch):
    monkeypatch.setattr(
        "app.main.get_env_value",
        lambda name: "test-secret",
    )

    async def mock_get(self, url, headers=None):
        if not headers:
            return httpx.Response(
                200,
                json={"data": [{"id": "public-model"}]},
                request=httpx.Request("GET", url),
            )

        return httpx.Response(
            403,
            request=httpx.Request("GET", url),
        )

    with patch("app.main.httpx.AsyncClient.get", new=mock_get):
        result = asyncio.run(
            _discover_provider_models(provider_spec)
        )

    assert result["routes"]["public"]["success"] is True
    assert result["routes"]["authenticated"]["success"] is False
    assert result["unique_model_count"] == 1
    assert result["can_add"] is True


def test_no_valid_models_means_cannot_add(provider_spec, monkeypatch):
    monkeypatch.setattr(
        "app.main.get_env_value",
        lambda name: "test-secret",
    )

    async def mock_get(self, url, headers=None):
        return httpx.Response(
            200,
            json={"data": []},
            request=httpx.Request("GET", url),
        )

    with patch("app.main.httpx.AsyncClient.get", new=mock_get):
        result = asyncio.run(
            _discover_provider_models(provider_spec)
        )

    assert result["unique_model_count"] == 0
    assert result["can_add"] is False

def test_add_provider_rediscovers_models_on_server(
    provider_spec,
    monkeypatch,
):
    config = {
        "providers": {},
        "routing": {
            "primary": None,
            "fallbacks": [],
        },
    }

    saved_configs = []
    discovery_calls = []

    async def mock_discover(spec):
        discovery_calls.append(spec)
        return {
            "models": [
                {"id": "server-model-a", "name": "Server Model A"},
                {"id": "server-model-b", "name": "Server Model B"},
            ],
            "unique_model_count": 2,
            "can_add": True,
        }

    monkeypatch.setattr(main, "load_config", lambda: config)
    monkeypatch.setattr(
        main,
        "save_config",
        lambda value: saved_configs.append(value.copy()),
    )
    monkeypatch.setattr(
        main,
        "_discover_provider_models",
        mock_discover,
    )
    monkeypatch.setattr(
        main,
        "rebuild_large_catalog",
        lambda value: {
            "model_count": 2,
            "updated_at": "test-timestamp",
        },
    )

    # مدل‌های جعلی مرورگر نباید در config ذخیره شوند.
    request_body = {
        **provider_spec,
        "models": [
            {"id": "browser-fake-model", "name": "Fake Model"},
        ],
    }

    client = TestClient(main.app)
    response = client.post("/api/providers", json=request_body)

    assert response.status_code == 200
    assert response.json()["success"] is True

    assert len(discovery_calls) == 1
    assert len(saved_configs) == 1

    saved_provider = config["providers"]["test_provider"]

    assert saved_provider["models"] == [
        {"id": "server-model-a", "name": "Server Model A"},
        {"id": "server-model-b", "name": "Server Model B"},
    ]

    assert all(
        model["id"] != "browser-fake-model"
        for model in saved_provider["models"]
    )

    assert response.json()["provider"]["model_count"] == 2
    assert response.json()["large_catalog_count"] == 2


def test_add_provider_rejects_empty_discovery_result(
    provider_spec,
    monkeypatch,
):
    config = {
        "providers": {},
        "routing": {
            "primary": None,
            "fallbacks": [],
        },
    }

    saved_configs = []
    catalog_calls = []

    async def mock_discover(spec):
        return {
            "models": [],
            "unique_model_count": 0,
            "can_add": False,
        }

    monkeypatch.setattr(main, "load_config", lambda: config)
    monkeypatch.setattr(
        main,
        "save_config",
        lambda value: saved_configs.append(value),
    )
    monkeypatch.setattr(
        main,
        "_discover_provider_models",
        mock_discover,
    )
    monkeypatch.setattr(
        main,
        "rebuild_large_catalog",
        lambda value: catalog_calls.append(value),
    )

    client = TestClient(main.app)
    response = client.post(
        "/api/providers",
        json=provider_spec,
    )

    assert response.status_code == 400
    assert "no valid models" in response.json()["detail"].lower()

    assert "test_provider" not in config["providers"]
    assert saved_configs == []
    assert catalog_calls == []


def test_add_provider_rejects_duplicate_provider(
    provider_spec,
    monkeypatch,
):
    config = {
        "providers": {
            "test_provider": {
                "display_name": "Existing Provider",
                "models": [],
            },
        },
        "routing": {
            "primary": None,
            "fallbacks": [],
        },
    }

    discovery_calls = []
    saved_configs = []

    async def mock_discover(spec):
        discovery_calls.append(spec)
        return {"models": []}

    monkeypatch.setattr(main, "load_config", lambda: config)
    monkeypatch.setattr(
        main,
        "save_config",
        lambda value: saved_configs.append(value),
    )
    monkeypatch.setattr(
        main,
        "_discover_provider_models",
        mock_discover,
    )

    client = TestClient(main.app)
    response = client.post(
        "/api/providers",
        json=provider_spec,
    )

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"].lower()

    assert discovery_calls == []
    assert saved_configs == []
