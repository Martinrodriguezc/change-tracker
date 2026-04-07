#!/bin/bash
# Change Tracker — Installation & verification script
#
# Usage:
#   bash install.sh           # Install hooks + create directories
#   bash install.sh --check   # Just check if everything is set up
#   bash install.sh --clean   # Remove all change-tracker data and hooks

set -euo pipefail

STORAGE_DIR="$HOME/.claude-change-tracker"
SESSIONS_DIR="$STORAGE_DIR/sessions"
SETTINGS_FILE="$HOME/.claude/settings.json"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m'

ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
warn() { echo -e "  ${YELLOW}!${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1"; }

# Hook installation uses a Python helper to avoid quoting hell
install_hooks() {
  python3 "$SCRIPT_DIR/install_hooks.py" "$1"
}

echo "Change Tracker — Installation"
echo "=============================="
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

  # Remove hooks from settings.json
  if [[ -f "$SETTINGS_FILE" ]]; then
    python3 -c "
import json
f = '$SETTINGS_FILE'
d = json.load(open(f))
changed = False
for event in ['PostToolUse', 'PreToolUse']:
    entries = d.get('hooks', {}).get(event, [])
    new_entries = []
    for e in entries:
        hooks = [h for h in e.get('hooks', []) if 'change-tracker' not in h.get('command', '')]
        if hooks:
            e['hooks'] = hooks
            new_entries.append(e)
        elif 'change-tracker' not in str(e):
            new_entries.append(e)
        else:
            changed = True
    if entries != new_entries:
        d['hooks'][event] = new_entries
        changed = True
    if not d['hooks'][event]:
        del d['hooks'][event]
if changed:
    if not d.get('hooks'):
        del d['hooks']
    with open(f, 'w') as out:
        json.dump(d, out, indent=2, ensure_ascii=False)
        out.write('\n')
" 2>/dev/null && ok "Removed hooks from settings.json" || warn "Could not clean hooks from settings.json"
  fi

  if [[ -d "$STORAGE_DIR" ]]; then
    rm -rf "$STORAGE_DIR"
    ok "Removed $STORAGE_DIR"
  else
    ok "Nothing to clean"
  fi

  # Clean temp files
  rm -f /tmp/claude-change-tracker-*.jsonl /tmp/claude-change-tracker-*.json /tmp/claude-change-tracker-*.lock /tmp/claude-changelog-*.html /tmp/claude-changelog-opened
  ok "Cleaned temp files"
  exit 0
fi

# --- Check Python ---
echo "1. Python"
if command -v python3 &>/dev/null; then
  PY_VERSION=$(python3 --version 2>&1)
  ok "python3 found: $PY_VERSION"
else
  fail "python3 not found — install Python 3.9+"
  exit 1
fi

# --- Check scripts ---
echo ""
echo "2. Scripts"
SCRIPTS=("hook-capture.sh" "hook-pre-capture.sh" "hook_capture_worker.py" "hook_pre_capture_worker.py" "session_manager.py" "shared_utils.py" "serve_changelog.py" "generate_changelog.py" "commit_message.py" "to_pr_description.py" "from_git_diff.py")
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
echo "3. Permissions"
for sh in hook-capture.sh hook-pre-capture.sh generate_explanation.sh generate_summary.sh; do
  if [[ -f "$SCRIPT_DIR/$sh" ]]; then
    if [[ -x "$SCRIPT_DIR/$sh" ]]; then
      ok "$sh is executable"
    elif [[ "$MODE" == "install" ]]; then
      chmod +x "$SCRIPT_DIR/$sh"
      ok "Made $sh executable"
    else
      fail "$sh is not executable (run without --check to fix)"
    fi
  fi
done

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

# --- Hooks in settings.json ---
echo ""
echo "6. Hooks (settings.json)"

if [[ ! -f "$SETTINGS_FILE" ]]; then
  if [[ "$MODE" == "install" ]]; then
    mkdir -p "$(dirname "$SETTINGS_FILE")"
    echo '{}' > "$SETTINGS_FILE"
    ok "Created $SETTINGS_FILE"
  else
    fail "$SETTINGS_FILE does not exist"
  fi
fi

# Check if hooks are already installed
HOOKS_INSTALLED=$(python3 -c "
import json
d = json.load(open('$SETTINGS_FILE'))
found = 0
for event in ['PostToolUse', 'PreToolUse']:
    for e in d.get('hooks', {}).get(event, []):
        for h in e.get('hooks', []):
            if 'change-tracker' in h.get('command', ''):
                found += 1
print(found)
" 2>/dev/null || echo "0")

if [[ "$HOOKS_INSTALLED" -ge 2 ]]; then
  ok "PostToolUse + PreToolUse hooks installed"
elif [[ "$MODE" == "install" ]]; then
  install_hooks "$SETTINGS_FILE"
  if [[ $? -eq 0 ]]; then
    ok "Installed PostToolUse + PreToolUse hooks into settings.json"
  else
    fail "Could not install hooks (run manually)"
  fi
else
  warn "Hooks not installed in settings.json (run without --check to install)"
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
  ok "No server running (starts automatically on first change)"
fi

# --- Summary ---
echo ""
echo "=============================="
if [[ "$MODE" == "install" ]]; then
  echo -e "${GREEN}Installation complete.${NC}"
  echo ""
  echo "Hooks are installed in ~/.claude/settings.json and will auto-capture"
  echo "every Edit/Write in ALL Claude Code sessions."
  echo ""
  echo "How it works:"
  echo "  1. Make any edit with Claude Code"
  echo "  2. The browser opens automatically with the live changelog"
  echo "  3. Commit messages and PR descriptions are generated in the background"
  echo ""
  echo "Commands:"
  echo "  python3 $SCRIPT_DIR/serve_changelog.py --open   # Start live SSE server"
  echo "  python3 $SCRIPT_DIR/session_manager.py --list    # List sessions"
  echo "  python3 $SCRIPT_DIR/commit_message.py            # Generate commit message"
  echo "  python3 $SCRIPT_DIR/to_pr_description.py         # Generate PR description"
  echo "  bash $SCRIPT_DIR/install.sh --clean              # Uninstall"
else
  echo "Check complete."
fi
