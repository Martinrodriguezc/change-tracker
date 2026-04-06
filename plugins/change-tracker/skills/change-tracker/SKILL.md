---
name: change-tracker
description: >-
  Generates a visual HTML changelog of all code changes made during the current session.
  The plugin's hook automatically captures every Edit/Write call — this skill only needs
  to be invoked to generate the report. Use when the user asks to "show changes",
  "generate changelog", "what did you change", "review changes", "show me a diff report",
  or at the end of any multi-file editing task. Also use retroactively to review changes
  from git history.
---

# Change Tracker

Every Edit and Write you make is automatically captured by a PostToolUse hook into `/tmp/claude-change-tracker.jsonl`. You do NOT need to log anything manually — it happens in the background.

This skill generates the visual HTML report from those captured changes. Invoke it when the user asks to see what changed, or at the end of a task.

## Generating the report

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
