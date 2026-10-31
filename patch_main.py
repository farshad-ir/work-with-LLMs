with open("app/main.py", "r") as f:
    content = f.read()

# Add the new imports and endpoints after the existing providers endpoint
old = """@app.get("/api/providers")
async def providers():
    return get_public_config()["providers"]



@app.get("/api/thinker-room/catalog")"""

new = """@app.get("/api/providers")
async def providers():
    return get_public_config()["providers"]


@app.post("/api/providers")
async def add_provider(
    provider_id: str = None,
    display_name: str = None,
    base_url: str = None,
    api_key_env: str = None,
    enabled: bool = True,
):
    \"\"\"Add a new provider to the configuration.\"\"\"
    # Get request body
    import json
    try:
        raw_body = await Request._scope.get("body") if hasattr(Request, "_scope") else b"{}"
    except:
        from fastapi import Form
        # Fallback: use form data or body parsing
        pass
    
    # Simpler approach: accept query/body parameters
    
    if not provider_id:
        raise HTTPException(status_code=400, detail="provider_id is required")
    
    provider_id = str(provider_id).strip()
    if not provider_id:
        raise HTTPException(status_code=400, detail="provider_id cannot be empty")
    
    if not re.match(r"^[a-zA-Z0-9_]+$", provider_id):
        raise HTTPException(
            status_code=400,
            detail="provider_id must contain only alphanumeric characters and underscores",
        )
    
    display_name = str(display_name or "").strip()
    if not display_name:
        display_name = provider_id.replace("_", " ").title()
    
    base_url = str(base_url or "").strip().rstrip("/")
    if not base_url:
        raise HTTPException(status_code=400, detail="base_url is required")
    
    if not base_url.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=400,
            detail="base_url must be a valid HTTP or HTTPS URL",
        )
    
    api_key_env = str(api_key_env or "").strip()
    if not api_key_env:
        raise HTTPException(status_code=400, detail="api_key_env is required")
    
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", api_key_env):
        raise HTTPException(
            status_code=400,
            detail="api_key_env must be a valid environment variable name",
        )
    
    config = load_config()
    
    if provider_id in config["providers"]:
        raise HTTPException(
            status_code=409,
            detail=f"Provider '{provider_id}' already exists",
        )
    
    config["providers"][provider_id] = {
        "display_name": display_name,
        "base_url": base_url,
        "api_key_env": api_key_env,
        "enabled": bool(enabled),
        "models": [],
    }
    
    save_config(config)
    
    return {
        "success": True,
        "provider": {
            "id": provider_id,
            "display_name": display_name,
            "base_url": base_url,
            "api_key_env": api_key_env,
            "enabled": bool(enabled),
            "model_count": 0,
        },
    }


@app.delete("/api/providers/{provider_name}")
async def remove_provider(provider_name: str):
    \"\"\"Remove a provider and all its associated data.\"\"\"
    import re
    
    config = load_config()
    
    if provider_name not in config["providers"]:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_name}' not found")
    
    provider_config = config["providers"][provider_name]
    models_to_remove = [
        str(m.get("id", "")).strip()
        for m in provider_config.get("models", [])
        if m and isinstance(m, dict)
    ]
    
    # Remove provider from config
    del config["providers"][provider_name]
    save_config(config)
    
    # Remove models from large catalog
    catalog_path = Path(__file__).resolve().parent.parent / "data" / "large_catalog.json"
    
    if catalog_path.exists():
        try:
            with catalog_path.open("r", encoding="utf-8") as f:
                catalog = json.load(f)
        except (json.JSONDecodeError, OSError):
            catalog = {"model_count": 0, "updated_at": None, "models": []}
        
        original_count = len(catalog.get("models", []))
        original_model_keys = set()
        for m in catalog.get("models", []):
            key = m.get("key", "")
            if key:
                original_model_keys.add(key)
        
        # Remove models belonging to this provider
        provider_key_prefix = _normalize_provider_name(provider_name) + ":"
        
        remaining_models = []
        for m in catalog.get("models", []):
            key = m.get("key", "")
            if key and not key.startswith(provider_key_prefix):
                remaining_models.append(m)
        
        # Preserve only non-provider-specific fields for remaining models
        preserved_fields = set()
        for m in remaining_models:
            for k in m.keys():
                preserved_fields.add(k)
        
        for m in remaining_models:
            if "provider" not in m:
                m["provider"] = _normalize_provider_name_from_key(m.get("key", ""))
        
        catalog["models"] = remaining_models
        catalog["model_count"] = len(remaining_models)
        catalog["updated_at"] = datetime.now(timezone.utc).isoformat()
        
        with catalog_path.open("w", encoding="utf-8") as f:
            json.dump(catalog, f, ensure_ascii=False, indent=2)
            f.write("\\n")
    
    return {
        "success": True,
        "removed_provider": provider_name,
        "removed_model_count": len(models_to_remove),
    }


@app.get("/api/thinker-room/catalog")"""

# The replacement is too complex for inline, so let me write it differently
print("Patch size too large, will write to file directly")
