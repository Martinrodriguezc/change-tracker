#!/bin/bash
# Change Tracker — PostToolUse hook for Edit/Write auto-capture
# Captures every Edit/Write to /tmp/claude-change-tracker.jsonl
# Then regenerates the live HTML report in background.

CHANGELOG="/tmp/claude-change-tracker.jsonl"
LIVE_HTML="/tmp/claude-changelog-live.html"

# Read stdin into a temp file so Python can read it
INPUT_FILE=$(mktemp)
cat > "$INPUT_FILE"

# Find the scripts directory
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 1. Capture the change (fast, ~20ms)
python3 "$SCRIPT_DIR/hook_capture_worker.py" "$CHANGELOG" "$INPUT_FILE" 2>/dev/null

rm -f "$INPUT_FILE"

# 2. Check if this is the first change (browser not yet open)
FIRST_RUN=false
[ ! -f "$LIVE_HTML" ] && FIRST_RUN=true

# 3. Regenerate HTML + open browser in fully detached background
(
  python3 "$SCRIPT_DIR/generate_changelog.py" --live --no-open 2>/dev/null
  if [ "$FIRST_RUN" = true ] && [ -f "$LIVE_HTML" ]; then
    open "$LIVE_HTML" 2>/dev/null || xdg-open "$LIVE_HTML" 2>/dev/null
  fi
) </dev/null >/dev/null 2>&1 &
disown 2>/dev/null

exit 0
