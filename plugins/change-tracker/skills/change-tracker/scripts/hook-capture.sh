#!/bin/bash
# Change Tracker — PostToolUse hook for Edit/Write auto-capture
# Captures changes to ~/.claude-change-tracker/current-session.jsonl
# Regenerates live HTML, auto-opens browser on first change,
# and launches Claude-powered explanation + summary in background.

LIVE_HTML="/tmp/claude-changelog-live.html"
OPENED_FLAG="$HOME/.claude-change-tracker/.opened-session"
LAST_CHANGE="/tmp/claude-change-tracker-last-change.json"

INPUT_FILE=$(mktemp)
cat > "$INPUT_FILE"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Capture the change (writes to ~/.claude-change-tracker/current-session.jsonl)
# This also handles session rotation (archives old session if new Claude instance detected)
python3 "$SCRIPT_DIR/hook_capture_worker.py" "$INPUT_FILE" >/dev/null 2>&1
rm -f "$INPUT_FILE"

# Regenerate live HTML from current session
CHANGELOG="$HOME/.claude-change-tracker/current-session.jsonl"
if [ -f "$CHANGELOG" ]; then
  python3 "$SCRIPT_DIR/generate_changelog.py" "$CHANGELOG" --live --no-open -o "$LIVE_HTML" >/dev/null 2>&1
fi

# Detect if this is the first change of the current session.
# The flag stores the session token (CLAUDE_CODE_SSE_PORT or PPID).
# If it differs from the current token, this is a new session.
CURRENT_TOKEN="${CLAUDE_CODE_SSE_PORT:-$$}"
STORED_TOKEN=""
if [ -f "$OPENED_FLAG" ]; then
  STORED_TOKEN=$(cat "$OPENED_FLAG" 2>/dev/null)
fi

if [ "$STORED_TOKEN" != "$CURRENT_TOKEN" ]; then
  # New session — write token and auto-start
  mkdir -p "$(dirname "$OPENED_FLAG")"
  printf "%s" "$CURRENT_TOKEN" > "$OPENED_FLAG"

  # Start live SSE server if not already running
  SERVER_RUNNING=false
  if [ -f "$HOME/.claude-change-tracker/server.pid" ]; then
    SERVER_PID=$(python3 -c "import json; print(json.load(open('$HOME/.claude-change-tracker/server.pid')).get('pid',0))" 2>/dev/null || echo "0")
    if kill -0 "$SERVER_PID" 2>/dev/null; then
      SERVER_RUNNING=true
    fi
  fi

  if [ "$SERVER_RUNNING" = false ]; then
    python3 "$SCRIPT_DIR/serve_changelog.py" >/dev/null 2>&1
    sleep 0.5
  fi

  # Open browser pointing to the live server
  PORT=$(python3 -c "import json; print(json.load(open('$HOME/.claude-change-tracker/server.pid')).get('port','8877'))" 2>/dev/null || echo "8877")
  open "http://localhost:$PORT" >/dev/null 2>&1
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
