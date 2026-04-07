#!/usr/bin/env python3
"""Install change-tracker hooks into a Claude Code settings.json file.

Usage:
    python3 install_hooks.py <settings_json_path>
    python3 install_hooks.py --remove <settings_json_path>

Adds self-discovering PostToolUse and PreToolUse hooks that work even when
CLAUDE_PLUGIN_ROOT is not set (anthropics/claude-code#24529).
"""
import json
import sys
from pathlib import Path

# Self-discovering hook command template.
# 1. Try CLAUDE_PLUGIN_ROOT (forward-compatible)
# 2. Fall back to cached path at ~/.claude-change-tracker/.plugin-root
# 3. Auto-discover via find, cache for next time
# 4. Self-heal if cached path becomes stale
_HOOK_TEMPLATE = (
    'bash -c \''
    '_C="$HOME/.claude-change-tracker/.plugin-root"; '
    '_R="${{CLAUDE_PLUGIN_ROOT:-}}"; '
    '[ -z "$_R" ] && [ -f "$_C" ] && _R="$(cat "$_C")"; '
    '[ -z "$_R" ] || [ ! -d "$_R/skills" ] && {{ '
    '_R="$(find "$HOME/.claude/plugins" -path "*/change-tracker/scripts/{script}" -print -quit 2>/dev/null)"; '
    '[ -n "$_R" ] && _R="${{_R%/skills/change-tracker/scripts/{script}}}" && '
    'mkdir -p "$(dirname "$_C")" && printf "%s" "$_R" > "$_C"; }}; '
    '[ -n "$_R" ] && exec "$_R/skills/change-tracker/scripts/{script}"; '
    "exit 0'"
)

HOOK_POST = _HOOK_TEMPLATE.format(script="hook-capture.sh")
HOOK_PRE = _HOOK_TEMPLATE.format(script="hook-pre-capture.sh")


def install(settings_path: Path) -> bool:
    """Add change-tracker hooks to a settings.json file. Returns True if modified."""
    d = json.loads(settings_path.read_text(encoding="utf-8"))

    if "hooks" not in d:
        d["hooks"] = {}

    changed = False

    # PostToolUse
    post = d["hooks"].get("PostToolUse", [])
    if not any("change-tracker" in str(e) for e in post):
        post.append({
            "matcher": "Edit|Write",
            "hooks": [{"type": "command", "command": HOOK_POST, "timeout": 5}],
        })
        d["hooks"]["PostToolUse"] = post
        changed = True

    # PreToolUse
    pre = d["hooks"].get("PreToolUse", [])
    if not any("change-tracker" in str(e) for e in pre):
        pre.append({
            "matcher": "Write",
            "hooks": [{"type": "command", "command": HOOK_PRE, "timeout": 5}],
        })
        d["hooks"]["PreToolUse"] = pre
        changed = True

    if changed:
        settings_path.write_text(
            json.dumps(d, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    return changed


def remove(settings_path: Path) -> bool:
    """Remove change-tracker hooks from a settings.json file. Returns True if modified."""
    d = json.loads(settings_path.read_text(encoding="utf-8"))
    changed = False

    for event in ["PostToolUse", "PreToolUse"]:
        entries = d.get("hooks", {}).get(event, [])
        new_entries = []
        for e in entries:
            hooks = [h for h in e.get("hooks", []) if "change-tracker" not in h.get("command", "")]
            if hooks:
                e["hooks"] = hooks
                new_entries.append(e)
            elif "change-tracker" not in str(e):
                new_entries.append(e)
            else:
                changed = True
        if entries != new_entries:
            d["hooks"][event] = new_entries
            changed = True
        if event in d.get("hooks", {}) and not d["hooks"][event]:
            del d["hooks"][event]

    if changed:
        if not d.get("hooks"):
            del d["hooks"]
        settings_path.write_text(
            json.dumps(d, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    return changed


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} [--remove] <settings.json>", file=sys.stderr)
        sys.exit(1)

    if sys.argv[1] == "--remove":
        path = Path(sys.argv[2])
        removed = remove(path)
        print("Removed" if removed else "Nothing to remove")
    else:
        path = Path(sys.argv[1])
        installed = install(path)
        print("Installed" if installed else "Already installed")
