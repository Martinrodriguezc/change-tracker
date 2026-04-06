#!/usr/bin/env python3
"""Append a single change entry to a change-tracker JSON changelog.

Usage:
    cat <<'CHANGE_EOF' | python3 append_change.py /tmp/claude-changes-XXX.json
    {"id":1,"file":"...","type":"edit","old_text":"...","new_text":"...","reason":"...","category":"fix"}
    CHANGE_EOF
"""
import json
import sys

def main():
    if len(sys.argv) != 2:
        print("Usage: echo '<json>' | python3 append_change.py <changelog.json>", file=sys.stderr)
        sys.exit(1)

    changelog_path = sys.argv[1]
    change = json.load(sys.stdin)

    with open(changelog_path) as f:
        data = json.load(f)

    data["changes"].append(change)

    with open(changelog_path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    main()
