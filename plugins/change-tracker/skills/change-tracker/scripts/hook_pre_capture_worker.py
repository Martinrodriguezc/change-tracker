#!/usr/bin/env python3
"""PreToolUse worker: saves the current file content before Write overwrites it.

Called by hook-pre-capture.sh with:
    python3 hook_pre_capture_worker.py <pre_capture_dir> <input_json_file>

Saves the file content to <pre_capture_dir>/<hash>.txt so PostToolUse can read it.
"""
import hashlib
import json
import sys
from pathlib import Path


def main():
    if len(sys.argv) != 3:
        sys.exit(0)

    pre_capture_dir = sys.argv[1]
    input_file = sys.argv[2]

    try:
        input_data = json.loads(Path(input_file).read_text(encoding="utf-8"))
    except Exception:
        sys.exit(0)

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path or tool_name != "Write":
        sys.exit(0)

    target = Path(file_path)
    if not target.exists():
        sys.exit(0)

    # Save current content keyed by file path hash
    path_hash = hashlib.md5(file_path.encode()).hexdigest()
    try:
        content = target.read_text(encoding="utf-8")
        out = Path(pre_capture_dir) / f"{path_hash}.txt"
        out.write_text(content, encoding="utf-8")
    except Exception:
        pass


if __name__ == "__main__":
    main()
