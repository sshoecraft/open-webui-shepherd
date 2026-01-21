#!/bin/bash

# Stop Open WebUI backend server

PREFIX="${PREFIX:-$HOME/.open-webui}"
OPENWEBUI_PORT="${OPENWEBUI_PORT:-5555}"

echo "Stopping Open WebUI..."

# Method 0: Stop systemd service if it exists
if systemctl list-units --type=service | grep -q open-webui.service; then
    echo "Stopping systemd service..."
    sudo systemctl stop open-webui.service 2>/dev/null || true
    sleep 1
fi

# Method 1: Kill any uvicorn open_webui processes with sudo
echo "Killing all uvicorn open_webui processes..."
sudo pkill -9 -f "uvicorn.*open_webui" 2>/dev/null || true
sleep 1

# Method 2: Kill anything on the port with sudo
echo "Killing any process on port $OPENWEBUI_PORT..."
sudo fuser -k $OPENWEBUI_PORT/tcp 2>/dev/null || true
sleep 1

# Method 3: Double-check with lsof
remaining=$(lsof -ti:$OPENWEBUI_PORT 2>/dev/null)
if [ ! -z "$remaining" ]; then
    echo "Force killing remaining processes on port: $remaining"
    sudo kill -9 $remaining 2>/dev/null || true
    sleep 1
fi

# Clean up PID file
rm -f "$PREFIX/tmp/openwebui.pid" 2>/dev/null

# Final verification
sleep 1
if lsof -i :$OPENWEBUI_PORT 2>/dev/null | grep -q LISTEN; then
    echo "ERROR: Port $OPENWEBUI_PORT still in use!"
    lsof -i :$OPENWEBUI_PORT
    exit 1
else
    echo "Port $OPENWEBUI_PORT is free"
fi

echo "Open WebUI stop complete"
exit 0
