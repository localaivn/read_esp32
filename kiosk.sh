#!/bin/bash

# Kiosk launcher for Chromium on Orange Pi / Raspberry Pi
# This script opens the web dashboard at http://127.0.0.1:8080 in full-screen kiosk mode.

export DISPLAY=:0
export XAUTHORITY=/home/orangepi/.Xauthority

# Disable screen saver / blanking when running on a desktop session
xset -dpms || true
xset s off || true
xset s noblank || true

# Hide mouse cursor after inactivity
unclutter -idle 0 >/dev/null 2>&1 &

# Ensure HDMI output is enabled if present
xrandr --output HDMI-1 --auto >/dev/null 2>&1 || true

while true; do
  chromium \
    --kiosk \
    --disable-dev-shm-usage \
    --no-sandbox \
    --private-window \
    http://127.0.0.1:8080

  echo "Chromium exited. Restarting in 2 seconds..."
  sleep 2
done
