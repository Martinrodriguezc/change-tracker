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


def parse_unified_diff(diff_output: str) -> list:
    """Parse unified diff output into structured change entries."""
    changes = []
    current_file = None
    current_old_lines = []
    current_new_lines = []
    in_hunk = False
    change_id = 0

    lines = diff_output.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]

        # New file diff header
        if line.startswith("diff --git"):
            # Flush previous hunk
            if current_file and (current_old_lines or current_new_lines):
                change_id += 1
                changes.append({
                    "id": change_id,
                    "file": current_file,
                    "type": _detect_type(current_old_lines, current_new_lines),
                    "old_text": "\n".join(current_old_lines),
                    "new_text": "\n".join(current_new_lines),
                    "reason": "",
                    "category": "refactor",
                })
                current_old_lines = []
                current_new_lines = []

            # Extract file path from "diff --git a/path b/path"
            match = re.match(r"diff --git a/(.*) b/(.*)", line)
            if match:
                current_file = match.group(2)
            in_hunk = False
            i += 1
            continue

        # New file mode
        if line.startswith("new file mode"):
            i += 1
            continue

        # Deleted file mode
        if line.startswith("deleted file mode"):
            i += 1
            continue

        # --- and +++ headers
        if line.startswith("---") or line.startswith("+++"):
            i += 1
            continue

        # Hunk header
        if line.startswith("@@"):
            # If we had a previous hunk for the same file, flush it as a separate change
            if in_hunk and (current_old_lines or current_new_lines):
                change_id += 1
                changes.append({
                    "id": change_id,
                    "file": current_file,
                    "type": _detect_type(current_old_lines, current_new_lines),
                    "old_text": "\n".join(current_old_lines),
                    "new_text": "\n".join(current_new_lines),
                    "reason": "",
                    "category": "refactor",
                })
                current_old_lines = []
                current_new_lines = []

            in_hunk = True
            i += 1
            continue

        # Diff content lines
        if in_hunk:
            if line.startswith("-"):
                current_old_lines.append(line[1:])
            elif line.startswith("+"):
                current_new_lines.append(line[1:])
            elif line.startswith(" "):
                # Context line — include in both
                current_old_lines.append(line[1:])
                current_new_lines.append(line[1:])
            # Skip "\ No newline at end of file"

        i += 1

    # Flush last change
    if current_file and (current_old_lines or current_new_lines):
        change_id += 1
        changes.append({
            "id": change_id,
            "file": current_file,
            "type": _detect_type(current_old_lines, current_new_lines),
            "old_text": "\n".join(current_old_lines),
            "new_text": "\n".join(current_new_lines),
            "reason": "",
            "category": "refactor",
        })

    return changes


def _detect_type(old_lines: list, new_lines: list) -> str:
    """Detect if this is a create, edit, or rewrite."""
    if not old_lines or all(l == "" for l in old_lines):
        return "create"
    if not new_lines or all(l == "" for l in new_lines):
        return "edit"
    return "edit"


def make_paths_absolute(changes: list, repo: str) -> list:
    """Convert relative file paths to absolute."""
    repo_path = Path(repo).resolve()
    for change in changes:
        if not change["file"].startswith("/"):
            change["file"] = str(repo_path / change["file"])
    return changes


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
            # Maybe everything is staged but not committed, try against last commit
            diff_output = run_git(repo, "diff", "--cached", "-U2")
        if not diff_output.strip():
            # Try last commit's changes
            diff_output = run_git(repo, "diff", "HEAD~1..HEAD", "-U2")

    if not diff_output.strip():
        print("No changes found.", file=sys.stderr)
        sys.exit(1)

    changes = parse_unified_diff(diff_output)
    changes = make_paths_absolute(changes, repo)

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
