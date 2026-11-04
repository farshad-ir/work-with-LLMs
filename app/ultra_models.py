"""
Ultra Model Registry

A curated collection of models tested through NVIDIA NIM.

Ultra is a logical model interface, not a separate upstream provider.
All models use the NVIDIA NIM transport and credentials.
"""

import json
from copy import deepcopy


# ---------------------------------------------------------
# Ultra model registry (JSON)
# ---------------------------------------------------------

ULTRA_MODELS_JSON = r"""
[
    {
        "id": "google/diffusiongemma-26b-a4b-it",
        "enabled": true,
        "status": "confirmed"
    },
    {
        "id": "meta/llama-3.2-90b-vision-instruct",
        "enabled": true,
        "status": "confirmed"
    },
    {
        "id": "meta/llama-guard-4-12b",
        "enabled": true,
        "status": "confirmed"
    },
    {
        "id": "meta/muse-glimmer-30b",
        "enabled": true,
        "status": "confirmed"
    },
    {
        "id": "minimaxai/minimax-m3.1-flash",
        "enabled": true,
        "status": "confirmed"
    },
    {
        "id": "mistralai/mistral-large-4-1t-a52b",
        "enabled": true,
        "status": "confirmed"
    },
    {
        "id": "nvidia/ising-calibration-1.5-31b",
        "enabled": true,
        "status": "confirmed"
    },
    {
        "id": "nvidia/llama-3.1-nemotron-safety-guard-8b-v3",
        "enabled": true,
        "status": "confirmed"
    },
    {
        "id": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
        "enabled": true,
        "status": "confirmed"
    },
    {
        "id": "nvidia/nemotron-3-ultra-550b-a55b",
        "enabled": true,
        "status": "confirmed"
    },
    {
        "id": "nvidia/nemotron-3.5-bolt-e4b",
        "enabled": true,
        "status": "confirmed"
    },
    {
        "id": "nvidia/nemotron-3.5-lightning-30b-a3b",
        "enabled": true,
        "status": "confirmed"
    },
    {
        "id": "nvidia/nemotron-3.5-super-vl-120b-a12b",
        "enabled": true,
        "status": "confirmed"
    },
    {
        "id": "nvidia/nemotron-parse-2.0",
        "enabled": true,
        "status": "confirmed"
    },
    {
        "id": "nvidia/riva-translate-4b-instruct-v2",
        "enabled": true,
        "status": "confirmed"
    },
    {
        "id": "poolside/laguna-xs-2.1",
        "enabled": true,
        "status": "confirmed"
    }
]
"""


# ---------------------------------------------------------
# Load and validate registry
# ---------------------------------------------------------

ULTRA_MODELS = json.loads(ULTRA_MODELS_JSON)

ULTRA_INTERFACE = "ultra"
ULTRA_TRANSPORT_PROVIDER = "nvidia"


def _validate_registry():
    model_ids = [model["id"] for model in ULTRA_MODELS]

    if len(model_ids) != len(set(model_ids)):
        raise ValueError("Duplicate model IDs found in Ultra registry")

    for model in ULTRA_MODELS:
        if not model.get("id"):
            raise ValueError("Ultra model has no ID")

        if model.get("status") != "confirmed":
            raise ValueError(
                f"Unexpected status for Ultra model: {model['id']}"
            )


_validate_registry()


# ---------------------------------------------------------
# Public API
# ---------------------------------------------------------

def get_ultra_models(enabled_only=True):
    """
    Return Ultra models.

    Results are copied so callers cannot accidentally
    modify the internal registry.
    """
    models = ULTRA_MODELS

    if enabled_only:
        models = [
            model for model in models
            if model.get("enabled", False)
        ]

    return deepcopy(models)


def get_ultra_model(model_id):
    """
    Find an Ultra model by its original upstream ID.

    Accepts:
        nvidia/nemotron-3-ultra-550b-a55b
        ultra:nvidia/nemotron-3-ultra-550b-a55b
    """
    model_id = normalize_ultra_model_id(model_id)

    for model in ULTRA_MODELS:
        if model["id"] == model_id:
            return deepcopy(model)

    return None


def normalize_ultra_model_id(model_id):
    """
    Remove the internal Ultra prefix, if present.
    """
    if not isinstance(model_id, str):
        return model_id

    prefix = f"{ULTRA_INTERFACE}:"

    if model_id.startswith(prefix):
        return model_id[len(prefix):]

    return model_id


def make_ultra_model_key(model_id):
    """
    Build the internal Gateway key.

    Example:
        ultra:nvidia/nemotron-3-ultra-550b-a55b
    """
    model_id = normalize_ultra_model_id(model_id)

    if get_ultra_model(model_id) is None:
        raise ValueError(f"Unknown Ultra model: {model_id}")

    return f"{ULTRA_INTERFACE}:{model_id}"


def is_ultra_model(model_id):
    """
    Check whether a model belongs to the Ultra registry.
    """
    return get_ultra_model(model_id) is not None


def get_ultra_model_count(enabled_only=True):
    return len(get_ultra_models(enabled_only=enabled_only))

