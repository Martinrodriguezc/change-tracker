#!/bin/bash
# Change Tracker — PostToolUse hook for Edit/Write auto-capture
# Captures changes to ~/.claude-change-tracker/current-session.jsonl
# Regenerates live HTML, auto-opens browser on first change,
# and launches Claude-powered explanation + summary in background.

LIVE_HTML="/tmp/claude-changelog-live.html"
OPENED_FLAG="/tmp/claude-changelog-opened"
LAST_CHANGE="/tmp/claude-change-tracker-last-change.json"

INPUT_FILE=$(mktemp)
cat > "$INPUT_FILE"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Capture the change (writes to ~/.claude-change-tracker/current-session.jsonl)
python3 "$SCRIPT_DIR/hook_capture_worker.py" "$INPUT_FILE" >/dev/null 2>&1
rm -f "$INPUT_FILE"

# Regenerate live HTML from current session
CHANGELOG="$HOME/.claude-change-tracker/current-session.jsonl"
if [ -f "$CHANGELOG" ]; then
  python3 "$SCRIPT_DIR/generate_changelog.py" "$CHANGELOG" --live --no-open -o "$LIVE_HTML" >/dev/null 2>&1
fi

# Clear stale flag from previous sessions (older than 30 min)
if [ -f "$OPENED_FLAG" ]; then
  FLAG_AGE=$(( $(date +%s) - $(stat -f %m "$OPENED_FLAG" 2>/dev/null || stat -c %Y "$OPENED_FLAG" 2>/dev/null || echo 0) ))
  if [ "$FLAG_AGE" -gt 1800 ]; then
    rm -f "$OPENED_FLAG"
  fi
fi

# Auto-open browser on first change of the session
if [ ! -f "$OPENED_FLAG" ] && [ -f "$LIVE_HTML" ]; then
  touch "$OPENED_FLAG"
  if [ -f "$HOME/.claude-change-tracker/server.pid" ]; then
    PORT=$(python3 -c "import json; print(json.load(open('$HOME/.claude-change-tracker/server.pid')).get('port','8877'))" 2>/dev/null || echo "8877")
    if kill -0 "$(python3 -c "import json; print(json.load(open('$HOME/.claude-change-tracker/server.pid')).get('pid',0))" 2>/dev/null)" 2>/dev/null; then
      open "http://localhost:$PORT" >/dev/null 2>&1
    else
      open "$LIVE_HTML" >/dev/null 2>&1
    fi
  else
    open "$LIVE_HTML" >/dev/null 2>&1
  fi
fi

# Launch Claude-powered explanation + summary in PARALLEL (fire-and-forget)
if [ -f "$LAST_CHANGE" ]; then
  # Explanation: per-change, then regenerate HTML
  (
    "$SCRIPT_DIR/generate_explanation.sh" "$LAST_CHANGE"
    if [ -f "$CHANGELOG" ]; then
      python3 "$SCRIPT_DIR/generate_changelog.py" "$CHANGELOG" --live --no-open -o "$LIVE_HTML"
    fi
  ) </dev/null >/dev/null 2>&1 &

  # Summary: commit msg + PR desc (runs in parallel, self-debouncing)
  "$SCRIPT_DIR/generate_summary.sh" </dev/null >/dev/null 2>&1 &
fi

exit 0
