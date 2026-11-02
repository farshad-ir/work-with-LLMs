import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

import httpx

from app.config import load_config, save_config
from app.thinker_room import rebuild_large_catalog


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"


def read_env(name):
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            if key.strip() == name:
                return value.strip().strip("\"'")
    return ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", required=True, help="Provider ID")
    parser.add_argument("--name", required=True, help="Display name")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--api-key-env", required=True)
    parser.add_argument("--models-url", help="Defaults to BASE_URL/models")
    parser.add_argument("--authenticated", action="store_true")
    args = parser.parse_args()

    config = load_config()
    models_url = args.models_url or args.base_url.rstrip("/") + "/models"

    headers = {}
    if args.authenticated:
        api_key = read_env(args.api_key_env)
        if not api_key:
            raise SystemExit(f"Missing {args.api_key_env} in .env")
        headers["Authorization"] = f"Bearer {api_key}"

    response = httpx.get(models_url, headers=headers, timeout=40)
    response.raise_for_status()

    payload = response.json()
    items = payload.get("data", []) if isinstance(payload, dict) else payload

    if not isinstance(items, list):
        raise SystemExit("Unexpected models response: expected a list.")

    models = []
    seen = set()

    for item in items:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if not isinstance(model_id, str) or not model_id.strip():
            continue
        model_id = model_id.strip()
        if model_id not in seen:
            seen.add(model_id)
            models.append({
                "id": model_id,
                "name": item.get("name") or model_id,
            })

    if not models:
        raise SystemExit("No models found. Configuration was not changed.")

    backup = CONFIG_PATH.with_name(
        f"config.json.{datetime.now():%Y%m%d-%H%M%S}.bak"
    )
    shutil.copy2(CONFIG_PATH, backup)

    config["providers"][args.id] = {
        "display_name": args.name,
        "base_url": args.base_url.rstrip("/"),
        "api_key_env": args.api_key_env,
        "enabled": True,
        "models": models,
    }

    save_config(config)
    catalog = rebuild_large_catalog(config)

    print(f"Provider added: {args.name}")
    print(f"Models loaded: {len(models)}")
    print(f"Total catalog models: {catalog['model_count']}")
    print(f"Backup: {backup.name}")


if __name__ == "__main__":
    main()
