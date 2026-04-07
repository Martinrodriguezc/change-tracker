#!/bin/bash
# Change Tracker — Installation & verification script
#
# Usage:
#   bash install.sh           # Verify installation and create directories
#   bash install.sh --check   # Just check if everything is set up
#   bash install.sh --clean   # Remove all change-tracker data (sessions, config, PID)

set -euo pipefail

STORAGE_DIR="$HOME/.claude-change-tracker"
SESSIONS_DIR="$STORAGE_DIR/sessions"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
warn() { echo -e "  ${YELLOW}!${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1"; }

echo "Change Tracker — Installation Check"
echo "===================================="
echo ""

# --- Arg parsing ---
MODE="install"
if [[ "${1:-}" == "--check" ]]; then MODE="check"; fi
if [[ "${1:-}" == "--clean" ]]; then MODE="clean"; fi

# --- Clean mode ---
if [[ "$MODE" == "clean" ]]; then
  echo "Cleaning change-tracker data..."

  # Stop server if running
  if [[ -f "$STORAGE_DIR/server.pid" ]]; then
    PID=$(python3 -c "import json; print(json.load(open('$STORAGE_DIR/server.pid')).get('pid',''))" 2>/dev/null || true)
    if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
      kill "$PID" 2>/dev/null && ok "Stopped live server (PID $PID)" || warn "Could not stop server"
    fi
  fi

  if [[ -d "$STORAGE_DIR" ]]; then
    rm -rf "$STORAGE_DIR"
    ok "Removed $STORAGE_DIR"
  else
    ok "Nothing to clean"
  fi
  exit 0
fi

# --- Check Python ---
echo "1. Python"
if command -v python3 &>/dev/null; then
  PY_VERSION=$(python3 --version 2>&1)
  ok "python3 found: $PY_VERSION"
else
  fail "python3 not found — install Python 3.10+"
  exit 1
fi

# --- Check scripts ---
echo ""
echo "2. Scripts"
SCRIPTS=("hook-capture.sh" "hook_capture_worker.py" "session_manager.py" "serve_changelog.py" "generate_changelog.py" "commit_message.py" "to_pr_description.py" "from_git_diff.py")
ALL_FOUND=true
for script in "${SCRIPTS[@]}"; do
  if [[ -f "$SCRIPT_DIR/$script" ]]; then
    ok "$script"
  else
    fail "$script NOT FOUND"
    ALL_FOUND=false
  fi
done

# --- Check hook is executable ---
echo ""
echo "3. Hook permissions"
if [[ -x "$SCRIPT_DIR/hook-capture.sh" ]]; then
  ok "hook-capture.sh is executable"
else
  if [[ "$MODE" == "install" ]]; then
    chmod +x "$SCRIPT_DIR/hook-capture.sh"
    ok "Made hook-capture.sh executable"
  else
    fail "hook-capture.sh is not executable (run without --check to fix)"
  fi
fi

# --- Storage directory ---
echo ""
echo "4. Storage"
if [[ -d "$STORAGE_DIR" ]]; then
  ok "$STORAGE_DIR exists"
else
  if [[ "$MODE" == "install" ]]; then
    mkdir -p "$STORAGE_DIR" "$SESSIONS_DIR"
    ok "Created $STORAGE_DIR"
  else
    warn "$STORAGE_DIR does not exist (run without --check to create)"
  fi
fi

if [[ -d "$SESSIONS_DIR" ]]; then
  SESSION_COUNT=$(find "$SESSIONS_DIR" -name "*.jsonl" 2>/dev/null | wc -l | tr -d ' ')
  ok "$SESSIONS_DIR exists ($SESSION_COUNT archived sessions)"
else
  if [[ "$MODE" == "install" ]]; then
    mkdir -p "$SESSIONS_DIR"
    ok "Created $SESSIONS_DIR"
  fi
fi

# --- Config ---
echo ""
echo "5. Config"
if [[ -f "$STORAGE_DIR/config.json" ]]; then
  ok "config.json exists"
else
  if [[ "$MODE" == "install" ]]; then
    cat > "$STORAGE_DIR/config.json" <<'CONFIGEOF'
{
  "max_sessions": 20,
  "stale_minutes": 30,
  "server_port": 8877
}
CONFIGEOF
    ok "Created default config.json"
  else
    warn "config.json does not exist (defaults will be used)"
  fi
fi

# --- Plugin hook check ---
echo ""
echo "6. Plugin hook"
PLUGIN_JSON="$SCRIPT_DIR/../../.claude-plugin/plugin.json"
if [[ -f "$PLUGIN_JSON" ]]; then
  if grep -q "PostToolUse" "$PLUGIN_JSON" 2>/dev/null; then
    ok "PostToolUse hook configured in plugin.json"
  else
    fail "PostToolUse hook NOT found in plugin.json"
  fi
else
  warn "plugin.json not found at expected path"
fi

# --- Server status ---
echo ""
echo "7. Live server"
if [[ -f "$STORAGE_DIR/server.pid" ]]; then
  PID=$(python3 -c "import json; print(json.load(open('$STORAGE_DIR/server.pid')).get('pid',''))" 2>/dev/null || echo "")
  PORT=$(python3 -c "import json; print(json.load(open('$STORAGE_DIR/server.pid')).get('port',''))" 2>/dev/null || echo "")
  if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
    ok "Server running at http://localhost:$PORT (PID $PID)"
  else
    warn "Stale PID file (server not running)"
    if [[ "$MODE" == "install" ]]; then
      rm -f "$STORAGE_DIR/server.pid"
      ok "Cleaned stale PID file"
    fi
  fi
else
  ok "No server running (start with: python3 $SCRIPT_DIR/serve_changelog.py)"
fi

# --- Summary ---
echo ""
echo "===================================="
if [[ "$MODE" == "install" ]]; then
  echo -e "${GREEN}Installation complete.${NC}"
  echo ""
  echo "The hook auto-captures every Edit/Write when the plugin is active."
  echo ""
  echo "Commands:"
  echo "  python3 $SCRIPT_DIR/serve_changelog.py          # Start live server"
  echo "  python3 $SCRIPT_DIR/serve_changelog.py --stop    # Stop live server"
  echo "  python3 $SCRIPT_DIR/session_manager.py --list    # List sessions"
  echo "  python3 $SCRIPT_DIR/generate_changelog.py        # Generate HTML report"
  echo "  python3 $SCRIPT_DIR/commit_message.py            # Generate commit message"
  echo "  python3 $SCRIPT_DIR/to_pr_description.py         # Generate PR description"
else
  echo "Check complete."
fi
