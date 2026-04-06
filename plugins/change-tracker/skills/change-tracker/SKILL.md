---
name: change-tracker
description: >-
  Tracks all code changes during Claude Code sessions and displays them in a live
  HTML changelog with colored diffs. The report opens automatically on the first
  Edit/Write and updates in real-time — no manual invocation needed. Invoke this
  skill to enrich the live report with explanations, or to generate a retroactive
  report from git history.
---

# Change Tracker

Every Edit and Write you make is automatically captured by hooks into `/tmp/claude-change-tracker.jsonl`. The live HTML report opens automatically in the browser on the first change and auto-refreshes every 3 seconds.

You do NOT need to invoke this skill for the live report — it works automatically. Invoke it only when the user asks to enrich the report with explanations, generate a retroactive report from git, or create a PR description.

## Live Mode (automatic)

The plugin hooks handle everything:
1. **PreToolUse** saves the current file content before `Write` overwrites it
2. **PostToolUse** captures the change and regenerates the HTML in background
3. Browser opens automatically on the first change
4. HTML auto-refreshes every 3 seconds, preserving scroll position, search, and filters

The live report is always at: `/tmp/claude-changelog-live.html`

## Enriching with explanations

When the user asks for a detailed report, read the captured changes and add explanations:

### Step 1 — Find the scripts

```bash
CHANGE_TRACKER_DIR=$(find ~/.claude -path "*/change-tracker/scripts/generate_changelog.py" -exec dirname {} \; 2>/dev/null | head -1) && echo "$CHANGE_TRACKER_DIR"
```

### Step 2 — Fill in explanations

Read the captured changes and prepare a complete changelog JSON with explanations:

```bash
python3 -c "
import json
changes = []
for i, line in enumerate(open('/tmp/claude-change-tracker.jsonl'), 1):
    c = json.loads(line.strip())
    print(f'#{i} [{c.get(\"type\",\"edit\")}] {c[\"file\"].split(\"/\")[-1]}')
"
```

For each change, decide: `reason`, `category`, `pros`, `cons`, `notes`. Then create a complete changelog JSON:

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

This opens a separate HTML report (not the live one) with full explanations.

## Retroactive mode (from git)

If the hook wasn't active or changes were made before the plugin was installed:

```bash
python3 "$CHANGE_TRACKER_DIR/from_git_diff.py" --repo <REPO_PATH>
```

Options: `--commits N`, `--range main..HEAD`. Then fill in explanations and generate the HTML as above.

## Optional: Generate PR description

```bash
python3 "$CHANGE_TRACKER_DIR/to_pr_description.py" /tmp/claude-changelog-final.json
```

Or with `gh pr create`:

```bash
gh pr create --title "feat: description" --body "$(python3 "$CHANGE_TRACKER_DIR/to_pr_description.py" /tmp/claude-changelog-final.json)"
```

## Writing good explanations

The `reason` field should have: **Context** (what was the problem), **What changed** (plain language), **Why it's correct** (logic, edge cases).

**Bad:** "Fixed the bug" — **Good:** "The generateToken function returned a single JWT valid for 24h. This splits it into a short-lived access token (15min) and a long-lived refresh token (7d). The short access token limits the damage window if stolen."

Use `pros`/`cons` when there are real trade-offs. Use `notes` for follow-up suggestions or warnings. Omit all three for trivial changes.

## Viewer features

- **Keyboard:** `j`/`k` to navigate changes, `/` to search, `Escape` to clear
- **Search:** filters across file paths, explanations, pros, cons, notes, and diff content
- **Export:** download button exports as markdown
- **Paths:** common prefix stripped automatically, full path on hover
- **Timestamps:** each change shows capture time, hover for full ISO
- **Char-level diffs:** exact changed characters highlighted within lines
- **Live refresh:** auto-refreshes every 3s preserving scroll, search, and filter state
