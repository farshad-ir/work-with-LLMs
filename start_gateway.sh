#!/bin/bash

APP_DIR="/home/yhkcinki/apps/work-with-LLMs"
UVICORN="/home/yhkcinki/virtualenv/apps/work-with-LLMs/3.12/bin/uvicorn"
PID_FILE="$APP_DIR/logs/uvicorn.pid"
LOG_FILE="$APP_DIR/logs/uvicorn.log"
HEALTH_URL="http://127.0.0.1:8088/health"

mkdir -p "$APP_DIR/logs"
cd "$APP_DIR" || exit 1

# If the gateway is already healthy, do nothing.
if curl -fsS --max-time 3 "$HEALTH_URL" >/dev/null 2>&1; then
    exit 0
fi

# Stop an existing but unhealthy instance, only if it belongs to this app.
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if [[ "$PID" =~ ^[0-9]+$ ]] && kill -0 "$PID" 2>/dev/null; then
        CMDLINE=$(tr '\0' ' ' < "/proc/$PID/cmdline" 2>/dev/null)
        case "$CMDLINE" in
            *"$APP_DIR/app.main:app"*)
                kill "$PID"
                sleep 2
                kill -0 "$PID" 2>/dev/null && kill -9 "$PID"
                ;;
        esac
    fi
fi

# Uvicorn logging is disabled by default.
if [[ "${UVICORN_LOG_ENABLED:-false}" =~ ^(1|true|yes|on)$ ]]; then
    UVICORN_OUTPUT="$LOG_FILE"
else
    UVICORN_OUTPUT="/dev/null"
fi

# Start the gateway in the background.
nohup "$UVICORN" app.main:app \
    --host 127.0.0.1 \
    --port 8088 \
    >> "$UVICORN_OUTPUT" 2>&1 </dev/null &




echo $! > "$PID_FILE"

# Wait up to 10 seconds for the health endpoint.
for i in {1..10}; do
    if curl -fsS --max-time 2 "$HEALTH_URL" >/dev/null 2>&1; then
        exit 0
    fi
    sleep 1
done

echo "Gateway failed to become healthy. Check $LOG_FILE"
exit 1
