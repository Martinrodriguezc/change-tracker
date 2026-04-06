#!/usr/bin/env python3
"""Generate a GitHub PR description from a change-tracker changelog.

Usage:
    python3 to_pr_description.py /tmp/claude-changes-XXX.json
    python3 to_pr_description.py /tmp/claude-changes-XXX.json --copy

Outputs markdown suitable for gh pr create --body.
"""
import argparse
import json
import sys
from pathlib import Path
from collections import Counter


def compute_common_prefix(paths):
    if not paths:
        return ""
    parts = [p.split("/") for p in paths]
    prefix = []
    for segments in zip(*parts):
        if len(set(segments)) == 1:
            prefix.append(segments[0])
        else:
            break
    result = "/".join(prefix)
    return result + "/" if result else ""


def main():
    parser = argparse.ArgumentParser(description="Generate PR description from changelog")
    parser.add_argument("changelog", type=Path, help="Path to changelog JSON")
    parser.add_argument("--copy", action="store_true", help="Copy to clipboard (macOS)")
    args = parser.parse_args()

    data = json.loads(args.changelog.read_text(encoding="utf-8"))
    changes = data.get("changes", [])

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
    lines.append(f"**Task:** {data.get('task', 'N/A')}\n")
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

    all_cons = []
    for c in changes:
        for con in c.get("cons", []):
            all_cons.append(con)
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
        import subprocess
        subprocess.run(["pbcopy"], input=output.encode(), check=True)
        print("\n(Copied to clipboard)", file=sys.stderr)


if __name__ == "__main__":
    main()
