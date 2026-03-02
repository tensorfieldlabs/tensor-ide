#!/bin/bash
# Quick headless Chrome screenshot of the dev server
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless=new --screenshot=/tmp/ide_screenshot.png \
  --window-size=${1:-1400},${2:-900} --disable-gpu --no-sandbox \
  http://localhost:5173/ 2>/dev/null
echo "Screenshot saved to /tmp/ide_screenshot.png"
