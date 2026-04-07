#!/usr/bin/env python3
"""Generate conventional commit messages from change-tracker session data.

Reads the current session JSONL (or a specified file) and generates
commit message(s) following Conventional Commits format.

Usage:
    python3 commit_message.py                         # From current session
    python3 commit_message.py --file /path/to.jsonl   # From specific file
    python3 commit_message.py --json /path/to.json    # From changelog JSON
    python3 commit_message.py --copy                  # Copy to clipboard (macOS)
    python3 commit_message.py --multi                 # Suggest multiple commits if applicable

Output format:
    feat: short description (max 72 chars)

    - Changed file1: what changed
    - Changed file2: what changed
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from session_manager import CURRENT_SESSION
from shared_utils import load_explanations, compute_common_prefix, load_changes_from_jsonl, copy_to_clipboard


def load_changes(source: Path) -> list[dict]:
    """Load changes from JSONL or JSON file, merging explanations."""
    _, changes = load_changes_from_jsonl(source)
    return changes


def classify_change(change: dict) -> str:
    """Classify a change into a conventional commit category.

    Uses the 'category' field if present, otherwise infers from the change type
    and file path.
    """
    cat = change.get("category", "").lower()
    if cat in ("fix", "feature", "refactor", "style", "docs", "test"):
        return {"feature": "feat"}.get(cat, cat)

    # Infer from file path
    file_path = change.get("file", "").lower()
    if "test" in file_path or "__tests__" in file_path or ".spec." in file_path or ".test." in file_path:
        return "test"
    if "readme" in file_path or ".md" in file_path or "docs/" in file_path:
        return "docs"
    if ".css" in file_path or ".scss" in file_path or "style" in file_path:
        return "style"

    # Infer from change type
    if change.get("type") == "create":
        return "feat"

    return "refactor"


def group_changes_by_category(changes: list[dict]) -> dict[str, list[dict]]:
    """Group changes by their conventional commit category."""
    groups = defaultdict(list)
    for c in changes:
        cat = classify_change(c)
        groups[cat].append(c)
    return dict(groups)


def short_path(file_path: str, prefix: str) -> str:
    """Get a short display name for a file."""
    if prefix and file_path.startswith(prefix):
        return file_path[len(prefix):]
    # Just the filename
    return file_path.split("/")[-1]


def generate_single_commit(changes: list[dict]) -> str:
    """Generate a single commit message covering all changes."""
    all_paths = [c.get("file", "") for c in changes]
    prefix = compute_common_prefix(all_paths)
    groups = group_changes_by_category(changes)

    # Determine primary category (most changes)
    primary_cat = max(groups.keys(), key=lambda k: len(groups[k]))
    files = set(short_path(c["file"], prefix) for c in changes)

    # Build title
    if len(files) == 1:
        scope = list(files)[0]
        title = f"{primary_cat}: update {scope}"
    elif len(files) <= 3:
        title = f"{primary_cat}: update {', '.join(sorted(files))}"
    else:
        # Describe by directory or count
        dirs = set()
        for f in all_paths:
            rel = f[len(prefix):] if prefix else f
            parts = rel.split("/")
            if len(parts) > 1:
                dirs.add(parts[0])
        if dirs and len(dirs) <= 2:
            title = f"{primary_cat}: update {', '.join(sorted(dirs))}"
        else:
            title = f"{primary_cat}: update {len(files)} files"

    # Truncate title to 72 chars
    if len(title) > 72:
        title = title[:69] + "..."

    # Build body
    body_lines = []
    for cat in sorted(groups.keys()):
        cat_changes = groups[cat]
        if len(groups) > 1:
            body_lines.append(f"\n{cat}:")
        for c in cat_changes:
            sp = short_path(c["file"], prefix)
            reason = c.get("reason", "").strip()
            if reason:
                first_sentence = reason.split(". ")[0].rstrip(".")
                body_lines.append(f"- {sp}: {first_sentence}")
            else:
                change_type = c.get("type", "edit")
                body_lines.append(f"- {sp} ({change_type})")

    body = "\n".join(body_lines)
    return f"{title}\n\n{body}"


def generate_multi_commits(changes: list[dict]) -> list[str]:
    """Generate multiple commit messages, one per category group."""
    all_paths = [c.get("file", "") for c in changes]
    prefix = compute_common_prefix(all_paths)
    groups = group_changes_by_category(changes)

    messages = []
    for cat, cat_changes in sorted(groups.items()):
        files = set(short_path(c["file"], prefix) for c in cat_changes)

        if len(files) == 1:
            title = f"{cat}: update {list(files)[0]}"
        elif len(files) <= 3:
            title = f"{cat}: update {', '.join(sorted(files))}"
        else:
            title = f"{cat}: update {len(files)} files"

        if len(title) > 72:
            title = title[:69] + "..."

        body_lines = []
        for c in cat_changes:
            sp = short_path(c["file"], prefix)
            reason = c.get("reason", "").strip()
            if reason:
                first_sentence = reason.split(". ")[0].rstrip(".")
                body_lines.append(f"- {sp}: {first_sentence}")
            else:
                body_lines.append(f"- {sp} ({c.get('type', 'edit')})")

        body = "\n".join(body_lines)
        messages.append(f"{title}\n\n{body}")

    return messages


def main():
    parser = argparse.ArgumentParser(description="Generate commit messages from change-tracker data")
    parser.add_argument("--file", "-f", type=Path, default=None, help="JSONL session file")
    parser.add_argument("--json", "-j", type=Path, default=None, help="JSON changelog file")
    parser.add_argument("--multi", action="store_true", help="Generate separate commits per category")
    parser.add_argument("--copy", action="store_true", help="Copy to clipboard (macOS)")
    args = parser.parse_args()

    # Determine source
    source = args.json or args.file or CURRENT_SESSION
    if not source.exists():
        print(f"No changes found at {source}", file=sys.stderr)
        sys.exit(1)

    changes = load_changes(source)
    if not changes:
        print("No changes found.", file=sys.stderr)
        sys.exit(1)

    if args.multi:
        messages = generate_multi_commits(changes)
        groups = group_changes_by_category(changes)
        if len(messages) == 1:
            print(messages[0])
        else:
            print(f"# Suggested: {len(messages)} separate commits\n")
            for i, msg in enumerate(messages, 1):
                print(f"--- Commit {i}/{len(messages)} ---")
                print(msg)
                print()
        output = "\n\n".join(messages)
    else:
        output = generate_single_commit(changes)
        print(output)

    if args.copy:
        if copy_to_clipboard(output):
            print("\n(Copied to clipboard)", file=sys.stderr)
        else:
            print("\n(Could not copy to clipboard — install pbcopy or xclip)", file=sys.stderr)


if __name__ == "__main__":
    main()
