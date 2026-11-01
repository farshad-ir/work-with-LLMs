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
