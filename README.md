# Change Tracker for Claude Code

A plugin that automatically tracks every code change Claude makes and shows them in a live browser dashboard with diffs, AI-generated explanations, commit messages, and PR descriptions.

![Light Mode](https://raw.githubusercontent.com/Martinrodriguezc/change-tracker/main/assets/screenshot-light.png)
![Dark Mode](https://raw.githubusercontent.com/Martinrodriguezc/change-tracker/main/assets/screenshot-dark.png)

## What it does

Every time Claude edits or creates a file, Change Tracker:

1. **Captures the change** (old code, new code, file path, timestamp)
2. **Generates an AI explanation** of what changed and why (via Claude Haiku)
3. **Updates a live dashboard** in your browser via Server-Sent Events (SSE)
4. **Generates a commit message** and **PR description** automatically

All of this happens in the background. You don't need to invoke anything.

## Installation

```bash
# 1. Add the marketplace (one-time)
claude plugin marketplace add https://github.com/Martinrodriguezc/change-tracker

# 2. Install the plugin
claude plugin install change-tracker

# 3. Register the hooks (one-time — required due to Claude Code bug #24529)
CHANGE_TRACKER_DIR=$(find ~/.claude -path "*/change-tracker/scripts/install.sh" -exec dirname {} \; 2>/dev/null | head -1)
bash "$CHANGE_TRACKER_DIR/install.sh"
```

Step 3 adds PostToolUse/PreToolUse hooks to `~/.claude/settings.json`. This is needed because Claude Code currently doesn't load hooks from plugins ([#24529](https://github.com/anthropics/claude-code/issues/24529)). You only need to run it once.

```bash
# Or project-only
claude plugin install change-tracker --scope project
```

## How it works

The plugin registers `PreToolUse` and `PostToolUse` hooks that run on every `Edit` and `Write` tool call. No manual invocation needed.

| What happens | When |
|---|---|
| Change captured to `~/.claude-change-tracker/current-session.jsonl` | Every Edit/Write |
| AI explanation generated (Haiku) | After each change |
| Commit message + PR description generated (Haiku) | After each change (debounced) |
| Live dashboard updated via SSE | Real-time |
| Browser auto-opens | On first change of the session |

### Live dashboard

The dashboard runs at `http://localhost:8877` and includes:

- **Real-time diffs** with line numbers and colored additions/removals
- **AI explanations** that appear after each change (categorized as feat/fix/refactor/style/docs/test)
- **Commit message panel** with copy button
- **PR description panel** with copy button (What/Why/How/Changes/How to test)
- **File sidebar** with change counts
- **Search** across files, code, and explanations
- **Dark/light mode** (remembers preference)
- **Keyboard navigation** (`j`/`k` to navigate, `/` to search)
- **Connection indicator** (green = live, auto-reconnects)

### Session management

Sessions are stored persistently in `~/.claude-change-tracker/`. When you open a new Claude Code conversation, the previous session is automatically archived. The last 20 sessions are kept.

```bash
# These commands are available via the skill — just ask Claude:
# "list my sessions", "show previous session", "rotate session"
```

### Commit messages & PR descriptions

Generated automatically in the background. Access them via:

- The **summary panel** in the live dashboard (click the pencil or refresh icon in the header)
- Ask Claude: _"show me the commit message"_, _"prepare the PR"_
- CLI: `python3 <scripts>/commit_message.py` or `python3 <scripts>/to_pr_description.py`

### Retroactive mode

If you made changes before installing the plugin, extract them from git:

```bash
python3 <scripts>/from_git_diff.py --repo .          # uncommitted changes
python3 <scripts>/from_git_diff.py --commits 3       # last 3 commits
python3 <scripts>/from_git_diff.py --range main..HEAD # specific range
```

## Trigger phrases

The skill activates automatically via hooks, but you can also invoke it by saying things like:

- _"show changes"_, _"what did you change"_, _"changelog"_
- _"generate commit"_, _"prepare PR"_, _"commit message"_
- _"list sessions"_, _"previous session"_
- _"que cambiaste"_, _"muestra los cambios"_, _"genera el commit"_

## Requirements

- **Claude Code** (CLI, desktop, web, or IDE extension)
- **Python 3.9+**
- **Git** (only for retroactive mode)

No npm, no pip, no external dependencies. Python stdlib only.

## Updating

```bash
claude plugin update change-tracker
```

## License

MIT
