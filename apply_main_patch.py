import re

path = "C:/Users/Rezvan/work/codex/work-with-LLMs/app/main.py"
content = open(path, encoding="utf-8").read()

# 1. Add imports for MT5 rotation functions
old_import = """from app.model_rotation import (
    select_next_model,
    record_request_result,
    get_rotation_status,
    _provider_key,
)"""

new_import = """from app.model_rotation import (
    select_next_model,
    record_request_result,
    get_rotation_status,
    _provider_key,
    select_next_model_mt5,
    record_request_result_mt5,
)"""

content = content.replace(old_import, new_import)

# 2. Update mt5_ingest function to route through MT5 rotation
old_ingest = """async def mt5_ingest(request: Request):
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Request body must be valid JSON.",
        )

    # Free-form explorer: print everything received
    if isinstance(data, dict):
        for key, value in data.items():
            print(f"\\n[ key ] {key}", flush=True)
            if isinstance(value, dict):
                print(json.dumps(value, ensure_ascii=False, indent=2), flush=True)
            elif isinstance(value, list):
                n = len(value)
                print(f"  [ array ] length={n}", flush=True)
                if n > 0:
                    print(f"  [ first ]", json.dumps(value[0], ensure_ascii=False, indent=2), flush=True)
                if n > 1:
                    print(f"  [ last ]", json.dumps(value[-1], ensure_ascii=False, indent=2), flush=True)
                if n > 2:
                    print(f"  [ ... {n-2} more items omitted ... ]", flush=True)
            else:
                print(f"  {value}", flush=True)
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2), flush=True)

    return {"success": True}"""

new_ingest = """async def mt5_ingest(request: Request):
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Request body must be valid JSON.",
        )

    # Free-form explorer: print everything received
    if isinstance(data, dict):
        for key, value in data.items():
            print(f"\\n[ key ] {key}", flush=True)
            if isinstance(value, dict):
                print(json.dumps(value, ensure_ascii=False, indent=2), flush=True)
            elif isinstance(value, list):
                n = len(value)
                print(f"  [ array ] length={n}", flush=True)
                if n > 0:
                    print(f"  [ first ]", json.dumps(value[0], ensure_ascii=False, indent=2), flush=True)
                if n > 1:
                    print(f"  [ last ]", json.dumps(value[-1], ensure_ascii=False, indent=2), flush=True)
                if n > 2:
                    print(f"  [ ... {n-2} more items omitted ... ]", flush=True)
            else:
                print(f"  {value}", flush=True)
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2), flush=True)

    # Route to MT5-specific rotation
    selected_model = select_next_model_mt5()
    if selected_model is None:
        print("[MT5-ROTATION] No MT5 model available", flush=True)
        return {"success": True, "mt5_rotation": "no_model_available"}

    model_key = selected_model.get("key") or f"{selected_model.get('provider')}:{selected_model.get('id')}"
    provider = selected_model.get("provider")
    
    print(f"[MT5-ROTATION] Selected model: {model_key} (Provider: {provider})", flush=True)

    # Record the request for MT5 rotation (simulated success for now)
    # In production, this would call the provider and record actual result
    input_chars = len(json.dumps(data))
    result = record_request_result_mt5(
        model_key=model_key,
        input_chars=input_chars,
        success=True,
        ends_model_test=False,
    )

    print(f"[MT5-ROTATION] Model {model_key} recorded: test_status={result.get('test_status')}, mt5_in_progress={result.get('mt5_in_progress')}", flush=True)

    return {
        "success": True,
        "mt5_rotation": {
            "model_key": model_key,
            "provider": provider,
            "test_status": result.get("test_status"),
            "mt5_in_progress": result.get("mt5_in_progress"),
            "next_available": True
        }
    }"""

if old_ingest in content:
    content = content.replace(old_ingest, new_ingest)
    print("Patched mt5_ingest function")
else:
    print("Could not find old_ingest string - trying alternative match")
    # Try with escaped newlines
    import re
    pattern = r'@app\.post\("/api/mt5/ingest"\)\s+async def mt5_ingest.*?return \{"success": True\}'
    replacement = '''@app.post("/api/mt5/ingest")
async def mt5_ingest(request: Request):
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Request body must be valid JSON.",
        )

    # Free-form explorer: print everything received
    if isinstance(data, dict):
        for key, value in data.items():
            print(f"\\n[ key ] {key}", flush=True)
            if isinstance(value, dict):
                print(json.dumps(value, ensure_ascii=False, indent=2), flush=True)
            elif isinstance(value, list):
                n = len(value)
                print(f"  [ array ] length={n}", flush=True)
                if n > 0:
                    print(f"  [ first ]", json.dumps(value[0], ensure_ascii=False, indent=2), flush=True)
                if n > 1:
                    print(f"  [ last ]", json.dumps(value[-1], ensure_ascii=False, indent=2), flush=True)
                if n > 2:
                    print(f"  [ ... {n-2} more items omitted ... ]", flush=True)
            else:
                print(f"  {value}", flush=True)
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2), flush=True)

    # Route to MT5-specific rotation
    selected_model = select_next_model_mt5()
    if selected_model is None:
        print("[MT5-ROTATION] No MT5 model available", flush=True)
        return {"success": True, "mt5_rotation": "no_model_available"}

    model_key = selected_model.get("key") or f"{selected_model.get('provider')}:{selected_model.get('id')}"
    provider = selected_model.get("provider")

    print(f"[MT5-ROTATION] Selected model: {model_key} (Provider: {provider})", flush=True)

    input_chars = len(json.dumps(data))
    result = record_request_result_mt5(
        model_key=model_key,
        input_chars=input_chars,
        success=True,
        ends_model_test=False,
    )

    print(f"[MT5-ROTATION] Model {model_key} recorded: test_status={result.get('test_status')}, mt5_in_progress={result.get('mt5_in_progress')}", flush=True)

    return {
        "success": True,
        "mt5_rotation": {
            "model_key": model_key,
            "provider": provider,
            "test_status": result.get("test_status"),
            "mt5_in_progress": result.get("mt5_in_progress"),
            "next_available": True
        }
    }'''

    content, count = re.subn(pattern, replacement, content, flags=re.DOTALL)
    if count > 0:
        print(f"Patched mt5_ingest via regex (replacements: {count})")
    else:
        print("Pattern not found")

open(path, "w", encoding="utf-8").write(content)
print("main.py patched")
