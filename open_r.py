from curl_cffi import requests

URL = "https://openrouter.ai/api/v1/models"

try:
    response = requests.get(
        URL,
        impersonate="chrome",
        timeout=30,
        headers={"Accept": "application/json"},
    )

    print("HTTP Status:", response.status_code)

    if response.status_code != 200:
        print("Response:", response.text[:500])
        print("Server:", response.headers.get("server"))
        print("CF-Ray:", response.headers.get("cf-ray"))
        raise SystemExit(1)

    result = response.json()
    models = result.get("data")

    if not isinstance(models, list):
        raise SystemExit("ERROR: Unexpected API response format")

    print("Total models:", len(models))

except requests.RequestsError as error:
    print("Connection error:", error)
    raise SystemExit(1)
