---
name: change-tracker
description: >-
  Tracks all code changes during Claude Code sessions and displays them in a live HTML changelog
  with colored diffs. The report opens automatically on the first Edit/Write and updates in
  real-time — no manual invocation needed. Invoke this skill to enable live tracking at session
  start, generate the HTML report, review session changes, or produce commit messages and PR
  descriptions. TRIGGER when: user says "show changes", "what did you change", "what changed",
  "review changes", "changelog", "diff report", "what files did you touch", "session summary",
  "qué cambiaste", "qué cambios hiciste", "muéstrame los cambios", "resumen de cambios",
  "qué archivos tocaste", "genera el commit", "commit message", "prepara el PR",
  "PR description", "ya terminé", "listo el refactor", "haz un commit", "ya está todo",
  "generate commit", "prepare PR", "show me a diff", "list sessions", "previous session",
  "sesión anterior", "historial de cambios". Also trigger at the end of any multi-file editing
  task, after a refactor, or when the user is preparing to commit or create a PR.
---

# Change Tracker

Every Edit and Write is automatically captured by a PostToolUse hook into `~/.claude-change-tracker/current-session.jsonl`. You do NOT need to log anything manually — it happens in the background.

This skill generates the visual HTML report, starts the live server, manages sessions, and generates commit messages and PR descriptions.

## IMPORTANT — Automatic behavior (no skill invocation needed)

The hooks run automatically on every Edit/Write. The live HTML report at `/tmp/claude-changelog-live.html` auto-refreshes. The browser opens automatically on the first change of the session. **You do NOT need to invoke this skill for changes to be tracked.**

When the user asks to see changes ("muéstrame los cambios", "what changed", etc.) and the hooks are already capturing, just tell them:
- The live changelog is already open in the browser (or tell them to check `/tmp/claude-changelog-live.html`)
- If the live SSE server is running, point them to `http://localhost:8877` (or the active port)
- Only invoke this skill's full flow if the user wants to START the live server, generate a STATIC report with explanations, or manage sessions

## First-time setup (one-time)

If hooks are not capturing changes, run the install script to register them in `~/.claude/settings.json`:

```bash
CHANGE_TRACKER_DIR=$(find ~/.claude -path "*/change-tracker/scripts/install.sh" -exec dirname {} \; 2>/dev/null | head -1) && echo "$CHANGE_TRACKER_DIR"
bash "$CHANGE_TRACKER_DIR/install.sh"
```

This installs PostToolUse/PreToolUse hooks that auto-capture every Edit/Write. You only need to run this once.

## Quick start — Live server (preferred)

### Step 1 — Find the scripts

```bash
CHANGE_TRACKER_DIR=$(find ~/.claude -path "*/change-tracker/scripts/serve_changelog.py" -exec dirname {} \; 2>/dev/null | head -1) && echo "$CHANGE_TRACKER_DIR"
```

### Step 2 — Start the live server

```bash
python3 "$CHANGE_TRACKER_DIR/serve_changelog.py" --open
```

This starts a background HTTP server at `http://localhost:8877` (or next available port) that:
- Serves the changelog HTML viewer
- Uses Server-Sent Events (SSE) to push new changes to the browser in real-time
- Shows a connection indicator (green = live, red = disconnected)
- Auto-reconnects if the connection drops
- Shows toast notifications when new changes arrive while the user has scrolled up

The server runs in the background and does NOT block the terminal. Once started, every subsequent Edit/Write will appear in the browser automatically.

### Step 3 — Stop the server when done

```bash
python3 "$CHANGE_TRACKER_DIR/serve_changelog.py" --stop
```

## Alternative — Static HTML report (batch mode)

For a one-time report with full explanations:

### Step 1 — Review captured changes

```bash
python3 -c "
import json
changes = []
for i, line in enumerate(open('$HOME/.claude-change-tracker/current-session.jsonl'), 1):
    c = json.loads(line.strip())
    print(f'#{i} [{c.get(\"type\",\"edit\")}] {c[\"file\"].split(\"/\")[-1]}')
"
```

### Step 2 — Fill in explanations and generate

For each change, decide: `reason`, `category`, `pros`, `cons`, `notes`. Then create the changelog JSON:

```bash
cat <<'EOF' > /tmp/claude-changelog-final.json
{
  "task": "<TASK DESCRIPTION>",
  "timestamp": "<ISO TIMESTAMP>",
  "changes": [
    {
      "id": 1,
      "file": "<from captured data>",
      "type": "<from captured data>",
      "old_text": "<from captured data>",
      "new_text": "<from captured data>",
      "timestamp": "<from captured data>",
      "reason": "<YOUR EXPLANATION>",
      "category": "fix|feature|refactor|style|docs|test",
      "pros": ["advantage 1"],
      "cons": ["trade-off 1"],
      "notes": "optional note"
    }
  ]
}
EOF
```

### Step 3 — Generate the HTML

```bash
python3 "$CHANGE_TRACKER_DIR/generate_changelog.py" /tmp/claude-changelog-final.json --task "<TASK DESCRIPTION>"
```

Or generate directly from the raw JSONL (without explanations):

```bash
python3 "$CHANGE_TRACKER_DIR/generate_changelog.py" --task "<TASK DESCRIPTION>"
```

This opens the HTML report in the browser automatically.

## Retroactive mode (from git)

If the hook wasn't active or changes were made before the plugin was installed:

```bash
python3 "$CHANGE_TRACKER_DIR/from_git_diff.py" --repo <REPO_PATH>
```

Options: `--commits N`, `--range main..HEAD`. Then fill in explanations and generate HTML as above.

## Commit messages

Generate a conventional commit message from the current session:

```bash
python3 "$CHANGE_TRACKER_DIR/commit_message.py"
```

Options:
- `--multi` — Suggest separate commits per category (feat/fix/refactor/etc.)
- `--copy` — Copy to clipboard
- `--file <path>` — Use a specific JSONL file instead of current session

The commit message follows Conventional Commits format:
- Title: `type: short description` (max 72 chars)
- Body: bullet points per file with what changed

## PR descriptions

```bash
python3 "$CHANGE_TRACKER_DIR/to_pr_description.py"
```

Or use directly with `gh pr create`:

```bash
gh pr create --title "feat: description" --body "$(python3 "$CHANGE_TRACKER_DIR/to_pr_description.py")"
```

Options:
- `--copy` — Copy to clipboard
- Pass a specific file: `python3 "$CHANGE_TRACKER_DIR/to_pr_description.py" /path/to/changelog.json`

## Session management

Sessions are stored in `~/.claude-change-tracker/`. Each session is automatically archived when a new one starts (after 30 minutes of inactivity).

```bash
# List all archived sessions
python3 "$CHANGE_TRACKER_DIR/session_manager.py" --list

# Show current session info
python3 "$CHANGE_TRACKER_DIR/session_manager.py" --current

# Open a previous session (by index, 'last', or partial name)
python3 "$CHANGE_TRACKER_DIR/serve_changelog.py" --session last --open

# Force-rotate the current session (archive and start fresh)
python3 "$CHANGE_TRACKER_DIR/session_manager.py" --rotate
```

Sessions include metadata: start time, working directory, git branch. The last 20 sessions are kept by default (configurable in `~/.claude-change-tracker/config.json`).

## Installation & troubleshooting

Verify the installation:

```bash
bash "$CHANGE_TRACKER_DIR/install.sh" --check
```

Fix any issues:

```bash
bash "$CHANGE_TRACKER_DIR/install.sh"
```

### How the hook works

The plugin registers a `PostToolUse` hook in `.claude-plugin/plugin.json` that runs `hook-capture.sh` after every Edit/Write tool call. This shell script:

1. Reads the tool call data from stdin
2. Passes it to `hook_capture_worker.py`
3. The worker appends one JSON line to `~/.claude-change-tracker/current-session.jsonl`
4. If the session is stale (>30 min since last write), it archives the old session first

No configuration needed — the hook is active whenever the plugin is installed.

### Troubleshooting

- **No changes captured?** Run `bash "$CHANGE_TRACKER_DIR/install.sh" --check` to verify the hook is configured.
- **Server won't start?** Check if the port is in use: `python3 "$CHANGE_TRACKER_DIR/serve_changelog.py" --status`
- **Server zombie?** Force stop: `python3 "$CHANGE_TRACKER_DIR/serve_changelog.py" --stop`
- **Old data from previous sessions?** Sessions auto-archive after 30 min of inactivity. Force archive with `python3 "$CHANGE_TRACKER_DIR/session_manager.py" --rotate`

## Writing good explanations

The `reason` field should have: **Context** (what was the problem), **What changed** (plain language), **Why it's correct** (logic, edge cases).

**Bad:** "Fixed the bug" — **Good:** "The generateToken function returned a single JWT valid for 24h. This splits it into a short-lived access token (15min) and a long-lived refresh token (7d). The short access token limits the damage window if stolen."

Use `pros`/`cons` when there are real trade-offs. Use `notes` for follow-up suggestions or warnings. Omit all three for trivial changes.

## Viewer features

- **Live updates:** SSE-powered real-time updates when using the live server
- **Connection indicator:** green dot = connected, red = disconnected (auto-reconnects)
- **Toast notifications:** subtle notification when a new change arrives and user is scrolled up
- **Keyboard:** `j`/`k` to navigate changes, `/` to search, `Escape` to clear
- **Search:** filters across file paths, explanations, pros, cons, notes, and diff content
- **Export:** download button exports as markdown
- **Paths:** common prefix stripped automatically, full path on hover
- **Timestamps:** each change shows capture time, hover for full ISO
- **Char-level diffs:** exact changed characters highlighted within lines
- **Auto-start server:** SSE server launches automatically on first change
- **Dark/light mode:** toggleable, remembers your preference
