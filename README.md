# Change Tracker for Claude Code

A Claude Code plugin that automatically documents every code change made during a session and generates a visual HTML diff report you can review in your browser.

![Light Mode](https://raw.githubusercontent.com/Martinrodriguezc/change-tracker/main/assets/screenshot-light.png)
![Dark Mode](https://raw.githubusercontent.com/Martinrodriguezc/change-tracker/main/assets/screenshot-dark.png)

## The Problem

When Claude Code edits multiple files during a task, it's hard to keep track of what changed, where, and why. You end up scrolling through the conversation trying to piece together what happened.

## The Solution

Change Tracker records every edit as it happens — the old code, the new code, and a detailed explanation of why the change was made. At the end, it generates a standalone HTML page with:

- **Colored unified diffs** — red for removed lines, green for added lines, with line numbers and 2 lines of context
- **Detailed explanations** — each change includes context about what it does and why the new code is correct
- **PROs and CONs** — trade-off analysis per change so you can evaluate decisions at a glance
- **Notes and suggestions** — follow-up items, warnings, or additional context
- **File sidebar** — navigate changes grouped by file with change counts
- **Category filters** — filter by fix, feature, refactor, style, docs, or test
- **Search** — find changes by file path or description text
- **Dark/light mode** — toggleable, remembers your preference
- **Retroactive mode** — works even if activated after changes were already made (extracts from `git diff`)
- **Character-level diff highlighting** — within changed lines, the exact characters that differ are highlighted with a stronger background
- **Per-change timestamps** — see when each edit was made during the session
- **Auto-capture via hooks** — edits are recorded automatically via PostToolUse hook, no manual logging needed
- **Keyboard navigation** — `j`/`k` to move between changes, `/` to search, `Escape` to clear
- **Export to Markdown** — download the full changelog as a `.md` file
- **PR description generator** — auto-generate a GitHub PR body from the changelog
- **Relative file paths** — common prefix stripped for cleaner display, full path on hover
- **Zero dependencies** — self-contained HTML file, works offline, Python stdlib only

## Installation

### Option 1: Plugin Marketplace (Recommended)

```bash
# 1. Add the marketplace (one-time setup)
claude plugin marketplace add https://github.com/Martinrodriguezc/change-tracker

# 2. Install the plugin — choose one:

# Global (available in all your projects)
claude plugin install change-tracker

# Or project-only (only available in the current project)
claude plugin install change-tracker --scope project
```

**When to use which scope:**
- `--scope project` — you only want change tracking in specific projects, keeps other projects clean
- no flag (global) — you want it everywhere, always available

### Option 2: Clone and Load Directly

```bash
git clone https://github.com/Martinrodriguezc/change-tracker.git
claude --plugin-dir ./change-tracker
```

This loads the plugin for a single session without installing it permanently.

### Option 3: Manual Install (no marketplace)

Copy the skill directly into your Claude skills directory:

```bash
git clone https://github.com/Martinrodriguezc/change-tracker.git
cp -r change-tracker/plugins/change-tracker/skills/change-tracker ~/.claude/skills/change-tracker
```

This bypasses the plugin system entirely. The skill will be available in all sessions but won't receive automatic updates.

## How It Works

### Automatic Mode (Proactive)

The skill activates automatically when Claude is about to edit code. It:

1. Creates a JSON changelog in `/tmp/` at the start of the task
2. Records each edit immediately after it happens — the exact old and new code, a detailed explanation, PROs/CONs, and optional notes
3. Generates and opens the HTML report when the task is done

You don't need to do anything — it just works in the background.

### Retroactive Mode

Already made changes and want to see them? The skill can extract changes from `git diff` and reconstruct the changelog retroactively:

- **Uncommitted changes** (staged + unstaged) — default
- **Last N commits** — `--commits 3`
- **Specific ref range** — `--range main..HEAD`

Just ask Claude: _"show me what changed"_, _"generate a changelog of recent changes"_, or _"review the last 3 commits"_

Claude will extract the diffs, read the code to understand context, fill in explanations and PROs/CONs, and generate the HTML report.

### Generating PR Descriptions

After a task is complete, generate a ready-to-use PR body from the changelog:

```bash
# Output to stdout
python3 <scripts-dir>/to_pr_description.py /tmp/claude-changes-XXX.json

# Copy to clipboard (macOS)
python3 <scripts-dir>/to_pr_description.py /tmp/claude-changes-XXX.json --copy

# Use directly with gh
gh pr create --title "feat: my feature" --body "$(python3 <scripts-dir>/to_pr_description.py /tmp/claude-changes-XXX.json)"
```

The PR description includes a summary, per-file change list with reasons, trade-offs section (from CONs), notes, and a test plan checklist.

## What Each Change Includes

| Field | Description |
|-------|-------------|
| **File path** | Which file was modified |
| **Category** | `fix`, `feature`, `refactor`, `style`, `docs`, or `test` |
| **Explanation** | Context, what changed, and why the new code is correct |
| **PROs** | Advantages of this change (displayed in green with checkmarks) |
| **CONs** | Trade-offs or downsides (displayed in red with X marks) |
| **Notes** | Follow-up suggestions, warnings, or dependencies to watch |
| **Diff** | Unified diff showing exactly what lines changed |

PROs, CONs, and Notes are optional — trivial changes (renames, typo fixes) skip them.

## What the HTML Report Looks Like

Each change card shows:

```
┌──────────────────────────────────────────────────────────┐
│  /src/services/auth.service.ts              #1  FEATURE  │
│                                                          │
│  The generateToken function previously returned a single │
│  JWT valid for 24h. This splits it into a short-lived    │
│  access token (15min) and a long-lived refresh token     │
│  (7 days). The short access token limits damage if       │
│  stolen, while refresh allows seamless session renewal.  │
│                                                          │
│  ✓ Reduces exposure window — stolen token useless in 15m │
│  ✓ Refresh token rotation limits damage from theft       │
│  ✗ Frontend must handle refresh flow (more complexity)   │
│                                                          │
│  📝 Consider Redis blacklist for revoked refresh tokens  │
│     if user count exceeds ~10K.                          │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │  @@ -1,7 +1,15 @@                                 │  │
│  │ - export function generateToken(user): string {    │  │
│  │ + export function generateToken(user): {           │  │
│  │ +   accessToken: string;                           │  │
│  │ +   refreshToken: string;                          │  │
│  │ + } {                                              │  │
│  │     const accessToken = jwt.sign(                  │  │
│  │ -     { expiresIn: '24h' }                         │  │
│  │ +     { expiresIn: '15m' }                         │  │
│  │     );                                             │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

The sidebar lets you navigate by file, filter by category, and search by text. Large diffs (100+ lines) are collapsed by default with an expand button.

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `j` / `↓` | Next change |
| `k` / `↑` | Previous change |
| `/` | Focus search |
| `Escape` | Clear focus / blur search |

## Requirements

- **Claude Code** (CLI, desktop app, or IDE extension)
- **Python 3.6+** (pre-installed on macOS and most Linux distros)
- **Git** (only needed for retroactive mode)

No npm packages, no pip installs, no external dependencies.

## Updating

```bash
# If installed via marketplace
claude plugin update change-tracker

# If cloned manually
cd path/to/change-tracker && git pull
```

## License

MIT
