#!/bin/bash
# Change Tracker — PostToolUse hook for Edit/Write auto-capture
# Captures every Edit/Write to /tmp/claude-change-tracker.jsonl
# Then regenerates the live HTML report and generates Claude-powered explanations.

CHANGELOG="/tmp/claude-change-tracker.jsonl"
LIVE_HTML="/tmp/claude-changelog-live.html"
OPENED_FLAG="/tmp/claude-changelog-opened"
LAST_CHANGE="/tmp/claude-change-tracker-last-change.json"

# Read stdin into a temp file so Python can read it
INPUT_FILE=$(mktemp)
cat > "$INPUT_FILE"

# Find the scripts directory
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 1. Capture the change (fast, ~20ms)
python3 "$SCRIPT_DIR/hook_capture_worker.py" "$CHANGELOG" "$INPUT_FILE" >/dev/null 2>&1

rm -f "$INPUT_FILE"

# 2. Regenerate HTML (sync — typically <100ms)
python3 "$SCRIPT_DIR/generate_changelog.py" --live --no-open >/dev/null 2>&1

# 3. Open browser once per session
if [ ! -f "$OPENED_FLAG" ] && [ -f "$LIVE_HTML" ]; then
  touch "$OPENED_FLAG"
  open "$LIVE_HTML" >/dev/null 2>&1
fi

# 4. Launch Claude-powered explanation in background (fire-and-forget)
if [ -f "$LAST_CHANGE" ]; then
  CHANGE_ID=$(python3 -c "import json; print(json.load(open('$LAST_CHANGE'))['id'])" 2>/dev/null)
  FILE_PATH=$(python3 -c "import json; print(json.load(open('$LAST_CHANGE'))['file'])" 2>/dev/null)
  OLD_TEXT=$(python3 -c "import json; print(json.load(open('$LAST_CHANGE')).get('old_text',''))" 2>/dev/null)
  NEW_TEXT=$(python3 -c "import json; print(json.load(open('$LAST_CHANGE')).get('new_text',''))" 2>/dev/null)
  CHANGE_TYPE=$(python3 -c "import json; print(json.load(open('$LAST_CHANGE')).get('type','edit'))" 2>/dev/null)

  (
    "$SCRIPT_DIR/generate_explanation.sh" "$CHANGE_ID" "$FILE_PATH" "$OLD_TEXT" "$NEW_TEXT" "$CHANGE_TYPE"
    # Regenerate HTML again with explanation included
    python3 "$SCRIPT_DIR/generate_changelog.py" --live --no-open
  ) </dev/null >/dev/null 2>&1 &
fi

exit 0
