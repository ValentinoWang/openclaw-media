#!/bin/bash
# Start Chrome with remote debugging enabled for cookie export

echo "Starting Chrome with remote debugging..."
echo "This allows the export script to connect to your existing browser session."
echo ""

# Kill existing Chrome with debugging port
lsof -ti:9222 | xargs kill -9 2>/dev/null

# Start Chrome with remote debugging
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/Library/Application Support/Google/Chrome" \
  > /dev/null 2>&1 &

echo "✓ Chrome started with remote debugging on port 9222"
echo ""
echo "Now you can:"
echo "1. Log in to 抖音 (douyin.com) and 小红书 (xiaohongshu.com)"
echo "2. Run: ./run_export.sh --save-secrets"
echo ""
