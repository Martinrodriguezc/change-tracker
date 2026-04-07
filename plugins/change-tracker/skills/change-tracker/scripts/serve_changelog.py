#!/usr/bin/env python3
"""Live changelog server with Server-Sent Events (SSE) for real-time updates.

Serves the change-tracker HTML viewer and pushes new changes to the browser
as they are captured by the PostToolUse hook.

Usage:
    python3 serve_changelog.py                    # Start server (default port 8877)
    python3 serve_changelog.py --port 9000        # Custom port
    python3 serve_changelog.py --session last      # Serve a previous session (read-only)
    python3 serve_changelog.py --stop              # Stop running server
    python3 serve_changelog.py --status            # Check if server is running

Architecture:
    - HTTP server on localhost with 3 endpoints:
        GET /           → HTML viewer with embedded SSE client
        GET /events     → SSE stream of new changes
        GET /data.json  → Full changelog data (for initial load + reconnect)
    - File watcher polls the JSONL file every 1s, reads only new bytes
    - No external dependencies — stdlib only
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import sys
import threading
import time
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from session_manager import (
    BASE_DIR,
    CURRENT_SESSION,
    SERVER_PID_FILE,
    load_config,
    ensure_dirs,
)
from shared_utils import load_explanations, EXPLANATIONS_FILE, SUMMARY_FILE

# Capture python3 path before any daemon fork (PATH may change)
import shutil
_python3_path = shutil.which("python3") or sys.executable or "python3"

# Global state for SSE
_sse_clients: list = []
_sse_lock = threading.Lock()
_changelog_data: dict = {"changes": [], "task": "Live Session", "timestamp": ""}
_data_lock = threading.Lock()
_jsonl_path: Path = CURRENT_SESSION
_explanations_file = EXPLANATIONS_FILE
_summary_file = SUMMARY_FILE


def find_free_port(preferred: int) -> int:
    """Find a free port, starting with the preferred one."""
    for port in range(preferred, preferred + 20):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    raise RuntimeError(f"No free port found in range {preferred}-{preferred+19}")


def load_jsonl_changes(path: Path, offset: int = 0) -> tuple[list[dict], int]:
    """Read JSONL changes starting from byte offset. Returns (changes, new_offset)."""
    if not path.exists():
        return [], 0

    changes = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            f.seek(offset)
            new_data = f.read()
            new_offset = f.tell()

        for i, line in enumerate(new_data.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                entry.setdefault("id", offset + i + 1)
                entry.setdefault("reason", "")
                entry.setdefault("category", "")
                entry.setdefault("pros", [])
                entry.setdefault("cons", [])
                entry.setdefault("notes", "")
                changes.append(entry)
            except json.JSONDecodeError:
                continue

        return changes, new_offset
    except OSError:
        return [], offset


def broadcast_sse(event_type: str, data: str):
    """Send an SSE event to all connected clients."""
    message = f"event: {event_type}\ndata: {data}\n\n"
    with _sse_lock:
        dead = []
        for client_wfile in _sse_clients:
            try:
                client_wfile.write(message.encode("utf-8"))
                client_wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                dead.append(client_wfile)
        for d in dead:
            _sse_clients.remove(d)


def file_watcher():
    """Background thread that watches the JSONL file for new changes and explanations."""
    offset = 0
    change_id_counter = 0
    last_explanations_size = 0
    last_summary_mtime = 0.0

    # Initial load
    changes, offset = load_jsonl_changes(_jsonl_path, 0)
    change_id_counter = len(changes)

    # Merge any existing explanations + categories
    explanations = load_explanations(_explanations_file)
    for c in changes:
        cid = c.get("id", 0)
        if cid in explanations:
            expl = explanations[cid]
            if not c.get("reason"):
                c["reason"] = expl["explanation"]
            if not c.get("category") or c.get("category") == "other":
                c["category"] = expl.get("category") or "other"

    with _data_lock:
        for i, c in enumerate(changes, 1):
            c["id"] = i
        _changelog_data["changes"] = changes
        if changes:
            _changelog_data["timestamp"] = changes[0].get("timestamp", datetime.now().isoformat())

    if _explanations_file.exists():
        try:
            last_explanations_size = _explanations_file.stat().st_size
        except OSError:
            pass

    while True:
        time.sleep(1)

        # --- Check for new explanations ---
        try:
            if _explanations_file.exists():
                expl_size = _explanations_file.stat().st_size
                if expl_size > last_explanations_size:
                    last_explanations_size = expl_size
                    explanations = load_explanations(_explanations_file)
                    updated = []
                    with _data_lock:
                        for c in _changelog_data["changes"]:
                            cid = c.get("id", 0)
                            if cid in explanations:
                                expl = explanations[cid]
                                changed = False
                                if c.get("reason", "") != expl["explanation"] and expl["explanation"]:
                                    c["reason"] = expl["explanation"]
                                    changed = True
                                if expl.get("category") and (not c.get("category") or c.get("category") == "other"):
                                    c["category"] = expl["category"]
                                    changed = True
                                if changed:
                                    updated.append(c)
                    # Broadcast explanation + category updates
                    for c in updated:
                        broadcast_sse("explanation", json.dumps(
                            {"id": c["id"], "reason": c.get("reason", ""), "category": c.get("category", "")},
                            ensure_ascii=False))
        except OSError:
            pass

        # --- Check for updated summary (commit msg + PR desc) ---
        try:
            if _summary_file.exists():
                summary_mtime = _summary_file.stat().st_mtime
                if summary_mtime > last_summary_mtime:
                    last_summary_mtime = summary_mtime
                    summary = json.loads(_summary_file.read_text(encoding="utf-8"))
                    broadcast_sse("summary", json.dumps(summary, ensure_ascii=False))
        except (OSError, json.JSONDecodeError):
            pass

        # --- Check for new changes ---
        if not _jsonl_path.exists():
            continue

        try:
            current_size = _jsonl_path.stat().st_size
        except OSError:
            continue

        if current_size <= offset:
            # File might have been truncated (new session)
            if current_size < offset:
                offset = 0
                change_id_counter = 0
                with _data_lock:
                    _changelog_data["changes"] = []
                broadcast_sse("reset", "{}")
            continue

        new_changes, new_offset = load_jsonl_changes(_jsonl_path, offset)
        if new_changes:
            offset = new_offset

            # Reuse cached explanations (refreshed above if file changed)
            for c in new_changes:
                change_id_counter += 1
                c["id"] = change_id_counter
                if c["id"] in explanations:
                    expl = explanations[c["id"]]
                    if not c.get("reason"):
                        c["reason"] = expl["explanation"]
                    if not c.get("category") or c.get("category") == "other":
                        c["category"] = expl.get("category") or "other"

            with _data_lock:
                _changelog_data["changes"].extend(new_changes)
                if not _changelog_data["timestamp"] and new_changes:
                    _changelog_data["timestamp"] = new_changes[0].get("timestamp", "")

            # Broadcast each new change individually
            for c in new_changes:
                broadcast_sse("change", json.dumps(c, ensure_ascii=False))


class ChangelogHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the live changelog server."""

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._serve_html()
        elif self.path == "/events":
            self._serve_sse()
        elif self.path == "/data.json":
            self._serve_data()
        elif self.path == "/summary.json":
            self._serve_summary()
        else:
            self.send_error(404)

    def _serve_html(self):
        html = generate_live_html()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _serve_sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        with _sse_lock:
            _sse_clients.append(self.wfile)

        # Keep connection alive
        try:
            while True:
                time.sleep(15)
                try:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    break
        finally:
            with _sse_lock:
                if self.wfile in _sse_clients:
                    _sse_clients.remove(self.wfile)

    def _serve_summary(self):
        """Serve the current summary (commit msg + PR desc) as JSON."""
        data = {"commit_message": "", "pr_description": ""}
        if _summary_file.exists():
            try:
                data = json.loads(_summary_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        body = json.dumps(data, ensure_ascii=False)
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def _serve_data(self):
        with _data_lock:
            data = json.dumps(_changelog_data, ensure_ascii=False)
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data.encode("utf-8"))


def generate_live_html() -> str:
    """Generate the live-updating HTML viewer."""
    return LIVE_HTML_TEMPLATE


LIVE_HTML_TEMPLATE = r'''<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Change Tracker — Live</title>
<style>
  :root {
    --bg: #faf9f5;
    --surface: #ffffff;
    --surface-hover: #f5f4f0;
    --border: #e8e6dc;
    --text: #141413;
    --text-muted: #8a8880;
    --accent: #d97757;
    --green: #4a7c3f;
    --green-bg: #e6f2e1;
    --green-border: #b8d4af;
    --red: #c44;
    --red-bg: #fceaea;
    --red-border: #e8b4b4;
    --blue: #4a7c9c;
    --purple: #7c5caa;
    --teal: #3c8c8c;
    --orange: #c87a2a;
    --header-bg: #1a1a1a;
    --header-text: #faf9f5;
    --sidebar-bg: #f5f4f0;
    --mono: 'SF Mono', 'Cascadia Code', 'JetBrains Mono', 'Fira Code', Menlo, Monaco, 'Courier New', monospace;
    --sans: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    --radius: 8px;
    --shadow: 0 1px 3px rgba(0,0,0,0.08);
  }

  html.dark {
    --bg: #161616;
    --surface: #1e1e1e;
    --surface-hover: #262626;
    --border: #333;
    --text: #e0ddd5;
    --text-muted: #777;
    --green: #7ee787;
    --green-bg: rgba(46,160,67,0.12);
    --green-border: rgba(46,160,67,0.3);
    --red: #f85149;
    --red-bg: rgba(248,81,73,0.12);
    --red-border: rgba(248,81,73,0.3);
    --header-bg: #111;
    --header-text: #e0ddd5;
    --sidebar-bg: #1a1a1a;
    --shadow: 0 1px 3px rgba(0,0,0,0.3);
  }

  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    font-family: var(--sans);
    background: var(--bg);
    color: var(--text);
    line-height: 1.5;
    height: 100vh;
    display: flex;
    flex-direction: column;
  }

  .header {
    background: var(--header-bg);
    color: var(--header-text);
    padding: 14px 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-shrink: 0;
    gap: 16px;
  }
  .header-left { display: flex; align-items: center; gap: 16px; flex: 1; min-width: 0; }
  .header-logo {
    font-size: 14px;
    font-weight: 600;
    letter-spacing: 0.5px;
    text-transform: uppercase;
    opacity: 0.7;
    flex-shrink: 0;
  }
  .header-task {
    font-size: 15px;
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .header-right { display: flex; align-items: center; gap: 12px; flex-shrink: 0; }

  .stat-badge {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 4px 10px;
    border-radius: 20px;
    font-size: 12px;
    font-weight: 600;
    background: rgba(255,255,255,0.1);
  }
  .stat-badge.files { color: #b0c4de; }
  .stat-badge.added { color: #7ee787; }
  .stat-badge.removed { color: #f85149; }

  /* Connection indicator */
  .conn-indicator {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 4px 10px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 600;
  }
  .conn-indicator .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    animation: pulse 2s infinite;
  }
  .conn-indicator.connected .dot { background: #7ee787; }
  .conn-indicator.connected { color: #7ee787; background: rgba(126,231,135,0.1); }
  .conn-indicator.disconnected .dot { background: #f85149; animation: none; }
  .conn-indicator.disconnected { color: #f85149; background: rgba(248,81,73,0.1); }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }

  .theme-toggle {
    background: rgba(255,255,255,0.1);
    border: none;
    color: var(--header-text);
    padding: 6px 10px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 16px;
    transition: background 0.2s;
  }
  .theme-toggle:hover { background: rgba(255,255,255,0.2); }

  .layout {
    display: flex;
    flex: 1;
    overflow: hidden;
  }

  .sidebar {
    width: 260px;
    background: var(--sidebar-bg);
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    flex-shrink: 0;
    overflow: hidden;
  }
  .sidebar-section {
    padding: 12px 16px;
    border-bottom: 1px solid var(--border);
  }
  .sidebar-section h3 {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-muted);
    margin-bottom: 8px;
  }

  .search-input {
    width: 100%;
    padding: 7px 10px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--surface);
    color: var(--text);
    font-size: 13px;
    font-family: var(--sans);
    outline: none;
    transition: border-color 0.2s;
  }
  .search-input:focus { border-color: var(--accent); }
  .search-input::placeholder { color: var(--text-muted); }

  .file-list {
    flex: 1;
    overflow-y: auto;
    padding: 8px 0;
  }
  .file-item {
    padding: 6px 16px;
    font-size: 13px;
    font-family: var(--mono);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: space-between;
    transition: background 0.15s;
    white-space: nowrap;
    overflow: hidden;
  }
  .file-item:hover { background: var(--surface-hover); }
  .file-item.active { background: var(--accent); color: #fff; }
  .file-item .file-name {
    overflow: hidden;
    text-overflow: ellipsis;
    direction: rtl;
    text-align: left;
  }
  .file-item .file-count {
    font-size: 11px;
    background: var(--border);
    color: var(--text-muted);
    padding: 1px 7px;
    border-radius: 10px;
    flex-shrink: 0;
    margin-left: 8px;
  }
  .file-item.active .file-count { background: rgba(255,255,255,0.25); color: #fff; }

  .category-filters { display: flex; flex-direction: column; gap: 4px; }
  .category-filter {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    cursor: pointer;
    padding: 3px 0;
  }
  .category-filter input { accent-color: var(--accent); }
  .category-badge {
    display: inline-block;
    padding: 1px 8px;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.3px;
  }
  .category-badge.fix { background: var(--red-bg); color: var(--red); border: 1px solid var(--red-border); }
  .category-badge.feature { background: var(--green-bg); color: var(--green); border: 1px solid var(--green-border); }
  .category-badge.refactor { background: rgba(74,124,156,0.1); color: var(--blue); border: 1px solid rgba(74,124,156,0.3); }
  .category-badge.style { background: rgba(124,92,170,0.1); color: var(--purple); border: 1px solid rgba(124,92,170,0.3); }
  .category-badge.docs { background: rgba(60,140,140,0.1); color: var(--teal); border: 1px solid rgba(60,140,140,0.3); }
  .category-badge.test { background: rgba(200,122,42,0.1); color: var(--orange); border: 1px solid rgba(200,122,42,0.3); }
  .category-badge.other { background: var(--surface-hover); color: var(--text-muted); border: 1px solid var(--border); }

  .main {
    flex: 1;
    overflow-y: auto;
    padding: 24px 32px;
  }

  .change-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    margin-bottom: 20px;
    box-shadow: var(--shadow);
    overflow: hidden;
    transition: border-color 0.3s;
  }
  .change-card.hidden { display: none; }
  .change-card.new-highlight {
    border-color: var(--accent);
    box-shadow: 0 0 0 1px var(--accent), var(--shadow);
  }

  .change-header {
    padding: 14px 18px;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
  }
  .change-header-left { display: flex; flex-direction: column; gap: 4px; flex: 1; min-width: 0; }
  .change-file {
    font-family: var(--mono);
    font-size: 13px;
    font-weight: 600;
    color: var(--accent);
    word-break: break-all;
  }
  .change-reason {
    font-size: 13px;
    color: var(--text);
    line-height: 1.4;
    animation: fadeIn 0.3s ease-in;
  }
  @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
  .change-meta {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-shrink: 0;
  }
  .change-id {
    font-size: 11px;
    color: var(--text-muted);
    font-weight: 600;
  }
  .change-timestamp {
    font-size: 11px;
    color: var(--text-muted);
    font-family: var(--mono);
  }
  .new-file-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 600;
    background: var(--green-bg);
    color: var(--green);
    border: 1px solid var(--green-border);
  }

  .diff-container { overflow-x: auto; }
  .diff-table {
    width: 100%;
    border-collapse: collapse;
    font-family: var(--mono);
    font-size: 12.5px;
    line-height: 1.55;
    tab-size: 4;
  }
  .diff-table td {
    padding: 0 12px;
    white-space: pre;
    vertical-align: top;
  }
  .diff-table .line-num {
    width: 1px;
    padding: 0 8px;
    text-align: right;
    color: var(--text-muted);
    user-select: none;
    font-size: 11px;
    opacity: 0.6;
    border-right: 1px solid var(--border);
  }
  .diff-table .line-sign {
    width: 1px;
    padding: 0 6px;
    text-align: center;
    user-select: none;
    font-weight: 700;
  }
  .diff-table tr.diff-add { background: var(--green-bg); }
  .diff-table tr.diff-add .line-sign { color: var(--green); }
  .diff-table tr.diff-add .line-content { color: var(--green); }
  .diff-table tr.diff-remove { background: var(--red-bg); }
  .diff-table tr.diff-remove .line-sign { color: var(--red); }
  .diff-table tr.diff-remove .line-content { color: var(--red); }
  .diff-table tr.diff-header {
    background: var(--surface-hover);
    color: var(--text-muted);
    font-size: 11px;
  }
  .diff-table tr.diff-header td { padding: 4px 12px; }

  .diff-collapse-toggle {
    display: block;
    width: 100%;
    padding: 8px 18px;
    background: var(--surface-hover);
    border: none;
    border-top: 1px solid var(--border);
    color: var(--accent);
    font-family: var(--sans);
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    text-align: left;
    transition: background 0.15s;
  }
  .diff-collapse-toggle:hover { background: var(--border); }

  .empty-state {
    text-align: center;
    padding: 64px 24px;
    color: var(--text-muted);
  }
  .empty-state p { font-size: 15px; margin-top: 8px; }
  .change-card.focused { outline: 2px solid var(--accent); outline-offset: -2px; }

  /* Toast notification */
  .toast-container {
    position: fixed;
    bottom: 24px;
    right: 24px;
    z-index: 1000;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .toast {
    background: var(--header-bg);
    color: var(--header-text);
    padding: 10px 16px;
    border-radius: var(--radius);
    font-size: 13px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.2);
    animation: slideIn 0.3s ease-out, fadeOut 0.3s ease-in 3s forwards;
    max-width: 320px;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .toast .toast-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--accent);
    flex-shrink: 0;
  }
  @keyframes slideIn {
    from { transform: translateX(100%); opacity: 0; }
    to { transform: translateX(0); opacity: 1; }
  }
  @keyframes fadeOut {
    from { opacity: 1; }
    to { opacity: 0; }
  }

  /* Summary panel */
  .summary-panel {
    width: 0;
    overflow: hidden;
    background: var(--sidebar-bg);
    border-left: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    flex-shrink: 0;
    transition: width 0.25s ease;
  }
  .summary-panel.open { width: 360px; }
  .summary-section {
    padding: 14px 16px;
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }
  .summary-section-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 8px;
  }
  .summary-section h3 {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-muted);
    margin: 0;
  }
  .summary-copy {
    background: none;
    border: 1px solid var(--border);
    border-radius: 4px;
    color: var(--text-muted);
    font-size: 11px;
    cursor: pointer;
    padding: 2px 8px;
    transition: all 0.15s;
  }
  .summary-copy:hover { background: var(--surface-hover); color: var(--text); }
  .summary-copy.copied { background: var(--green-bg); border-color: var(--green-border); color: var(--green); }
  .summary-content {
    font-family: var(--mono);
    font-size: 12px;
    line-height: 1.6;
    white-space: pre-wrap;
    word-break: break-word;
    color: var(--text);
    max-height: 40vh;
    overflow-y: auto;
  }
  .summary-placeholder {
    color: var(--text-muted);
    font-size: 12px;
    font-style: italic;
  }
  .summary-status {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 11px;
    color: var(--text-muted);
    padding: 2px 0;
  }
  .summary-status .spinner {
    width: 10px;
    height: 10px;
    border: 2px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .btn-active { background: rgba(255,255,255,0.25) !important; }
  .summary-updating {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 10px;
    color: var(--accent);
    font-weight: 600;
    letter-spacing: 0.3px;
    text-transform: uppercase;
    opacity: 0;
    transition: opacity 0.3s;
  }
  .summary-updating.visible { opacity: 1; }
  .summary-updating .spinner {
    width: 8px;
    height: 8px;
    border: 1.5px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }

  @media (max-width: 768px) {
    .sidebar { width: 200px; }
    .main { padding: 16px; }
    .header { padding: 12px 16px; }
    .stat-badge { display: none; }
  }
  @media (max-width: 600px) {
    .sidebar { display: none; }
  }
</style>
</head>
<body>

<div class="header">
  <div class="header-left">
    <span class="header-logo">Change Tracker</span>
    <span class="header-task" id="taskTitle">Live Session</span>
  </div>
  <div class="header-right">
    <span class="conn-indicator disconnected" id="connIndicator">
      <span class="dot"></span>
      <span id="connText">Connecting...</span>
    </span>
    <span class="stat-badge files" id="statFiles">0 archivos</span>
    <span class="stat-badge added" id="statChanges">0 cambios</span>
    <button class="theme-toggle" id="btnCommit" title="Generate commit message">&#9998;</button>
    <button class="theme-toggle" id="btnPR" title="Generate PR description">&#8634;</button>
    <button class="theme-toggle" id="themeToggle" title="Toggle theme">&#9789;</button>
  </div>
</div>


<div class="layout">
  <div class="sidebar">
    <div class="sidebar-section">
      <h3>Buscar</h3>
      <input type="text" class="search-input" id="searchInput" placeholder="Buscar en archivos o codigo...">
    </div>

    <div class="sidebar-section" style="border-bottom: none; padding-bottom: 0;">
      <h3>Archivos</h3>
    </div>
    <div class="file-list" id="fileList"></div>
  </div>

  <div class="main" id="mainContent">
    <div class="empty-state" id="emptyState">
      <p>Esperando cambios...</p>
      <p style="font-size: 13px; margin-top: 4px;">Los cambios apareceran aqui en tiempo real cuando Claude edite archivos.</p>
    </div>
  </div>

  <div class="summary-panel" id="summaryPanel">
    <div class="summary-section">
      <div class="summary-section-header">
        <h3>Commit Message <span class="summary-updating" id="commitUpdating"><span class="spinner"></span> Updating</span></h3>
        <button class="summary-copy" id="copyCommit" title="Copy">Copy</button>
      </div>
      <div class="summary-content" id="commitContent">
        <span class="summary-placeholder" id="commitPlaceholder">
          <span class="summary-status"><span class="spinner"></span> Generating after first changes...</span>
        </span>
      </div>
    </div>
    <div class="summary-section" style="border-bottom:none; flex:1; display:flex; flex-direction:column;">
      <div class="summary-section-header">
        <h3>PR Description <span class="summary-updating" id="prUpdating"><span class="spinner"></span> Updating</span></h3>
        <button class="summary-copy" id="copyPR" title="Copy">Copy</button>
      </div>
      <div class="summary-content" id="prContent" style="flex:1;">
        <span class="summary-placeholder" id="prPlaceholder">
          <span class="summary-status"><span class="spinner"></span> Generating after first changes...</span>
        </span>
      </div>
    </div>
  </div>
</div>

<div class="toast-container" id="toastContainer"></div>

<script>
// State
let changes = [];
let activeFile = null;
let searchQuery = '';
let isConnected = false;
let userAtBottom = true;

// Compute common path prefix
function computePrefix(paths) {
  if (paths.length === 0) return '';
  const parts = paths.map(p => p.split('/'));
  const prefix = [];
  for (let i = 0; i < parts[0].length; i++) {
    const seg = parts[0][i];
    if (parts.every(p => p[i] === seg)) prefix.push(seg);
    else break;
  }
  const result = prefix.join('/');
  return result ? result + '/' : '';
}

function getDisplayFile(filePath, prefix) {
  return prefix && filePath.startsWith(prefix) ? filePath.slice(prefix.length) : filePath;
}

// Simple unified diff computation (client-side, for live mode)
function computeDiffLines(oldText, newText) {
  if (!oldText && !newText) return [];
  const oldLines = (oldText || '').split('\n');
  const newLines = (newText || '').split('\n');

  const lines = [];
  // Simple approach: if edit, show removed then added
  if (oldText) {
    oldLines.forEach((l, i) => {
      lines.push({ type: 'remove', old_num: i + 1, new_num: null, text: l });
    });
  }
  newLines.forEach((l, i) => {
    lines.push({ type: 'add', old_num: null, new_num: i + 1, text: l });
  });
  return lines;
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// Track scroll position
const mainEl = document.getElementById('mainContent');
mainEl.addEventListener('scroll', () => {
  userAtBottom = (mainEl.scrollHeight - mainEl.scrollTop - mainEl.clientHeight) < 50;
});

// Render file list
function renderFileList() {
  const container = document.getElementById('fileList');
  container.innerHTML = '';

  const allPaths = changes.map(c => c.file);
  const prefix = computePrefix(allPaths);
  const fileCounts = {};
  changes.forEach(c => {
    fileCounts[c.file] = (fileCounts[c.file] || 0) + 1;
  });

  Object.entries(fileCounts).forEach(([path, count]) => {
    const el = document.createElement('div');
    el.className = 'file-item' + (activeFile === path ? ' active' : '');
    const displayName = getDisplayFile(path, prefix);
    const parts = displayName.split('/');
    const shortPath = parts.length > 3 ? '.../' + parts.slice(-3).join('/') : displayName;
    el.innerHTML = '<span class="file-name" title="' + escapeHtml(path) + '">' + escapeHtml(shortPath) + '</span>'
      + '<span class="file-count">' + count + '</span>';
    el.addEventListener('click', () => {
      activeFile = activeFile === path ? null : path;
      renderFileList();
      renderChanges();
    });
    container.appendChild(el);
  });
}

// Render change cards
function renderChanges() {
  const container = document.getElementById('mainContent');
  container.innerHTML = '';

  const allPaths = changes.map(c => c.file);
  const prefix = computePrefix(allPaths);

  const filtered = changes.filter(c => {
    if (activeFile && c.file !== activeFile) return false;
    if (searchQuery) {
      const haystack = (c.file + ' ' + (c.old_text || '') + ' ' + (c.new_text || '')).toLowerCase();
      if (!haystack.includes(searchQuery)) return false;
    }
    return true;
  });

  if (filtered.length === 0) {
    container.innerHTML = '<div class="empty-state"><p>No hay cambios que coincidan.</p></div>';
    return;
  }

  filtered.forEach(change => {
    const card = document.createElement('div');
    card.className = 'change-card';
    card.dataset.id = change.id;

    const header = document.createElement('div');
    header.className = 'change-header';

    const headerLeft = document.createElement('div');
    headerLeft.className = 'change-header-left';

    const fileEl = document.createElement('div');
    fileEl.className = 'change-file';
    fileEl.textContent = getDisplayFile(change.file, prefix);
    fileEl.title = change.file;
    headerLeft.appendChild(fileEl);

    if (change.reason) {
      const reasonEl = document.createElement('div');
      reasonEl.className = 'change-reason';
      reasonEl.id = 'reason-' + change.id;
      reasonEl.textContent = change.reason;
      headerLeft.appendChild(reasonEl);
    }

    const meta = document.createElement('div');
    meta.className = 'change-meta';

    const idEl = document.createElement('span');
    idEl.className = 'change-id';
    idEl.textContent = '#' + change.id;
    meta.appendChild(idEl);

    if (change.timestamp) {
      const tsEl = document.createElement('span');
      tsEl.className = 'change-timestamp';
      const d = new Date(change.timestamp);
      tsEl.textContent = d.toLocaleTimeString('es-CL', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      tsEl.title = change.timestamp;
      meta.appendChild(tsEl);
    }

    const typeBadge = document.createElement('span');
    typeBadge.className = 'category-badge ' + (change.type === 'create' ? 'feature' : change.type === 'rewrite' ? 'refactor' : 'other');
    typeBadge.textContent = change.type;
    meta.appendChild(typeBadge);

    header.appendChild(headerLeft);
    header.appendChild(meta);
    card.appendChild(header);

    // Diff
    const diffLines = computeDiffLines(change.old_text, change.new_text);
    if (diffLines.length > 0) {
      const diffContainer = document.createElement('div');
      diffContainer.className = 'diff-container';
      const table = document.createElement('table');
      table.className = 'diff-table';

      const maxLines = 80;
      const linesToShow = diffLines.length > maxLines ? diffLines.slice(0, maxLines) : diffLines;

      linesToShow.forEach(line => {
        const tr = document.createElement('tr');
        tr.className = 'diff-' + line.type;

        const oldNum = document.createElement('td');
        oldNum.className = 'line-num';
        oldNum.textContent = line.old_num != null ? line.old_num : '';

        const newNum = document.createElement('td');
        newNum.className = 'line-num';
        newNum.textContent = line.new_num != null ? line.new_num : '';

        const sign = document.createElement('td');
        sign.className = 'line-sign';
        sign.textContent = line.type === 'add' ? '+' : line.type === 'remove' ? '-' : ' ';

        const content = document.createElement('td');
        content.className = 'line-content';
        content.textContent = line.text;

        tr.appendChild(oldNum);
        tr.appendChild(newNum);
        tr.appendChild(sign);
        tr.appendChild(content);
        table.appendChild(tr);
      });

      diffContainer.appendChild(table);

      if (diffLines.length > maxLines) {
        const toggle = document.createElement('button');
        toggle.className = 'diff-collapse-toggle';
        toggle.textContent = 'Mostrar diff completo (' + diffLines.length + ' lineas)';
        let expanded = false;
        toggle.addEventListener('click', () => {
          if (!expanded) {
            table.innerHTML = '';
            diffLines.forEach(line => {
              const tr = document.createElement('tr');
              tr.className = 'diff-' + line.type;
              tr.innerHTML =
                '<td class="line-num">' + (line.old_num != null ? line.old_num : '') + '</td>'
                + '<td class="line-num">' + (line.new_num != null ? line.new_num : '') + '</td>'
                + '<td class="line-sign">' + (line.type === 'add' ? '+' : line.type === 'remove' ? '-' : ' ') + '</td>'
                + '<td class="line-content">' + escapeHtml(line.text) + '</td>';
              table.appendChild(tr);
            });
            toggle.textContent = 'Colapsar diff';
            expanded = true;
          } else {
            table.innerHTML = '';
            diffLines.slice(0, maxLines).forEach(line => {
              const tr = document.createElement('tr');
              tr.className = 'diff-' + line.type;
              tr.innerHTML =
                '<td class="line-num">' + (line.old_num != null ? line.old_num : '') + '</td>'
                + '<td class="line-num">' + (line.new_num != null ? line.new_num : '') + '</td>'
                + '<td class="line-sign">' + (line.type === 'add' ? '+' : line.type === 'remove' ? '-' : ' ') + '</td>'
                + '<td class="line-content">' + escapeHtml(line.text) + '</td>';
              table.appendChild(tr);
            });
            toggle.textContent = 'Mostrar diff completo (' + diffLines.length + ' lineas)';
            expanded = false;
          }
        });
        diffContainer.appendChild(toggle);
      }

      card.appendChild(diffContainer);
    }

    container.appendChild(card);
  });
}

function updateStats() {
  const files = new Set(changes.map(c => c.file));
  document.getElementById('statFiles').textContent = files.size + ' archivo' + (files.size !== 1 ? 's' : '');
  document.getElementById('statChanges').textContent = changes.length + ' cambio' + (changes.length !== 1 ? 's' : '');
}

// Toast notification
function showToast(message) {
  if (userAtBottom) return; // Don't show if user is already at the bottom
  const container = document.getElementById('toastContainer');
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.innerHTML = '<span class="toast-dot"></span>' + escapeHtml(message);
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3500);
}

// SSE connection
function connectSSE() {
  const evtSource = new EventSource('/events');
  const indicator = document.getElementById('connIndicator');
  const connText = document.getElementById('connText');

  evtSource.onopen = () => {
    isConnected = true;
    indicator.className = 'conn-indicator connected';
    connText.textContent = 'Live';
  };

  evtSource.addEventListener('change', (e) => {
    try {
      const change = JSON.parse(e.data);
      changes.push(change);
      showSummaryUpdating();
      renderFileList();
      renderChanges();
      updateStats();

      // Auto-scroll if user was at bottom
      if (userAtBottom) {
        requestAnimationFrame(() => {
          mainEl.scrollTop = mainEl.scrollHeight;
        });
      } else {
        const displayFile = change.file.split('/').pop();
        showToast('Nuevo cambio: ' + displayFile);
      }

      // Highlight the new card briefly
      const lastCard = mainEl.querySelector('.change-card:last-child');
      if (lastCard) {
        lastCard.classList.add('new-highlight');
        setTimeout(() => lastCard.classList.remove('new-highlight'), 2000);
      }

      // Remove empty state
      const empty = document.getElementById('emptyState');
      if (empty) empty.remove();
    } catch (err) {
      console.error('SSE parse error:', err);
    }
  });

  evtSource.addEventListener('explanation', (e) => {
    try {
      const data = JSON.parse(e.data);
      const change = changes.find(c => c.id === data.id);
      if (change) {
        if (data.reason) change.reason = data.reason;
        if (data.category) change.category = data.category;

        const card = document.querySelector('.change-card[data-id="' + data.id + '"]');
        if (!card) return;

        // Update reason
        if (data.reason) {
          const reasonEl = document.getElementById('reason-' + data.id);
          if (reasonEl) {
            reasonEl.textContent = data.reason;
          } else {
            const headerLeft = card.querySelector('.change-header-left');
            if (headerLeft) {
              const newReason = document.createElement('div');
              newReason.className = 'change-reason';
              newReason.id = 'reason-' + data.id;
              newReason.textContent = data.reason;
              headerLeft.appendChild(newReason);
            }
          }
        }

        // Update category badge
        if (data.category) {
          const badge = card.querySelector('.category-badge');
          if (badge) {
            badge.className = 'category-badge ' + data.category;
            badge.textContent = data.category;
          }
        }
      }
    } catch (err) {
      console.error('Explanation SSE error:', err);
    }
  });

  evtSource.addEventListener('summary', (e) => {
    try {
      const data = JSON.parse(e.data);
      updateSummary(data);
    } catch (err) {}
  });

  evtSource.addEventListener('reset', () => {
    changes = [];
    renderFileList();
    renderChanges();
    updateStats();
  });

  evtSource.onerror = () => {
    isConnected = false;
    indicator.className = 'conn-indicator disconnected';
    connText.textContent = 'Reconnecting...';
    // EventSource auto-reconnects
  };
}

// Initial data load
async function loadInitialData() {
  try {
    const resp = await fetch('/data.json');
    const data = await resp.json();
    if (data.changes && data.changes.length > 0) {
      changes = data.changes;
      renderFileList();
      renderChanges();
      updateStats();
      const empty = document.getElementById('emptyState');
      if (empty) empty.remove();
    }
  } catch (err) {
    console.error('Initial load error:', err);
  }
}

// Theme
function initTheme() {
  const saved = localStorage.getItem('change-tracker-theme');
  if (saved === 'dark' || (!saved && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
    document.documentElement.classList.add('dark');
  }
}
function toggleTheme() {
  document.documentElement.classList.toggle('dark');
  const isDark = document.documentElement.classList.contains('dark');
  localStorage.setItem('change-tracker-theme', isDark ? 'dark' : 'light');
  document.getElementById('themeToggle').textContent = isDark ? '\u2600' : '\u263D';
}
initTheme();
document.getElementById('themeToggle').addEventListener('click', toggleTheme);
document.getElementById('themeToggle').textContent =
  document.documentElement.classList.contains('dark') ? '\u2600' : '\u263D';

// Search
document.getElementById('searchInput').addEventListener('input', e => {
  searchQuery = e.target.value.toLowerCase();
  renderChanges();
});

// Keyboard navigation
let focusedCardIndex = -1;
function updateCardFocus() {
  const cards = document.querySelectorAll('.change-card');
  cards.forEach((c, i) => c.classList.toggle('focused', i === focusedCardIndex));
  if (focusedCardIndex >= 0 && focusedCardIndex < cards.length) {
    cards[focusedCardIndex].scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
}

document.addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT') {
    if (e.key === 'Escape') { e.target.blur(); e.preventDefault(); }
    return;
  }
  const cards = document.querySelectorAll('.change-card');
  if (e.key === 'j' || e.key === 'ArrowDown') {
    e.preventDefault();
    focusedCardIndex = Math.min(focusedCardIndex + 1, cards.length - 1);
    updateCardFocus();
  } else if (e.key === 'k' || e.key === 'ArrowUp') {
    e.preventDefault();
    focusedCardIndex = Math.max(focusedCardIndex - 1, 0);
    updateCardFocus();
  } else if (e.key === '/') {
    e.preventDefault();
    document.getElementById('searchInput').focus();
  } else if (e.key === 'Escape') {
    focusedCardIndex = -1;
    updateCardFocus();
  }
});

// Summary panel
const summaryPanel = document.getElementById('summaryPanel');
const commitContent = document.getElementById('commitContent');
const prContent = document.getElementById('prContent');
let panelOpen = false;

function togglePanel() {
  panelOpen = !panelOpen;
  summaryPanel.classList.toggle('open', panelOpen);
  document.getElementById('btnCommit').classList.toggle('btn-active', panelOpen);
  document.getElementById('btnPR').classList.toggle('btn-active', panelOpen);
}

const commitUpdating = document.getElementById('commitUpdating');
const prUpdating = document.getElementById('prUpdating');

function showSummaryUpdating() {
  commitUpdating.classList.add('visible');
  prUpdating.classList.add('visible');
}

function hideSummaryUpdating() {
  commitUpdating.classList.remove('visible');
  prUpdating.classList.remove('visible');
}

function updateSummary(data) {
  if (data.commit_message) {
    commitContent.textContent = data.commit_message;
  }
  if (data.pr_description) {
    prContent.textContent = data.pr_description;
  }
  hideSummaryUpdating();
}

document.getElementById('btnCommit').addEventListener('click', togglePanel);
document.getElementById('btnPR').addEventListener('click', togglePanel);

// Copy buttons
function setupCopy(btnId, contentId) {
  document.getElementById(btnId).addEventListener('click', (e) => {
    e.stopPropagation();
    const text = document.getElementById(contentId).textContent;
    navigator.clipboard.writeText(text).then(() => {
      const btn = document.getElementById(btnId);
      btn.classList.add('copied');
      btn.textContent = 'Copied!';
      setTimeout(() => { btn.classList.remove('copied'); btn.textContent = 'Copy'; }, 1500);
    });
  });
}
setupCopy('copyCommit', 'commitContent');
setupCopy('copyPR', 'prContent');

// Load initial summary
async function loadSummary() {
  try {
    const resp = await fetch('/summary.json');
    const data = await resp.json();
    if (data.commit_message || data.pr_description) {
      updateSummary(data);
    }
  } catch (err) {}
}

// Boot
loadInitialData().then(() => { connectSSE(); loadSummary(); });
</script>
</body>
</html>
'''


def write_pid(port: int):
    """Write PID file for the server."""
    ensure_dirs()
    SERVER_PID_FILE.write_text(json.dumps({
        "pid": os.getpid(),
        "port": port,
        "started_at": datetime.now().isoformat(),
    }), encoding="utf-8")


def read_pid() -> dict | None:
    """Read the PID file."""
    if not SERVER_PID_FILE.exists():
        return None
    try:
        return json.loads(SERVER_PID_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def is_server_running() -> tuple[bool, dict | None]:
    """Check if the server is currently running."""
    info = read_pid()
    if not info:
        return False, None
    pid = info.get("pid")
    if not pid:
        return False, None
    try:
        os.kill(pid, 0)  # Check if process exists
        return True, info
    except (ProcessLookupError, PermissionError):
        SERVER_PID_FILE.unlink(missing_ok=True)
        return False, None


def stop_server():
    """Stop the running server."""
    running, info = is_server_running()
    if not running:
        print("No server running.")
        return False
    pid = info["pid"]
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"Server (PID {pid}) stopped.")
        SERVER_PID_FILE.unlink(missing_ok=True)
        return True
    except (ProcessLookupError, PermissionError) as e:
        print(f"Could not stop server: {e}", file=sys.stderr)
        SERVER_PID_FILE.unlink(missing_ok=True)
        return False


def start_server(port: int, session_path: Path = None, foreground: bool = False):
    """Start the live changelog server."""
    global _jsonl_path

    if session_path:
        _jsonl_path = session_path
    else:
        _jsonl_path = CURRENT_SESSION

    # Check if already running
    running, info = is_server_running()
    if running:
        existing_port = info.get("port", "?")
        print(f"Server already running at http://localhost:{existing_port} (PID {info['pid']})")
        return

    actual_port = find_free_port(port)

    if foreground:
        _run_server(actual_port)
    else:
        # Fork to background
        pid = os.fork()
        if pid > 0:
            # Parent process
            time.sleep(0.5)
            print(f"Live changelog server started at http://localhost:{actual_port}")
            print(f"Watching: {_jsonl_path}")
            return
        else:
            # Child process — daemonize
            os.setsid()
            # Redirect stdout/stderr to devnull
            devnull = os.open(os.devnull, os.O_RDWR)
            os.dup2(devnull, 0)
            os.dup2(devnull, 1)
            os.dup2(devnull, 2)
            os.close(devnull)
            _run_server(actual_port)


def _run_server(port: int):
    """Internal: run the HTTP server (blocking)."""
    write_pid(port)

    # Handle clean shutdown
    def shutdown_handler(signum, frame):
        SERVER_PID_FILE.unlink(missing_ok=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)

    # Start file watcher thread
    watcher = threading.Thread(target=file_watcher, daemon=True)
    watcher.start()

    # Start HTTP server
    class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True

    server = ThreadingHTTPServer(("127.0.0.1", port), ChangelogHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        SERVER_PID_FILE.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="Live changelog server with SSE")
    parser.add_argument("--port", type=int, default=None, help="Server port (default: 8877)")
    parser.add_argument("--session", type=str, default=None,
                        help="Session to serve ('last', index, or path). Default: current session")
    parser.add_argument("--stop", action="store_true", help="Stop running server")
    parser.add_argument("--status", action="store_true", help="Check if server is running")
    parser.add_argument("--foreground", action="store_true", help="Run in foreground (don't daemonize)")
    parser.add_argument("--open", action="store_true", help="Open browser after starting")
    args = parser.parse_args()

    ensure_dirs()
    cfg = load_config()
    port = args.port or cfg.get("server_port", 8877)

    if args.stop:
        stop_server()
        return

    if args.status:
        running, info = is_server_running()
        if running:
            print(f"Server running at http://localhost:{info.get('port', '?')} (PID {info['pid']})")
        else:
            print("No server running.")
        return

    # Resolve session path
    session_path = None
    if args.session:
        if Path(args.session).exists():
            session_path = Path(args.session)
        else:
            # Use session_manager to resolve
            from session_manager import get_session_path
            session_path = get_session_path(args.session)
            if not session_path:
                print(f"Session '{args.session}' not found.", file=sys.stderr)
                sys.exit(1)

    start_server(port, session_path, foreground=args.foreground)

    if args.open:
        import webbrowser
        actual_port = port
        info = read_pid()
        if info:
            actual_port = info.get("port", port)
        webbrowser.open(f"http://localhost:{actual_port}")


if __name__ == "__main__":
    main()
