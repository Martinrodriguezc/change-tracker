#!/usr/bin/env python3
"""Generate a GitHub PR description from change-tracker data.

Usage:
    python3 to_pr_description.py                              # From current session
    python3 to_pr_description.py /path/to/changelog.json      # From JSON
    python3 to_pr_description.py /path/to/session.jsonl        # From JSONL
    python3 to_pr_description.py --copy                       # Copy to clipboard

Outputs markdown suitable for gh pr create --body.
"""
import argparse
import json
import sys
from pathlib import Path
from collections import Counter

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from session_manager import CURRENT_SESSION
from shared_utils import compute_common_prefix, load_changes_from_jsonl, copy_to_clipboard


def load_changes(source: Path) -> tuple:
    """Load changes from JSONL or JSON, merging explanations. Returns (metadata, changes)."""
    return load_changes_from_jsonl(source)


def main():
    parser = argparse.ArgumentParser(description="Generate PR description from changelog")
    parser.add_argument("changelog", type=Path, nargs="?", default=None,
                        help="Path to changelog JSON/JSONL (default: current session)")
    parser.add_argument("--copy", action="store_true", help="Copy to clipboard (macOS)")
    parser.add_argument("--title", type=str, default=None, help="Override PR title")
    args = parser.parse_args()

    source = args.changelog or CURRENT_SESSION
    if not source.exists():
        print(f"No changes found at {source}", file=sys.stderr)
        sys.exit(1)

    meta, changes = load_changes(source)

    if not changes:
        print("No changes found.", file=sys.stderr)
        sys.exit(1)

    all_files = [c.get("file", "") for c in changes]
    prefix = compute_common_prefix(all_files)
    prefix_len = len(prefix)

    categories = Counter(c.get("category", "other") for c in changes)
    files_changed = len(set(all_files))

    lines = []
    lines.append("## Summary\n")
    task = meta.get("task", "N/A")
    lines.append(f"**Task:** {task}\n")
    lines.append(f"**{files_changed} files changed** | {len(changes)} edits | Categories: {', '.join(f'{cat} ({n})' for cat, n in categories.most_common())}\n")

    lines.append("\n## Changes\n")
    for c in changes:
        display = c["file"][prefix_len:] if prefix_len else c["file"]
        cat = c.get("category", "other").upper()
        reason = c.get("reason", "").strip()
        line = f"- **`{display}`** [{cat}]"
        if reason:
            first_sentence = reason.split(". ")[0].rstrip(".")
            line += f" — {first_sentence}"
        lines.append(line)

    all_cons = [con for c in changes for con in c.get("cons", [])]
    if all_cons:
        lines.append("\n## Trade-offs\n")
        for con in all_cons:
            lines.append(f"- {con}")

    all_notes = [c.get("notes", "").strip() for c in changes if c.get("notes", "").strip()]
    if all_notes:
        lines.append("\n## Notes\n")
        for note in all_notes:
            lines.append(f"- {note}")

    lines.append("\n## Test plan\n")
    lines.append("- [ ] Verify all changes work as described")
    lines.append("- [ ] Review trade-offs listed above")
    lines.append("")

    output = "\n".join(lines)
    print(output)

    if args.copy:
        if copy_to_clipboard(output):
            print("\n(Copied to clipboard)", file=sys.stderr)
        else:
            print("\n(Could not copy to clipboard)", file=sys.stderr)


if __name__ == "__main__":
    main()
