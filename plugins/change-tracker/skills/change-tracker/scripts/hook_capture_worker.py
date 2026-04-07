#!/usr/bin/env python3
"""Worker script for the change-tracker PostToolUse hook.

Called by hook-capture.sh with:
    python3 hook_capture_worker.py <input_json_file>

Appends one JSON line per Edit/Write to ~/.claude-change-tracker/current-session.jsonl.
Handles session rotation automatically (archives stale sessions).
Recovers old_text for Write from PreToolUse capture.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from session_manager import (
    CURRENT_SESSION,
    ensure_dirs,
    rotate_if_stale,
    enforce_retention,
)
from shared_utils import PRE_CAPTURE_DIR, LAST_CHANGE_FILE


def main():
    if len(sys.argv) != 2:
        sys.exit(0)

    input_file = sys.argv[1]

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
    else:  # Write
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
            try:
                pre_file.unlink()
            except Exception:
                pass

        change_type = "create" if not old_text else "rewrite"

    # Ensure storage exists and rotate stale sessions
    ensure_dirs()
    cwd = str(Path(file_path).parent) if file_path.startswith("/") else None
    rotate_if_stale(cwd)

    # Determine change ID by counting newlines in the file (O(1) read of size, fast scan)
    change_id = 1
    if CURRENT_SESSION.exists():
        try:
            content = CURRENT_SESSION.read_bytes()
            line_count = content.count(b"\n")
            change_id = line_count + 1
            # Periodically enforce retention (every ~50 writes)
            if line_count > 0 and line_count % 50 == 0:
                enforce_retention()
        except OSError:
            pass

    change = {
        "file": file_path,
        "type": change_type,
        "old_text": old_text,
        "new_text": new_text,
        "timestamp": datetime.now().isoformat(),
    }

    # Append one line (JSONL format — atomic, no read-modify-write)
    with open(CURRENT_SESSION, "a", encoding="utf-8") as f:
        f.write(json.dumps(change, ensure_ascii=False) + "\n")

    # Write last change data for the explanation generator
    last_change = {
        "id": change_id,
        "file": file_path,
        "type": change_type,
        "old_text": old_text[:1000],  # truncate for API prompt
        "new_text": new_text[:1000],
    }
    LAST_CHANGE_FILE.write_text(json.dumps(last_change, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
