#!/bin/bash

# Restart Open WebUI backend server

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PREFIX="${PREFIX:-$HOME/.open-webui}"
OPENWEBUI_PORT="${OPENWEBUI_PORT:-8080}"

echo "Restarting Open WebUI..."

# Stop
"$SCRIPT_DIR/stop_openwebui.sh"

# Wait a moment
sleep 2

# Start
"$SCRIPT_DIR/start_openwebui.sh"

# Wait for startup
echo "Waiting for Open WebUI to be ready..."
MAX_ATTEMPTS=30
ATTEMPT=0
while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    if curl -s "http://127.0.0.1:$OPENWEBUI_PORT/health" | grep -q "true"; then
        echo "Open WebUI is ready!"
        exit 0
    fi
    ATTEMPT=$((ATTEMPT + 1))
    sleep 1
done

echo "ERROR: Open WebUI failed to start within timeout"
echo "Check logs: $PREFIX/logs/openwebui.log"
tail -20 "$PREFIX/logs/openwebui.log"
exit 1
