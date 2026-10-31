import json
import os
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_DIR / "config.json"
EXAMPLE_CONFIG_PATH = PROJECT_DIR / "config.example.json"
ENV_PATH = PROJECT_DIR / ".env"


def get_env_value(name: str) -> str:
    """Read a secret from the process environment or local .env file."""
    value = os.environ.get(name)
    if value:
        return value

    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, val = line.split("=", 1)
            if key.strip() == name:
                return val.strip().strip("\"'")

    return ""


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Missing {CONFIG_PATH.name}. Copy "
            f"{EXAMPLE_CONFIG_PATH.name} to {CONFIG_PATH.name} first."
        )

    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        config = json.load(file)

    if not isinstance(config, dict):
        raise ValueError("Configuration root must be a JSON object.")

    if not isinstance(config.get("providers"), dict):
        raise ValueError("'providers' must be a JSON object.")

    if not isinstance(config.get("routing"), dict):
        raise ValueError("'routing' must be a JSON object.")

    fallbacks = config["routing"].get("fallbacks", [])
    if not isinstance(fallbacks, list) or len(fallbacks) > 3:
        raise ValueError("At most three fallback models are supported.")

    for name, provider in config["providers"].items():
        if not isinstance(provider, dict):
            raise ValueError(f"Provider '{name}' must be a JSON object.")
        if not isinstance(provider.get("models", []), list):
            raise ValueError(f"Provider '{name}' models must be a JSON array.")

    return config


def save_config(config: dict[str, Any]) -> None:
    CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def get_public_config() -> dict[str, Any]:
    config = load_config()
    providers = {}

    for name, provider in config["providers"].items():
        models = provider.get("models", [])
        providers[name] = {
            "display_name": provider.get("display_name", name.replace("_", " ").title()),
            "base_url": provider.get("base_url", ""),
            "enabled": bool(provider.get("enabled", False)),
            "models": models,
            "model_count": len(models),
            "api_key_env": provider.get("api_key_env", ""),
        }

    return {
        "providers": providers,
        "routing": {
            "primary": config["routing"].get("primary"),
            "fallbacks": config["routing"].get("fallbacks", []),
        },
    }
