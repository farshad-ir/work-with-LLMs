#!/usr/bin/env bash

set -uo pipefail

# Project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_ROOT/.env"

# Arguments
ENDPOINT="${1:-}"
MODEL="${2:-}"
KEY_NAME="${3:-}"
PROMPT="${4:-Reply with exactly: CONNECTION_OK}"

# Validate arguments
if [[ -z "$ENDPOINT" || -z "$MODEL" || -z "$KEY_NAME" ]]; then
    echo "Usage:"
    echo "  $0 <endpoint_url> <model_name> <key_env_name> [prompt]"
    exit 1
fi

# Load local key vault
if [[ ! -f "$ENV_FILE" ]]; then
    echo "ERROR: .env file not found: $ENV_FILE"
    exit 1
fi

set -a
source "$ENV_FILE"
set +a

# Read API key by variable name
API_KEY="${!KEY_NAME:-}"

if [[ -z "$API_KEY" ]]; then
    echo "ERROR: Key '$KEY_NAME' was not found or is empty in .env"
    exit 1
fi

# Prepare request JSON
REQUEST_FILE="$(mktemp)"
RESPONSE_FILE="$(mktemp)"

trap 'rm -f "$REQUEST_FILE" "$RESPONSE_FILE"' EXIT

export MODEL PROMPT

python - <<'PY' > "$REQUEST_FILE"
import json
import os

payload = {
    "model": os.environ["MODEL"],
    "messages": [
        {"role": "user", "content": os.environ["PROMPT"]}
    ],
    "stream": False
}

print(json.dumps(payload))
PY

echo "======================================"
echo "Provider connection test"
echo "======================================"
echo "Endpoint : $ENDPOINT"
echo "Model    : $MODEL"
echo "Key name : $KEY_NAME"
echo "--------------------------------------"
echo "Sending request..."

# Export key for curl
export TEST_API_KEY="$API_KEY"

# Build curl command
CURL_CMD=(
    curl
    --silent
    --show-error
    --connect-timeout 15
    --max-time 120
    --output "$RESPONSE_FILE"
    --write-out '%{http_code}'
    --request POST "$ENDPOINT"
    --header "Authorization: Bearer $TEST_API_KEY"
    --header "Content-Type: application/json"
    --data-binary "@$REQUEST_FILE"
)

echo
echo "========== CURL COMMAND =========="

printf '%q ' "${CURL_CMD[@]}"
echo
echo "=================================="

# Optional: show command without executing
if [[ "${5:-}" == "--show-only" ]]; then
    echo "SHOW ONLY: request was not executed."
    exit 0
fi

echo "Executing curl..."

HTTP_STATUS=$("${CURL_CMD[@]}")
CURL_EXIT=$?

unset TEST_API_KEY

echo
echo "======================================"

if [[ $CURL_EXIT -ne 0 ]]; then
    echo "CURL ERROR: exit code $CURL_EXIT"
    echo "HTTP status: ${HTTP_STATUS:-unavailable}"
else
    echo "HTTP STATUS: $HTTP_STATUS"
fi

echo "======================================"
echo "Response body:"
echo "--------------------------------------"

python -m json.tool "$RESPONSE_FILE" 2>/dev/null || cat "$RESPONSE_FILE"

echo
echo "======================================"

if [[ "$HTTP_STATUS" == "200" ]]; then
    echo "RESULT: SUCCESS"
else
    echo "RESULT: FAILED"
fi
