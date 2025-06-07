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

echo "session.screen0.toolbar.visible: false" > ~/.fluxbox/init  # Hide toolbar to avoid errors

echo "Starting Fluxbox window manager..."
fluxbox -log ~/.fluxbox/fb.log &  # Redirect logs to a file instead of the console

sleep 2

echo "Starting VNC server..."
x11vnc -display :99 -forever -nopw -bg -rfbport 5990 &

sleep 2

echo "Starting Tkinter application..."
exec python3 ui.py
