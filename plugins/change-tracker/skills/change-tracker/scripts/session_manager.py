#!/usr/bin/env python3
"""Session management for change-tracker.

Handles session lifecycle: rotation, archival, listing, and cleanup.
Storage: ~/.claude-change-tracker/

Usage:
    python3 session_manager.py --list               # List all sessions
    python3 session_manager.py --session <id>        # Open a specific session report
    python3 session_manager.py --session last        # Open the previous session
    python3 session_manager.py --current             # Show current session info
    python3 session_manager.py --rotate              # Force-rotate the current session
    python3 session_manager.py --cleanup             # Remove sessions beyond retention limit
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

BASE_DIR = Path.home() / ".claude-change-tracker"
SESSIONS_DIR = BASE_DIR / "sessions"
CURRENT_SESSION = BASE_DIR / "current-session.jsonl"
SESSION_META = BASE_DIR / "session-meta.json"
SERVER_PID_FILE = BASE_DIR / "server.pid"
CONFIG_FILE = BASE_DIR / "config.json"

DEFAULT_CONFIG = {
    "max_sessions": 20,
    "stale_minutes": 30,
    "server_port": 8877,
}


def ensure_dirs():
    """Create the storage directories if they don't exist."""
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    """Load config, creating defaults if needed."""
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            # Merge with defaults for any missing keys
            merged = {**DEFAULT_CONFIG, **cfg}
            return merged
        except (json.JSONDecodeError, OSError):
            pass
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict):
    """Save config to disk."""
    ensure_dirs()
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def get_git_branch(cwd: str = None) -> str:
    """Get current git branch name, or empty string if not in a repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, cwd=cwd, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return ""


def project_hash(cwd: str = None) -> str:
    """Short hash of the working directory path for session identification."""
    path = cwd or os.getcwd()
    return hashlib.md5(path.encode()).hexdigest()[:6]


def read_session_meta() -> dict:
    """Read the current session metadata."""
    if SESSION_META.exists():
        try:
            return json.loads(SESSION_META.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def write_session_meta(meta: dict):
    """Write session metadata."""
    ensure_dirs()
    SESSION_META.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def is_session_stale() -> bool:
    """Check if the current session should be rotated.

    A session is stale if:
    - current-session.jsonl exists with content
    - AND it hasn't been modified in >stale_minutes (default 30)
    """
    if not CURRENT_SESSION.exists():
        return False
    st = CURRENT_SESSION.stat()
    if st.st_size == 0:
        return False

    cfg = load_config()
    stale_seconds = cfg.get("stale_minutes", 30) * 60
    return (time.time() - st.st_mtime) > stale_seconds


def count_changes(jsonl_path: Path) -> int:
    """Count lines (changes) in a JSONL file."""
    if not jsonl_path.exists():
        return 0
    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
    except OSError:
        return 0


def archive_current_session() -> str | None:
    """Move current-session.jsonl to sessions/ with a timestamped name.

    Returns the archive filename, or None if nothing to archive.
    """
    if not CURRENT_SESSION.exists() or CURRENT_SESSION.stat().st_size == 0:
        return None

    ensure_dirs()
    meta = read_session_meta()

    # Build archive filename: timestamp_projecthash.jsonl
    started = meta.get("started_at", "")
    if started:
        try:
            ts = datetime.fromisoformat(started).strftime("%Y-%m-%dT%H-%M-%S")
        except ValueError:
            ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    else:
        # Use file mtime of the first line as approximation
        ts = datetime.fromtimestamp(CURRENT_SESSION.stat().st_mtime).strftime("%Y-%m-%dT%H-%M-%S")

    phash = meta.get("project_hash", project_hash())
    archive_name = f"{ts}_{phash}.jsonl"
    archive_path = SESSIONS_DIR / archive_name

    # Avoid overwriting existing archives
    counter = 1
    while archive_path.exists():
        archive_name = f"{ts}_{phash}_{counter}.jsonl"
        archive_path = SESSIONS_DIR / archive_name
        counter += 1

    # Also save metadata alongside the session
    meta_archive = archive_path.with_suffix(".meta.json")
    meta["archived_at"] = datetime.now().isoformat()
    meta["changes_count"] = count_changes(CURRENT_SESSION)

    CURRENT_SESSION.rename(archive_path)
    meta_archive.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    return archive_name


def _get_session_token() -> str:
    """Get a stable identifier for the current Claude Code session.

    Uses CLAUDE_CODE_SSE_PORT which is unique per Claude Code instance.
    Falls back to PPID.
    """
    return os.environ.get("CLAUDE_CODE_SSE_PORT", "") or str(os.getppid())


def is_new_session() -> bool:
    """Check if this is a different Claude Code session than the one that wrote the current log.

    Compares the stored session_token in metadata with the current one.
    """
    try:
        if not CURRENT_SESSION.exists() or CURRENT_SESSION.stat().st_size == 0:
            return False
    except OSError:
        return False

    meta = read_session_meta()
    stored_token = meta.get("session_token", "")
    if not stored_token:
        return False

    current_token = _get_session_token()
    return bool(current_token) and stored_token != current_token


def start_new_session(cwd: str = None):
    """Start a fresh session: archive old one if needed, create new metadata."""
    ensure_dirs()

    # Archive existing session if it has content
    if CURRENT_SESSION.exists() and CURRENT_SESSION.stat().st_size > 0:
        archive_current_session()

    # Create empty current session file
    CURRENT_SESSION.write_text("", encoding="utf-8")

    # Clean up ephemeral files from previous session
    for tmp_file in [
        Path("/tmp/claude-change-tracker-explanations.jsonl"),
        Path("/tmp/claude-change-tracker-summary.json"),
        Path("/tmp/claude-change-tracker-summary.lock"),
        Path("/tmp/claude-change-tracker-last-change.json"),
        BASE_DIR / ".opened-session",
    ]:
        tmp_file.unlink(missing_ok=True)

    # Write fresh metadata
    cwd = cwd or os.getcwd()
    meta = {
        "started_at": datetime.now().isoformat(),
        "cwd": cwd,
        "branch": get_git_branch(cwd),
        "project_hash": project_hash(cwd),
        "session_token": _get_session_token(),
    }
    write_session_meta(meta)

    return meta


def rotate_if_stale(cwd: str = None) -> bool:
    """Check and rotate session if stale or if it's a new Claude session. Returns True if rotated."""
    if not CURRENT_SESSION.exists():
        start_new_session(cwd)
        return True

    # is_new_session() already checks exists + size > 0
    if is_new_session() or is_session_stale():
        start_new_session(cwd)
        return True

    return False


def enforce_retention():
    """Remove old sessions beyond the retention limit."""
    cfg = load_config()
    max_sessions = cfg.get("max_sessions", 20)

    # List all session files (not meta files)
    sessions = sorted(
        SESSIONS_DIR.glob("*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )

    if len(sessions) <= max_sessions:
        return

    # Remove oldest sessions
    for old in sessions[max_sessions:]:
        old.unlink(missing_ok=True)
        meta_file = old.with_suffix(".meta.json")
        meta_file.unlink(missing_ok=True)


def list_sessions() -> list[dict]:
    """List all archived sessions with metadata."""
    sessions = []
    for jsonl_file in sorted(SESSIONS_DIR.glob("*.jsonl"), reverse=True):
        meta_file = jsonl_file.with_suffix(".meta.json")
        meta = {}
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

        changes = meta.get("changes_count", count_changes(jsonl_file))
        sessions.append({
            "file": str(jsonl_file),
            "name": jsonl_file.stem,
            "started_at": meta.get("started_at", ""),
            "archived_at": meta.get("archived_at", ""),
            "cwd": meta.get("cwd", ""),
            "branch": meta.get("branch", ""),
            "changes": changes,
            "size_kb": round(jsonl_file.stat().st_size / 1024, 1),
        })

    return sessions


def print_sessions_table(sessions: list[dict]):
    """Pretty-print the sessions list."""
    if not sessions:
        print("No archived sessions found.")
        return

    print(f"{'#':<4} {'Date':<20} {'Branch':<15} {'Changes':<9} {'Size':<8} {'Directory'}")
    print("-" * 90)
    for i, s in enumerate(sessions, 1):
        date = s["started_at"][:19].replace("T", " ") if s["started_at"] else "unknown"
        branch = s["branch"][:14] or "-"
        cwd = s["cwd"]
        # Shorten cwd
        if len(cwd) > 35:
            cwd = "..." + cwd[-32:]
        print(f"{i:<4} {date:<20} {branch:<15} {s['changes']:<9} {s['size_kb']:.1f} KB  {cwd}")

    print(f"\nTotal: {len(sessions)} sessions")


def get_session_path(session_id: str) -> Path | None:
    """Resolve a session identifier to a JSONL path.

    Accepts: 'last', '1', '2' (index), or a partial filename match.
    """
    sessions = list_sessions()
    if not sessions:
        return None

    if session_id == "last":
        return Path(sessions[0]["file"])

    # Try as index (1-based)
    try:
        idx = int(session_id)
        if 1 <= idx <= len(sessions):
            return Path(sessions[idx - 1]["file"])
    except ValueError:
        pass

    # Try as partial filename match
    for s in sessions:
        if session_id in s["name"]:
            return Path(s["file"])

    return None


def main():
    parser = argparse.ArgumentParser(description="Change Tracker session management")
    parser.add_argument("--list", action="store_true", help="List all archived sessions")
    parser.add_argument("--session", type=str, help="Open a specific session ('last', index, or name)")
    parser.add_argument("--current", action="store_true", help="Show current session info")
    parser.add_argument("--rotate", action="store_true", help="Force-rotate the current session")
    parser.add_argument("--cleanup", action="store_true", help="Enforce retention limit")
    parser.add_argument("--json", action="store_true", help="Output in JSON format")
    args = parser.parse_args()

    ensure_dirs()

    if args.list:
        sessions = list_sessions()
        if args.json:
            print(json.dumps(sessions, indent=2, ensure_ascii=False))
        else:
            print_sessions_table(sessions)

    elif args.session:
        path = get_session_path(args.session)
        if not path:
            print(f"Session '{args.session}' not found.", file=sys.stderr)
            sys.exit(1)
        print(str(path))

    elif args.current:
        meta = read_session_meta()
        changes = count_changes(CURRENT_SESSION)
        meta["changes_count"] = changes
        meta["session_file"] = str(CURRENT_SESSION)
        if args.json:
            print(json.dumps(meta, indent=2, ensure_ascii=False))
        else:
            print(f"Session: {CURRENT_SESSION}")
            print(f"Started: {meta.get('started_at', 'unknown')}")
            print(f"Branch:  {meta.get('branch', '-')}")
            print(f"CWD:     {meta.get('cwd', '-')}")
            print(f"Changes: {changes}")

    elif args.rotate:
        archived = archive_current_session()
        if archived:
            print(f"Archived: {archived}")
        meta = start_new_session()
        print(f"New session started at {meta['started_at']}")

    elif args.cleanup:
        enforce_retention()
        print("Retention enforced.")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
