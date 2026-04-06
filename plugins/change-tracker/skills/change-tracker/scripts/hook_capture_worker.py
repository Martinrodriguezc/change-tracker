#!/usr/bin/env python3
"""Worker script for the change-tracker PostToolUse hook.

Called by hook-capture.sh with:
    python3 hook_capture_worker.py <changelog_jsonl_path> <input_json_file>

Appends one JSON line per Edit/Write to the JSONL changelog.
Always active — no initialization needed.
"""
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

PRE_CAPTURE_DIR = Path("/tmp/claude-change-tracker-pre")


def main():
    if len(sys.argv) != 3:
        sys.exit(0)

    changelog_path = sys.argv[1]
    input_file = sys.argv[2]

    # Read tool call input
    try:
        input_data = json.loads(Path(input_file).read_text(encoding="utf-8"))
    except Exception:
        sys.exit(0)

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path or tool_name not in ("Edit", "Write"):
        sys.exit(0)

    if tool_name == "Edit":
        old_text = tool_input.get("old_string", "")
        new_text = tool_input.get("new_string", "")
        change_type = "edit"
    elif tool_name == "Write":
        new_text = tool_input.get("content", "")

        # Try to recover old content from PreToolUse capture
        old_text = ""
        path_hash = hashlib.md5(file_path.encode()).hexdigest()
        pre_file = PRE_CAPTURE_DIR / f"{path_hash}.txt"
        if pre_file.exists():
            try:
                old_text = pre_file.read_text(encoding="utf-8")
            except Exception:
                pass
            # Clean up pre-capture file
            try:
                pre_file.unlink()
            except Exception:
                pass

        change_type = "create" if not old_text else "rewrite"
    else:
        sys.exit(0)

    change = {
        "file": file_path,
        "type": change_type,
        "old_text": old_text,
        "new_text": new_text,
        "timestamp": datetime.now().isoformat(),
    }

    # Append one line (JSONL format — atomic, no read-modify-write)
    with open(changelog_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(change, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
