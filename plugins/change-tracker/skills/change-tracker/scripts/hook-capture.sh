#!/bin/bash
# Change Tracker — PostToolUse hook for Edit/Write auto-capture
# Always captures every Edit/Write to /tmp/claude-change-tracker.jsonl
# No activation needed — runs automatically when the plugin is installed.

CHANGELOG="/tmp/claude-change-tracker.jsonl"

# Read stdin into a temp file so Python can read it
INPUT_FILE=$(mktemp)
cat > "$INPUT_FILE"

# Find the hook Python script (same directory as this shell script)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
python3 "$SCRIPT_DIR/hook_capture_worker.py" "$CHANGELOG" "$INPUT_FILE" 2>/dev/null

rm -f "$INPUT_FILE"
exit 0
