#!/bin/bash

APP_DIR="/home/yhkcinki/apps/work-with-LLMs"
UVICORN="/home/yhkcinki/virtualenv/apps/work-with-LLMs/3.12/bin/uvicorn"
PID_FILE="$APP_DIR/logs/uvicorn.pid"
LOG_FILE="$APP_DIR/logs/uvicorn.log"

mkdir -p "$APP_DIR/logs"
cd "$APP_DIR" || exit 1

echo "Stopping Gateway..."

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")

    if [[ "$PID" =~ ^[0-9]+$ ]] && kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        for i in {1..10}; do
            kill -0 "$PID" 2>/dev/null || break
            sleep 1
        done
    fi
fi

# Remove stale PID file.
rm -f "$PID_FILE"

echo "Starting Gateway..."

nohup "$UVICORN" app.main:app \
    --host 127.0.0.1 \
    --port 8088 \
    >> "$LOG_FILE" 2>&1 </dev/null &

echo $! > "$PID_FILE"

echo "Waiting for Gateway..."

for i in {1..15}; do
    if curl -fsS --max-time 2 http://127.0.0.1:8088/health; then
        echo
        echo "Gateway restarted successfully."
        exit 0
    fi
    sleep 1
done

echo "Gateway restart failed. Check $LOG_FILE"
exit 1
