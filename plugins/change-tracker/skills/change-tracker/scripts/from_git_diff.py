#!/usr/bin/env python3
"""Generate a change-tracker JSON changelog from git diff output.

Retroactive mode: when the skill is invoked after changes were already made,
this script extracts all modifications from git and builds the changelog.

Usage:
    # Changes since last commit (unstaged + staged)
    python3 from_git_diff.py --repo /path/to/repo

    # Changes in last N commits
    python3 from_git_diff.py --repo /path/to/repo --commits 3

    # Changes between two refs
    python3 from_git_diff.py --repo /path/to/repo --range main..HEAD

    # Output path (default: /tmp/claude-changes-{timestamp}.json)
    python3 from_git_diff.py --repo /path/to/repo --output /tmp/my-changelog.json
"""
import argparse
import json
import subprocess
import sys
import re
from pathlib import Path
from datetime import datetime


def run_git(repo: str, *args) -> str:
    """Run a git command and return stdout."""
    result = subprocess.run(
        ["git", "-C", repo] + list(args),
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"git error: {result.stderr.strip()}", file=sys.stderr)
        return ""
    return result.stdout


def _detect_type(old_lines: list, new_lines: list) -> str:
    """Detect if this is a create, delete, or edit."""
    if not old_lines or all(line == "" for line in old_lines):
        return "create"
    if not new_lines or all(line == "" for line in new_lines):
        return "delete"
    return "edit"


def _flush_hunk(changes: list, file: str, old_lines: list, new_lines: list) -> None:
    """Append a change entry from accumulated hunk lines, if any content exists."""
    if not file or (not old_lines and not new_lines):
        return
    changes.append({
        "id": len(changes) + 1,
        "file": file,
        "type": _detect_type(old_lines, new_lines),
        "old_text": "\n".join(old_lines),
        "new_text": "\n".join(new_lines),
        "reason": "",
        "category": "refactor",
    })


def parse_unified_diff(diff_output: str) -> list:
    """Parse unified diff output into structured change entries."""
    changes = []
    current_file = None
    current_old_lines = []
    current_new_lines = []
    in_hunk = False

    for line in diff_output.split("\n"):
        if line.startswith("diff --git"):
            _flush_hunk(changes, current_file, current_old_lines, current_new_lines)
            current_old_lines = []
            current_new_lines = []

            match = re.match(r"diff --git a/(.*) b/(.*)", line)
            if match:
                current_file = match.group(2)
            in_hunk = False
            continue

        if line.startswith(("new file mode", "deleted file mode", "---", "+++")):
            continue

        if line.startswith("@@"):
            if in_hunk:
                _flush_hunk(changes, current_file, current_old_lines, current_new_lines)
                current_old_lines = []
                current_new_lines = []
            in_hunk = True
            continue

        if in_hunk:
            if line.startswith("-"):
                current_old_lines.append(line[1:])
            elif line.startswith("+"):
                current_new_lines.append(line[1:])
            elif line.startswith(" "):
                current_old_lines.append(line[1:])
                current_new_lines.append(line[1:])

    _flush_hunk(changes, current_file, current_old_lines, current_new_lines)
    return changes


def make_paths_absolute(changes: list, repo: str) -> None:
    """Convert relative file paths to absolute (mutates in place)."""
    repo_path = Path(repo).resolve()
    for change in changes:
        if not change["file"].startswith("/"):
            change["file"] = str(repo_path / change["file"])


def main():
    parser = argparse.ArgumentParser(description="Generate changelog from git diff")
    parser.add_argument("--repo", type=str, required=True, help="Path to the git repository")
    parser.add_argument("--commits", type=int, default=None, help="Number of recent commits to include")
    parser.add_argument("--range", type=str, default=None, help="Git ref range (e.g., main..HEAD)")
    parser.add_argument("--output", "-o", type=Path, default=None, help="Output JSON path")
    args = parser.parse_args()

    repo = str(Path(args.repo).resolve())

    # Determine which diff to use
    if args.range:
        diff_output = run_git(repo, "diff", args.range, "-U2")
    elif args.commits:
        diff_output = run_git(repo, "diff", f"HEAD~{args.commits}..HEAD", "-U2")
    else:
        # Unstaged + staged changes (working tree vs HEAD)
        diff_output = run_git(repo, "diff", "HEAD", "-U2")
        if not diff_output.strip():
            # No working tree changes — fall back to last commit's changes
            diff_output = run_git(repo, "diff", "HEAD~1..HEAD", "-U2")

    if not diff_output.strip():
        print("No changes found.", file=sys.stderr)
        sys.exit(1)

    changes = parse_unified_diff(diff_output)
    make_paths_absolute(changes, repo)

    # Get commit message for task description if available
    task = run_git(repo, "log", "--oneline", "-1", "--format=%s").strip()
    if not task:
        task = "Cambios detectados retroactivamente via git diff"

    changelog = {
        "task": task,
        "timestamp": datetime.now().isoformat(),
        "changes": changes,
    }

    output = args.output or Path(f"/tmp/claude-changes-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json")
    output.write_text(json.dumps(changelog, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Changelog generado: {output}")
    print(f"  {len(changes)} cambios en {len(set(c['file'] for c in changes))} archivos")
    print(f"\nNOTA: Los campos 'reason' estan vacios — Claude debe llenarlos con explicaciones.")
    print(str(output))


if __name__ == "__main__":
    main()
