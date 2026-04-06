#!/bin/bash
# Change Tracker — PostToolUse hook for Edit/Write auto-capture

CHANGELOG="/tmp/claude-change-tracker.jsonl"
LIVE_HTML="/tmp/claude-changelog-live.html"
OPENED_FLAG="/tmp/claude-changelog-opened"
LAST_CHANGE="/tmp/claude-change-tracker-last-change.json"

INPUT_FILE=$(mktemp)
cat > "$INPUT_FILE"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

python3 "$SCRIPT_DIR/hook_capture_worker.py" "$CHANGELOG" "$INPUT_FILE" >/dev/null 2>&1
rm -f "$INPUT_FILE"

python3 "$SCRIPT_DIR/generate_changelog.py" --live --no-open >/dev/null 2>&1

if [ ! -f "$OPENED_FLAG" ] && [ -f "$LIVE_HTML" ]; then
  touch "$OPENED_FLAG"
  open "$LIVE_HTML" >/dev/null 2>&1
fi

# Launch Claude-powered explanation in background (fire-and-forget)
if [ -f "$LAST_CHANGE" ]; then
  (
    "$SCRIPT_DIR/generate_explanation.sh" "$LAST_CHANGE"
    python3 "$SCRIPT_DIR/generate_changelog.py" --live --no-open
  ) </dev/null >/dev/null 2>&1 &
fi

exit 0
