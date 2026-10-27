import csv
import time
import httpx

from app.config import get_env_value, load_config

config = load_config()
provider = config["providers"]["openrouter"]

base_url = provider["base_url"].rstrip("/")
key_name = provider.get("api_key_env", "OPENROUTER_API_KEY")
api_key = get_env_value(key_name)

if not api_key:
    raise SystemExit("ERROR: OpenRouter API key is missing.")

models = provider.get("models", [])

if not models:
    raise SystemExit("ERROR: No models found in config.json.")

results = []
successes = []

print(f"Testing {len(models)} models sequentially.")
print("API key will not be displayed.")
print("-" * 60)

with httpx.Client(timeout=35.0) as client:
    for index, model in enumerate(models, start=1):
        model_id = model["id"]

        try:
            response = client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model_id,
                    "messages": [
                        {
                            "role": "user",
                            "content": "Reply with exactly OK",
                        }
                    ],
                    "max_tokens": 2,
                    "stream": False,
                },
            )

            status_code = response.status_code
            detail = ""

            try:
                data = response.json()
            except ValueError:
                data = {}

            if (
                response.is_success
                and isinstance(data, dict)
                and isinstance(data.get("choices"), list)
                and len(data["choices"]) > 0
            ):
                status = "SUCCESS"
                successes.append(model_id)
                print(f"[{index}/{len(models)}] SUCCESS: {model_id}")

            else:
                status = "FAILED"

                if isinstance(data, dict):
                    error = data.get("error", data.get("detail", ""))
                    if isinstance(error, dict):
                        detail = error.get("message", str(error))
                    else:
                        detail = str(error)
                else:
                    detail = response.text[:180]

                detail = detail.replace("\n", " ")[:180]

                print(
                    f"[{index}/{len(models)}] "
                    f"HTTP {status_code}: {model_id} | {detail}"
                )

            results.append({
                "model": model_id,
                "status": status,
                "http_status": status_code,
                "detail": detail,
            })

        except httpx.HTTPError as exc:
            detail = f"{type(exc).__name__}: {str(exc)[:140]}"
            results.append({
                "model": model_id,
                "status": "CONNECTION_ERROR",
                "http_status": "",
                "detail": detail,
            })
            print(f"[{index}/{len(models)}] CONNECTION ERROR: {model_id}")

        # Reduce the request rate.
        time.sleep(1)

with open(
    "model_test_results.csv",
    "w",
    newline="",
    encoding="utf-8",
) as file:
    writer = csv.DictWriter(
        file,
        fieldnames=["model", "status", "http_status", "detail"],
    )
    writer.writeheader()
    writer.writerows(results)

with open("working_models.txt", "w", encoding="utf-8") as file:
    file.write("\n".join(successes))
    if successes:
        file.write("\n")

print("\n" + "=" * 60)
print(f"Total models tested: {len(models)}")
print(f"Successful models: {len(successes)}")
print(f"Failed/connection errors: {len(results) - len(successes)}")
print("Full report: model_test_results.csv")
print("Successful model IDs: working_models.txt")

if successes:
    print("\nSuccessful models:")
    for model_id in successes:
        print(model_id)
elif results and all(
    r["http_status"] == 403
    and "security policy" in r["detail"].lower()
    for r in results
):
    print("\nAll models received the same security-policy 403.")
    print("This points to an access/security issue, not model selection.")
