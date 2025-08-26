#!/bin/bash
set -e

# Update repo at runtime
if [ ! -d /app/.git ]; then
    git clone https://github.com/Ircama/epson_print_conf.git /app
else
    cd /app && git pull
fi

echo "Starting Xvfb virtual display..."
Xvfb :99 -screen 0 1280x800x24 &

sleep 2

echo "Creating minimal Fluxbox config..."
mkdir -p ~/.fluxbox

# Create minimal init file
cat > ~/.fluxbox/init <<'EOF'
# Minimal Fluxbox config for Docker/Xvfb
session.screen0.toolbar.visible: false
session.screen0.slit.placement: BottomRight
session.screen0.slit.direction: Horizontal
session.screen0.fullMaximization: true
session.screen0.workspaces: 1
session.screen0.focusModel: sloppy
session.keyFile: ~/.fluxbox/keys
session.appsFile: ~/.fluxbox/apps
EOF

echo "Starting Fluxbox window manager..."
fluxbox -log ~/.fluxbox/fb.log 2>&1 &  # Redirect logs to a file instead of the console

sleep 2

echo "Starting VNC server..."
x11vnc -display :99 -forever -nopw -bg -rfbport 5990 -ncache 10 -ncache_cr &

sleep 2

echo "Starting Tkinter application. Open your VNC client and connect to localhost:90..."
exec python3 ui.py
