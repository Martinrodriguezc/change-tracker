#!/bin/bash
# Change Tracker — PreToolUse hook for Write
# Saves the current file content before Write overwrites it,
# so PostToolUse can compute a real diff.

PRE_CAPTURE_DIR="/tmp/claude-change-tracker-pre"
mkdir -p "$PRE_CAPTURE_DIR"

INPUT_FILE=$(mktemp)
cat > "$INPUT_FILE"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
python3 "$SCRIPT_DIR/hook_pre_capture_worker.py" "$PRE_CAPTURE_DIR" "$INPUT_FILE" 2>/dev/null

rm -f "$INPUT_FILE"
exit 0
