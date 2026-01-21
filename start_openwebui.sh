#!/bin/bash

# Start Open WebUI backend server

PREFIX="${PREFIX:-$HOME/.open-webui}"
OPENWEBUI_PORT="${OPENWEBUI_PORT:-5555}"
OPENWEBUI_HOST="${OPENWEBUI_HOST:-0.0.0.0}"
VENV_PATH="${VENV_PATH:-$HOME/venvs/open-webui}"

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Ensure directories exist
mkdir -p "$PREFIX/logs"
mkdir -p "$PREFIX/tmp"

cd "$SCRIPT_DIR/backend" || exit 1

# Set environment variables
export PYTHONUNBUFFERED=1
export PYTHONPYCACHEPREFIX="$PREFIX/tmp/__pycache__"
export DATA_DIR="$PREFIX"

# Activate venv
source "$VENV_PATH/bin/activate"

# Start server in background
python3 -m uvicorn open_webui.main:app \
    --host "$OPENWEBUI_HOST" \
    --port "$OPENWEBUI_PORT" \
    --forwarded-allow-ips '*' \
    > "$PREFIX/logs/openwebui.log" 2>&1 &

# Save PID for reliable shutdown
OPENWEBUI_PID=$!
echo $OPENWEBUI_PID > "$PREFIX/tmp/openwebui.pid"
echo "Open WebUI started with PID: $OPENWEBUI_PID"
echo "Logs: $PREFIX/logs/openwebui.log"
