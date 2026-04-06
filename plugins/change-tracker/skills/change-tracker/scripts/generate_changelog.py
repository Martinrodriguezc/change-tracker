#!/usr/bin/env python3
"""Generate a standalone HTML diff viewer from a change-tracker JSON changelog.

Usage:
    python3 generate_changelog.py /tmp/claude-changes-XXX.json
    python3 generate_changelog.py /tmp/claude-changes-XXX.json --output /tmp/my-report.html
    python3 generate_changelog.py /tmp/claude-changes-XXX.json --no-open
"""
import argparse
import json
import sys
import difflib
import webbrowser
import html as html_module
from pathlib import Path
from datetime import datetime
from collections import Counter, defaultdict


def compute_char_segments(old_text: str, new_text: str) -> tuple:
    """Compute character-level diff between two lines.

    Returns two lists of segments: (old_segments, new_segments).
    Each segment is {"text": str, "hl": bool} where hl=True means this part changed.
    """
    sm = difflib.SequenceMatcher(None, old_text, new_text)
    old_segs = []
    new_segs = []

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            old_segs.append({"text": old_text[i1:i2], "hl": False})
            new_segs.append({"text": new_text[j1:j2], "hl": False})
        elif tag == "replace":
            old_segs.append({"text": old_text[i1:i2], "hl": True})
            new_segs.append({"text": new_text[j1:j2], "hl": True})
        elif tag == "delete":
            old_segs.append({"text": old_text[i1:i2], "hl": True})
        elif tag == "insert":
            new_segs.append({"text": new_text[j1:j2], "hl": True})

    return old_segs, new_segs


def add_char_highlights(lines: list) -> list:
    """Post-process diff lines to add character-level highlights to remove/add pairs."""
    i = 0
    while i < len(lines):
        # Find consecutive blocks of removes followed by adds
        if lines[i]["type"] == "remove":
            removes = []
            j = i
            while j < len(lines) and lines[j]["type"] == "remove":
                removes.append(j)
                j += 1
            adds = []
            while j < len(lines) and lines[j]["type"] == "add":
                adds.append(j)
                j += 1

            # Pair up removes with adds for char-level diff
            pairs = min(len(removes), len(adds))
            for k in range(pairs):
                old_segs, new_segs = compute_char_segments(
                    lines[removes[k]]["text"],
                    lines[adds[k]]["text"]
                )
                lines[removes[k]]["segments"] = old_segs
                lines[adds[k]]["segments"] = new_segs

            i = j
        else:
            i += 1

    return lines


def compute_diff(old_text: str, new_text: str) -> list:
    """Compute unified diff and return structured line data with char-level highlights."""
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)

    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm="", n=2))
    if len(diff) < 3:
        # No differences or only header lines
        return []

    lines = []
    old_num = 0
    new_num = 0

    for raw_line in diff[2:]:  # Skip --- and +++ headers
        if raw_line.startswith("@@"):
            # Parse hunk header: @@ -old_start,old_count +new_start,new_count @@
            parts = raw_line.split()
            old_part = parts[1]  # e.g., -41,13
            new_part = parts[2]  # e.g., +41,13
            old_num = int(old_part.split(",")[0].lstrip("-"))
            new_num = int(new_part.split(",")[0].lstrip("+"))
            lines.append({
                "type": "header",
                "old_num": None,
                "new_num": None,
                "text": raw_line.strip(),
            })
        elif raw_line.startswith("-"):
            content = raw_line[1:]
            lines.append({
                "type": "remove",
                "old_num": old_num,
                "new_num": None,
                "text": content.rstrip("\n"),
            })
            old_num += 1
        elif raw_line.startswith("+"):
            content = raw_line[1:]
            lines.append({
                "type": "add",
                "old_num": None,
                "new_num": new_num,
                "text": content.rstrip("\n"),
            })
            new_num += 1
        elif raw_line.startswith(" "):
            content = raw_line[1:]
            lines.append({
                "type": "context",
                "old_num": old_num,
                "new_num": new_num,
                "text": content.rstrip("\n"),
            })
            old_num += 1
            new_num += 1
        else:
            # Handle lines without the standard prefix (e.g., "\ No newline at end of file")
            if raw_line.strip():
                lines.append({
                    "type": "context",
                    "old_num": None,
                    "new_num": None,
                    "text": raw_line.rstrip("\n"),
                })

    # Add character-level highlighting to paired remove/add lines
    lines = add_char_highlights(lines)

    return lines


def compute_stats(changes: list) -> dict:
    """Compute summary statistics."""
    files = set()
    lines_added = 0
    lines_removed = 0
    by_category = Counter()

    for change in changes:
        files.add(change.get("file", "unknown"))
        by_category[change.get("category", "other")] += 1

        old_text = change.get("old_text", "")
        new_text = change.get("new_text", "")
        old_lines = old_text.splitlines() if old_text else []
        new_lines = new_text.splitlines() if new_text else []

        diff = list(difflib.unified_diff(old_lines, new_lines, lineterm="", n=2))
        for line in diff[2:]:  # Skip headers
            if line.startswith("+") and not line.startswith("+++"):
                lines_added += 1
            elif line.startswith("-") and not line.startswith("---"):
                lines_removed += 1

    return {
        "files_changed": len(files),
        "total_edits": len(changes),
        "lines_added": lines_added,
        "lines_removed": lines_removed,
        "by_category": dict(by_category),
    }


def compute_common_prefix(paths: list) -> str:
    """Find the longest common directory prefix across all file paths."""
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


def build_embedded_data(changelog: dict) -> dict:
    """Process changelog into the data structure the HTML needs."""
    changes = changelog.get("changes", [])
    processed = []

    for change in changes:
        old_text = change.get("old_text", "")
        new_text = change.get("new_text", "")
        diff_lines = compute_diff(old_text, new_text)

        processed.append({
            "id": change.get("id", 0),
            "file": change.get("file", "unknown"),
            "type": change.get("type", "edit"),
            "reason": change.get("reason", ""),
            "category": change.get("category", "other"),
            "pros": change.get("pros", []),
            "cons": change.get("cons", []),
            "notes": change.get("notes", ""),
            "timestamp": change.get("timestamp", ""),
            "diff_lines": diff_lines,
        })

    # Build file list with counts
    file_counts = defaultdict(int)
    for c in processed:
        file_counts[c["file"]] += 1

    all_paths = [c["file"] for c in processed]
    prefix = compute_common_prefix(all_paths)
    prefix_len = len(prefix)

    for c in processed:
        c["display_file"] = c["file"][prefix_len:] if prefix_len else c["file"]

    files = [{"path": f, "count": c, "display": f[prefix_len:] if prefix_len else f} for f, c in file_counts.items()]

    # Collect all categories
    categories = sorted(set(c["category"] for c in processed))

    return {
        "task": changelog.get("task", ""),
        "timestamp": changelog.get("timestamp", ""),
        "stats": compute_stats(changes),
        "changes": processed,
        "files": files,
        "categories": categories,
    }


LIVE_META = '<meta http-equiv="refresh" content="3">'

LIVE_SCRIPT = r"""
// ── Live Mode: preserve UI state across auto-refreshes ──
window.addEventListener('beforeunload', () => {
  sessionStorage.setItem('ct-scroll', window.scrollY);
  const searchEl = document.getElementById('searchInput');
  if (searchEl) sessionStorage.setItem('ct-search', searchEl.value);
  sessionStorage.setItem('ct-filters', JSON.stringify([...activeCategories]));
  sessionStorage.setItem('ct-active-file', activeFile || '');
  sessionStorage.setItem('ct-focused-card', focusedCardIndex);
});
(function restoreState() {
  const scroll = sessionStorage.getItem('ct-scroll');
  const search = sessionStorage.getItem('ct-search');
  const filters = sessionStorage.getItem('ct-filters');
  const file = sessionStorage.getItem('ct-active-file');
  const focused = sessionStorage.getItem('ct-focused-card');

  if (search) {
    const el = document.getElementById('searchInput');
    if (el) { el.value = search; searchQuery = search.toLowerCase(); }
  }
  if (filters) {
    try { activeCategories = new Set(JSON.parse(filters)); } catch(e) {}
  }
  if (file) { activeFile = file || null; }
  if (focused) { focusedCardIndex = parseInt(focused) || -1; }

  // Re-render with restored state
  renderFileList();
  renderCategoryFilters();
  renderChanges();

  if (scroll) { requestAnimationFrame(() => window.scrollTo(0, parseInt(scroll))); }
  if (focusedCardIndex >= 0) { updateCardFocus(); }
})();
"""


def generate_html(changelog: dict, live: bool = False) -> str:
    """Build the complete standalone HTML string."""
    data = build_embedded_data(changelog)
    data_json = json.dumps(data, ensure_ascii=False, indent=2)

    html = HTML_TEMPLATE.replace("/*__CHANGELOG_DATA__*/", f"const CHANGELOG_DATA = {data_json};")
    html = html.replace("/*__LIVE_META__*/", LIVE_META if live else "")
    html = html.replace("/*__LIVE_SCRIPT__*/", LIVE_SCRIPT if live else "")
    return html


HTML_TEMPLATE = r'''<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
/*__LIVE_META__*/
<title>Change Tracker — Changelog Visual</title>
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

  /* Header */
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

  /* Stats badges */
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

  /* Theme toggle */
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

  /* Layout */
  .layout {
    display: flex;
    flex: 1;
    overflow: hidden;
  }

  /* Sidebar */
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

  /* Search */
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

  /* File tree */
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

  /* Category filters */
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

  /* PR Description section */
  .pr-section {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    margin-bottom: 20px;
    box-shadow: var(--shadow);
    overflow: hidden;
  }
  .pr-header {
    padding: 14px 18px;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .pr-header-left {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .pr-header h3 {
    font-size: 13px;
    font-weight: 600;
    color: var(--text);
    margin: 0;
  }
  .pr-header .pr-icon {
    font-size: 16px;
    opacity: 0.6;
  }
  .pr-tabs {
    display: flex;
    gap: 0;
    border-bottom: 1px solid var(--border);
  }
  .pr-tab {
    padding: 8px 16px;
    font-size: 12px;
    font-weight: 600;
    color: var(--text-muted);
    background: none;
    border: none;
    cursor: pointer;
    border-bottom: 2px solid transparent;
    transition: all 0.15s;
  }
  .pr-tab:hover { color: var(--text); }
  .pr-tab.active {
    color: var(--accent);
    border-bottom-color: var(--accent);
  }
  .pr-content {
    padding: 16px 18px;
    font-family: var(--mono);
    font-size: 12.5px;
    line-height: 1.6;
    white-space: pre-wrap;
    color: var(--text);
    max-height: 300px;
    overflow-y: auto;
  }
  .pr-copy-btn {
    padding: 5px 12px;
    font-size: 11px;
    font-weight: 600;
    background: var(--surface-hover);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text-muted);
    cursor: pointer;
    transition: all 0.15s;
  }
  .pr-copy-btn:hover { background: var(--border); color: var(--text); }
  .pr-copy-btn.copied { background: var(--green-bg); color: var(--green); border-color: var(--green-border); }

  /* Main content */
  .main {
    flex: 1;
    overflow-y: auto;
    padding: 24px 32px;
  }

  /* Change card */
  .change-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    margin-bottom: 20px;
    box-shadow: var(--shadow);
    overflow: hidden;
  }
  .change-card.hidden { display: none; }

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
  }
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

  /* Pros, Cons, Notes */
  .change-insights {
    padding: 0 18px 14px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .insight-item {
    display: flex;
    align-items: flex-start;
    gap: 6px;
    font-size: 13px;
    line-height: 1.4;
  }
  .insight-icon {
    flex-shrink: 0;
    font-weight: 700;
    width: 18px;
    text-align: center;
  }
  .insight-item.pro .insight-icon { color: var(--green); }
  .insight-item.pro .insight-text { color: var(--green); }
  .insight-item.con .insight-icon { color: var(--red); }
  .insight-item.con .insight-text { color: var(--red); }
  .insight-note {
    font-size: 13px;
    line-height: 1.4;
    color: var(--text-muted);
    padding: 8px 12px;
    background: var(--surface-hover);
    border-radius: 6px;
    border-left: 3px solid var(--accent);
  }

  /* Diff table */
  .diff-container {
    overflow-x: auto;
  }
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

  /* Character-level highlights */
  .char-hl-add { background: rgba(46,160,67,0.3); border-radius: 2px; padding: 0 1px; }
  .char-hl-remove { background: rgba(248,81,73,0.3); border-radius: 2px; padding: 0 1px; }
  html.dark .char-hl-add { background: rgba(46,160,67,0.4); }
  html.dark .char-hl-remove { background: rgba(248,81,73,0.4); }
  .diff-table tr.diff-header {
    background: var(--surface-hover);
    color: var(--text-muted);
    font-size: 11px;
  }
  .diff-table tr.diff-header td { padding: 4px 12px; }

  /* Collapse toggle for large diffs */
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

  /* Empty state */
  .empty-state {
    text-align: center;
    padding: 64px 24px;
    color: var(--text-muted);
  }
  .empty-state p { font-size: 15px; margin-top: 8px; }
  .change-card.focused { outline: 2px solid var(--accent); outline-offset: -2px; }

  /* Responsive */
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
    <span class="header-task" id="taskTitle"></span>
  </div>
  <div class="header-right">
    <span class="stat-badge files" id="statFiles"></span>
    <span class="stat-badge added" id="statAdded"></span>
    <span class="stat-badge removed" id="statRemoved"></span>
    <button class="theme-toggle" id="themeToggle" title="Toggle theme">&#9789;</button>
    <button class="theme-toggle" id="exportBtn" title="Export as Markdown">&#8615;</button>
  </div>
</div>

<div class="layout">
  <div class="sidebar">
    <div class="sidebar-section">
      <h3>Buscar</h3>
      <input type="text" class="search-input" id="searchInput" placeholder="Buscar en archivos, codigo, explicaciones...">
    </div>

    <div class="sidebar-section" id="categorySection">
      <h3>Categorias</h3>
      <div class="category-filters" id="categoryFilters"></div>
    </div>

    <div class="sidebar-section" style="border-bottom: none; padding-bottom: 0;">
      <h3>Archivos</h3>
    </div>
    <div class="file-list" id="fileList"></div>
  </div>

  <div class="main" id="mainScroll">
    <div class="pr-section" id="prSection"></div>
    <div id="mainContent"></div>
  </div>
</div>

<script>
/*__CHANGELOG_DATA__*/

// State
let activeFile = null;
let activeCategories = new Set(CHANGELOG_DATA.categories);
let searchQuery = '';

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

// Populate header
document.getElementById('taskTitle').textContent = CHANGELOG_DATA.task;
const stats = CHANGELOG_DATA.stats;
document.getElementById('statFiles').textContent = stats.files_changed + ' archivo' + (stats.files_changed !== 1 ? 's' : '');
document.getElementById('statAdded').textContent = '+' + stats.lines_added + ' lineas';
document.getElementById('statRemoved').textContent = '-' + stats.lines_removed + ' lineas';

// Populate file list
function renderFileList() {
  const container = document.getElementById('fileList');
  container.innerHTML = '';
  CHANGELOG_DATA.files.forEach(f => {
    const el = document.createElement('div');
    el.className = 'file-item' + (activeFile === f.path ? ' active' : '');
    const displayName = f.display || f.path;
    const parts = displayName.split('/');
    const shortPath = parts.length > 3 ? '.../' + parts.slice(-3).join('/') : displayName;
    el.innerHTML = '<span class="file-name" title="' + escapeHtml(f.path) + '">' + escapeHtml(shortPath) + '</span>'
      + '<span class="file-count">' + f.count + '</span>';
    el.addEventListener('click', () => {
      activeFile = activeFile === f.path ? null : f.path;
      renderFileList();
      renderChanges();
    });
    container.appendChild(el);
  });
}

// Populate category filters
function renderCategoryFilters() {
  const container = document.getElementById('categoryFilters');
  container.innerHTML = '';
  CHANGELOG_DATA.categories.forEach(cat => {
    const count = CHANGELOG_DATA.changes.filter(c => c.category === cat).length;
    const label = document.createElement('label');
    label.className = 'category-filter';
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = activeCategories.has(cat);
    cb.addEventListener('change', () => {
      if (cb.checked) activeCategories.add(cat);
      else activeCategories.delete(cat);
      renderChanges();
    });
    label.appendChild(cb);
    const badge = document.createElement('span');
    badge.className = 'category-badge ' + cat;
    badge.textContent = cat + ' (' + count + ')';
    label.appendChild(badge);
    container.appendChild(label);
  });
}

// Search
document.getElementById('searchInput').addEventListener('input', e => {
  searchQuery = e.target.value.toLowerCase();
  renderChanges();
});

// Render changes
function renderChanges() {
  const container = document.getElementById('mainContent');
  container.innerHTML = '';

  const filtered = CHANGELOG_DATA.changes.filter(c => {
    if (!activeCategories.has(c.category)) return false;
    if (activeFile && c.file !== activeFile) return false;
    if (searchQuery) {
      const diffText = (c.diff_lines || []).map(l => l.text).join(' ');
      const prosText = (c.pros || []).join(' ');
      const consText = (c.cons || []).join(' ');
      const haystack = (c.file + ' ' + c.reason + ' ' + (c.notes || '') + ' ' + prosText + ' ' + consText + ' ' + diffText).toLowerCase();
      if (!haystack.includes(searchQuery)) return false;
    }
    return true;
  });

  if (filtered.length === 0) {
    container.innerHTML = '<div class="empty-state"><p>No hay cambios que coincidan con los filtros.</p></div>';
    return;
  }

  filtered.forEach(change => {
    const card = document.createElement('div');
    card.className = 'change-card';
    card.dataset.id = change.id;

    // Header
    const header = document.createElement('div');
    header.className = 'change-header';

    const headerLeft = document.createElement('div');
    headerLeft.className = 'change-header-left';

    const fileEl = document.createElement('div');
    fileEl.className = 'change-file';
    fileEl.textContent = change.display_file || change.file;
    fileEl.title = change.file;
    headerLeft.appendChild(fileEl);

    if (change.reason) {
      const reasonEl = document.createElement('div');
      reasonEl.className = 'change-reason';
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

    const badge = document.createElement('span');
    badge.className = 'category-badge ' + change.category;
    badge.textContent = change.category;
    meta.appendChild(badge);

    if (change.type === 'create') {
      const newBadge = document.createElement('span');
      newBadge.className = 'new-file-badge';
      newBadge.textContent = 'Nuevo';
      meta.appendChild(newBadge);
    }

    header.appendChild(headerLeft);
    header.appendChild(meta);
    card.appendChild(header);

    // Pros, Cons, Notes
    const hasPros = change.pros && change.pros.length > 0;
    const hasCons = change.cons && change.cons.length > 0;
    const hasNotes = change.notes && change.notes.trim();
    if (hasPros || hasCons || hasNotes) {
      const insights = document.createElement('div');
      insights.className = 'change-insights';

      if (hasPros) {
        change.pros.forEach(pro => {
          const item = document.createElement('div');
          item.className = 'insight-item pro';
          item.innerHTML = '<span class="insight-icon">\u2713</span><span class="insight-text">' + escapeHtml(pro) + '</span>';
          insights.appendChild(item);
        });
      }
      if (hasCons) {
        change.cons.forEach(con => {
          const item = document.createElement('div');
          item.className = 'insight-item con';
          item.innerHTML = '<span class="insight-icon">\u2717</span><span class="insight-text">' + escapeHtml(con) + '</span>';
          insights.appendChild(item);
        });
      }
      if (hasNotes) {
        const note = document.createElement('div');
        note.className = 'insight-note';
        note.textContent = change.notes;
        insights.appendChild(note);
      }

      card.appendChild(insights);
    }

    // Diff
    const diffLines = change.diff_lines || [];
    const isLarge = diffLines.length > 100;
    const diffContainer = document.createElement('div');
    diffContainer.className = 'diff-container';

    if (diffLines.length === 0) {
      diffContainer.innerHTML = '<div style="padding: 16px; color: var(--text-muted); font-size: 13px;">Sin diferencias detectadas.</div>';
    } else {
      const table = document.createElement('table');
      table.className = 'diff-table';

      const linesToShow = isLarge ? diffLines.slice(0, 100) : diffLines;
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
        if (line.type === 'add') sign.textContent = '+';
        else if (line.type === 'remove') sign.textContent = '-';
        else if (line.type === 'header') sign.textContent = '';
        else sign.textContent = ' ';

        const content = document.createElement('td');
        content.className = 'line-content';
        if (line.segments && line.segments.length > 0) {
          const hlClass = line.type === 'add' ? 'char-hl-add' : 'char-hl-remove';
          line.segments.forEach(seg => {
            if (seg.hl) {
              const span = document.createElement('span');
              span.className = hlClass;
              span.textContent = seg.text;
              content.appendChild(span);
            } else {
              content.appendChild(document.createTextNode(seg.text));
            }
          });
        } else {
          content.textContent = line.text;
        }

        tr.appendChild(oldNum);
        tr.appendChild(newNum);
        tr.appendChild(sign);
        tr.appendChild(content);
        table.appendChild(tr);
      });

      diffContainer.appendChild(table);

      if (isLarge) {
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
                + '<td class="line-content">' + renderLineContentHtml(line) + '</td>';
              table.appendChild(tr);
            });
            toggle.textContent = 'Colapsar diff';
            expanded = true;
          } else {
            table.innerHTML = '';
            diffLines.slice(0, 100).forEach(line => {
              const tr = document.createElement('tr');
              tr.className = 'diff-' + line.type;
              tr.innerHTML =
                '<td class="line-num">' + (line.old_num != null ? line.old_num : '') + '</td>'
                + '<td class="line-num">' + (line.new_num != null ? line.new_num : '') + '</td>'
                + '<td class="line-sign">' + (line.type === 'add' ? '+' : line.type === 'remove' ? '-' : ' ') + '</td>'
                + '<td class="line-content">' + renderLineContentHtml(line) + '</td>';
              table.appendChild(tr);
            });
            toggle.textContent = 'Mostrar diff completo (' + diffLines.length + ' lineas)';
            expanded = false;
          }
        });
        diffContainer.appendChild(toggle);
      }
    }

    card.appendChild(diffContainer);
    container.appendChild(card);
  });
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function renderLineContentHtml(line) {
  if (line.segments && line.segments.length > 0) {
    const hlClass = line.type === 'add' ? 'char-hl-add' : 'char-hl-remove';
    return line.segments.map(seg =>
      seg.hl ? '<span class="' + hlClass + '">' + escapeHtml(seg.text) + '</span>' : escapeHtml(seg.text)
    ).join('');
  }
  return escapeHtml(line.text);
}

// Keyboard navigation
let focusedCardIndex = -1;

function updateCardFocus() {
  const cards = document.querySelectorAll('.change-card:not(.hidden)');
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

  const cards = document.querySelectorAll('.change-card:not(.hidden)');
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

// Export to Markdown
document.getElementById('exportBtn').addEventListener('click', () => {
  let md = '# Changelog: ' + CHANGELOG_DATA.task + '\n\n';
  md += '**Date:** ' + new Date(CHANGELOG_DATA.timestamp).toLocaleDateString() + '\n';
  md += '**Stats:** ' + CHANGELOG_DATA.stats.files_changed + ' files, +'
    + CHANGELOG_DATA.stats.lines_added + '/-' + CHANGELOG_DATA.stats.lines_removed + ' lines\n\n---\n\n';

  CHANGELOG_DATA.changes.forEach(c => {
    const displayFile = c.display_file || c.file;
    md += '## #' + c.id + ' ' + displayFile + ' [' + (c.category || 'other').toUpperCase() + ']\n\n';
    if (c.reason) md += c.reason + '\n\n';
    if (c.pros && c.pros.length) {
      c.pros.forEach(p => { md += '- **PRO:** ' + p + '\n'; });
      md += '\n';
    }
    if (c.cons && c.cons.length) {
      c.cons.forEach(p => { md += '- **CON:** ' + p + '\n'; });
      md += '\n';
    }
    if (c.notes) md += '> ' + c.notes + '\n\n';
    if (c.diff_lines && c.diff_lines.length) {
      md += '```diff\n';
      c.diff_lines.forEach(l => {
        if (l.type === 'add') md += '+' + l.text + '\n';
        else if (l.type === 'remove') md += '-' + l.text + '\n';
        else if (l.type === 'header') md += l.text + '\n';
        else md += ' ' + l.text + '\n';
      });
      md += '```\n\n';
    }
    md += '---\n\n';
  });

  const blob = new Blob([md], { type: 'text/markdown' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'changelog-' + new Date().toISOString().slice(0, 10) + '.md';
  a.click();
  URL.revokeObjectURL(url);
});

// ── PR / Commit Description Generator ──

// Classify a line of code by its semantic type
function classifyLine(line) {
  const t = line.trim();
  if (!t) return null;
  if (/^\/\/|^\/\*|^\*|^#/.test(t)) return 'comment';
  if (/^import\s|^from\s.*import|^require\(|^export\s/.test(t)) return 'import';
  if (/^(export\s+)?(function|const|let|var|class|interface|type|enum)\s/.test(t)) return 'declaration';
  if (/^(async\s+)?function\s|=>\s*\{/.test(t)) return 'function';
  if (/className=|style=|css|tailwind|bg-|text-|flex|grid|rounded|border|shadow|padding|margin/i.test(t)) return 'styling';
  if (/useState|useEffect|useRef|useMemo|useCallback|useContext|useQuery|useMutation/.test(t)) return 'hook';
  if (/\.test\(|\.spec\(|describe\(|it\(|expect\(|assert/.test(t)) return 'test';
  if (/router\.|route|path:|redirect|navigate|middleware|endpoint/i.test(t)) return 'routing';
  if (/catch\(|throw\s|Error\(|reject\(|\.error|console\.error/.test(t)) return 'error-handling';
  if (/config|\.env|setting|option|flag|toggle|enable|disable/i.test(t)) return 'config';
  if (/prisma|query|where:|select:|include:|findMany|findUnique|create\(|update\(|delete\(/.test(t)) return 'database';
  if (/fetch\(|axios|\.get\(|\.post\(|\.put\(|\.delete\(|api|endpoint/i.test(t)) return 'api';
  if (/return\s|return\(/.test(t)) return 'return';
  return 'logic';
}

// Get human-readable area from file path
function describeArea(filePath) {
  const p = filePath.toLowerCase();
  if (p.includes('/components/')) return 'UI component';
  if (p.includes('/pages/') || p.includes('/views/')) return 'page';
  if (p.includes('/hooks/')) return 'custom hook';
  if (p.includes('/services/')) return 'service layer';
  if (p.includes('/routers/') || p.includes('/routes/')) return 'API route';
  if (p.includes('/controllers/')) return 'controller';
  if (p.includes('/middleware/')) return 'middleware';
  if (p.includes('/validators/')) return 'validator';
  if (p.includes('/utils/') || p.includes('/helpers/')) return 'utility';
  if (p.includes('/types/') || p.includes('.d.ts')) return 'type definition';
  if (p.includes('/styles/') || p.endsWith('.css')) return 'stylesheet';
  if (p.includes('/config/') || p.includes('.config.')) return 'configuration';
  if (p.includes('prisma')) return 'database schema';
  if (p.includes('test') || p.includes('spec')) return 'test';
  if (p.includes('.json')) return 'config file';
  if (p.includes('.md')) return 'documentation';
  if (p.includes('.sh')) return 'shell script';
  if (p.includes('.py')) return 'Python script';
  return 'source file';
}

// Analyze all diffs for a file and produce a semantic summary
function analyzeFile(file, edits) {
  const types = {};
  let totalAdded = 0, totalRemoved = 0;

  edits.forEach(e => {
    const dl = e.diff_lines || [];
    dl.forEach(l => {
      if (l.type === 'add') {
        totalAdded++;
        const cls = classifyLine(l.text);
        if (cls) types[cls] = (types[cls] || 0) + 1;
      } else if (l.type === 'remove') {
        totalRemoved++;
      }
    });
  });

  const isCreate = edits.some(e => e.type === 'create');
  const isRewrite = edits.some(e => e.type === 'rewrite');
  const area = describeArea(file);
  const sorted = Object.entries(types).sort((a, b) => b[1] - a[1]);
  const dominant = sorted[0] ? sorted[0][0] : 'logic';

  // Build a natural description
  const parts = [];

  if (isCreate) {
    parts.push('Created new ' + area + ' (' + totalAdded + ' lines)');
  } else if (isRewrite) {
    parts.push('Rewrote ' + area + ' (' + totalAdded + ' lines added, ' + totalRemoved + ' removed)');
  } else {
    // Describe by dominant change type
    const actions = [];
    if (types['comment']) actions.push('updated comments/documentation');
    if (types['import']) actions.push('modified imports');
    if (types['declaration'] || types['function']) actions.push('changed function/variable declarations');
    if (types['styling']) actions.push('updated styling/layout');
    if (types['hook']) actions.push('modified React hooks');
    if (types['routing']) actions.push('updated routing');
    if (types['config']) actions.push('changed configuration');
    if (types['database']) actions.push('modified database queries');
    if (types['api']) actions.push('updated API calls');
    if (types['error-handling']) actions.push('improved error handling');
    if (types['test']) actions.push('updated tests');
    if (types['logic'] && !actions.length) actions.push('updated business logic');

    if (actions.length) {
      parts.push(actions.slice(0, 3).join(', ') + ' in ' + area);
    } else {
      parts.push('edited ' + area + ' (' + edits.length + ' change' + (edits.length > 1 ? 's' : '') + ')');
    }

    if (totalAdded + totalRemoved > 0) {
      parts.push('+' + totalAdded + '/-' + totalRemoved + ' lines');
    }
  }

  return { description: parts[0], stats: parts[1] || '', dominant, isCreate, isRewrite, totalAdded, totalRemoved };
}

function generateDescriptions() {
  const changes = CHANGELOG_DATA.changes;
  if (!changes.length) return;

  const files = [...new Set(changes.map(c => c.file))];
  const prefix = computePrefix(files);

  // Group changes by file (using short path)
  const byFile = {};
  changes.forEach(c => {
    const short = c.file.slice(prefix.length) || c.file;
    if (!byFile[short]) byFile[short] = { edits: [], fullPath: c.file };
    byFile[short].edits.push(c);
  });

  // Analyze each file
  const analyses = {};
  Object.entries(byFile).forEach(([file, data]) => {
    analyses[file] = analyzeFile(data.fullPath, data.edits);
  });

  // Detect overall intent
  const allDominant = Object.values(analyses).map(a => a.dominant);
  const hasNewFiles = Object.values(analyses).some(a => a.isCreate);
  const hasRewrites = Object.values(analyses).some(a => a.isRewrite);
  const dominantCounts = {};
  allDominant.forEach(d => dominantCounts[d] = (dominantCounts[d] || 0) + 1);
  const topDominant = Object.entries(dominantCounts).sort((a,b) => b[1]-a[1])[0][0];

  // Choose commit prefix based on what actually changed
  let commitPrefix = 'chore';
  if (hasNewFiles) commitPrefix = 'feat';
  else if (topDominant === 'styling') commitPrefix = 'style';
  else if (topDominant === 'comment') commitPrefix = 'docs';
  else if (topDominant === 'test') commitPrefix = 'test';
  else if (topDominant === 'config') commitPrefix = 'chore';
  else if (topDominant === 'error-handling') commitPrefix = 'fix';
  else commitPrefix = 'feat';

  const task = CHANGELOG_DATA.task || '';
  const stats = CHANGELOG_DATA.stats || {};

  // ── Commit message ──
  const commitLines = [];

  // Title
  if (task && task !== 'Session changes') {
    commitLines.push(commitPrefix + ': ' + task);
  } else {
    // Generate title from analyses
    const summaries = Object.values(analyses).map(a => a.description);
    if (summaries.length === 1) {
      commitLines.push(commitPrefix + ': ' + summaries[0]);
    } else {
      // Find common theme
      const areas = [...new Set(Object.entries(byFile).map(([_, d]) => describeArea(d.fullPath)))];
      if (areas.length === 1) {
        commitLines.push(commitPrefix + ': update ' + areas[0] + ' (' + files.length + ' files)');
      } else {
        commitLines.push(commitPrefix + ': update ' + areas.slice(0, 3).join(', '));
      }
    }
  }
  commitLines.push('');

  // Body: one line per file with semantic description
  Object.entries(analyses).forEach(([file, analysis]) => {
    const line = analysis.stats
      ? '- ' + file + ': ' + analysis.description + ' (' + analysis.stats + ')'
      : '- ' + file + ': ' + analysis.description;
    commitLines.push(line);
  });

  // ── PR description ──
  const prLines = [];

  // What
  prLines.push('## What');
  prLines.push('');
  if (task && task !== 'Session changes') {
    prLines.push(task);
  } else {
    const summaries = Object.values(analyses).map(a => a.description);
    prLines.push(summaries.join('. ') + '.');
  }
  prLines.push('');
  prLines.push('**Scope:** ' + files.length + ' file(s) | +' + (stats.lines_added || 0) + '/-' + (stats.lines_removed || 0) + ' lines');
  prLines.push('');

  // Why (from reasons if available)
  const allReasons = changes.map(c => c.reason).filter(Boolean);
  if (allReasons.length) {
    prLines.push('## Why');
    prLines.push('');
    [...new Set(allReasons)].forEach(r => prLines.push('- ' + r));
    prLines.push('');
  }

  // How — semantic per-file breakdown
  prLines.push('## Changes');
  prLines.push('');
  Object.entries(analyses).forEach(([file, analysis]) => {
    let line = '- **' + file + '**: ' + analysis.description;
    if (analysis.stats) line += ' (' + analysis.stats + ')';
    prLines.push(line);
  });
  prLines.push('');

  // Trade-offs
  const allCons = changes.flatMap(c => c.cons || []);
  if (allCons.length) {
    prLines.push('## Trade-offs');
    prLines.push('');
    allCons.forEach(con => prLines.push('- ' + con));
    prLines.push('');
  }

  // Notes
  const allNotes = changes.map(c => (c.notes || '').trim()).filter(Boolean);
  if (allNotes.length) {
    prLines.push('## Notes');
    prLines.push('');
    allNotes.forEach(n => prLines.push('- ' + n));
    prLines.push('');
  }

  // Test plan
  prLines.push('## Test plan');
  prLines.push('');
  prLines.push('- [ ] Verify changes work as described');
  prLines.push('- [ ] No regressions in affected areas');

  return { commit: commitLines.join('\n'), pr: prLines.join('\n') };
}

function computePrefix(paths) {
  if (!paths.length) return '';
  const parts = paths.map(p => p.split('/'));
  const prefix = [];
  for (let i = 0; i < parts[0].length; i++) {
    const seg = parts[0][i];
    if (parts.every(p => p[i] === seg)) prefix.push(seg);
    else break;
  }
  const r = prefix.join('/');
  return r ? r + '/' : '';
}

function renderPrSection() {
  const section = document.getElementById('prSection');
  const desc = generateDescriptions();
  if (!desc) { section.style.display = 'none'; return; }

  const tabs = { commit: desc.commit, pr: desc.pr };
  let activeTab = sessionStorage.getItem('ct-pr-tab') || 'commit';

  section.innerHTML = '';

  const header = document.createElement('div');
  header.className = 'pr-header';
  const headerLeft = document.createElement('div');
  headerLeft.className = 'pr-header-left';
  headerLeft.innerHTML = '<span class="pr-icon">\u{1F4CB}</span><h3>Commit / PR Description</h3>';
  const copyBtn = document.createElement('button');
  copyBtn.className = 'pr-copy-btn';
  copyBtn.textContent = 'Copiar';
  header.appendChild(headerLeft);
  header.appendChild(copyBtn);
  section.appendChild(header);

  const tabBar = document.createElement('div');
  tabBar.className = 'pr-tabs';
  const commitTab = document.createElement('button');
  commitTab.className = 'pr-tab' + (activeTab === 'commit' ? ' active' : '');
  commitTab.textContent = 'Commit message';
  const prTab = document.createElement('button');
  prTab.className = 'pr-tab' + (activeTab === 'pr' ? ' active' : '');
  prTab.textContent = 'PR description';
  tabBar.appendChild(commitTab);
  tabBar.appendChild(prTab);
  section.appendChild(tabBar);

  const content = document.createElement('div');
  content.className = 'pr-content';
  content.textContent = tabs[activeTab];
  section.appendChild(content);

  function switchTab(tab) {
    activeTab = tab;
    sessionStorage.setItem('ct-pr-tab', tab);
    commitTab.className = 'pr-tab' + (tab === 'commit' ? ' active' : '');
    prTab.className = 'pr-tab' + (tab === 'pr' ? ' active' : '');
    content.textContent = tabs[tab];
    copyBtn.textContent = 'Copiar';
    copyBtn.className = 'pr-copy-btn';
  }
  commitTab.addEventListener('click', () => switchTab('commit'));
  prTab.addEventListener('click', () => switchTab('pr'));

  copyBtn.addEventListener('click', () => {
    navigator.clipboard.writeText(tabs[activeTab]).then(() => {
      copyBtn.textContent = '\u2713 Copiado';
      copyBtn.className = 'pr-copy-btn copied';
      setTimeout(() => { copyBtn.textContent = 'Copiar'; copyBtn.className = 'pr-copy-btn'; }, 2000);
    });
  });
}

// Initial render
renderPrSection();
renderFileList();
renderCategoryFilters();
renderChanges();

/*__LIVE_SCRIPT__*/
</script>
</body>
</html>
'''


EXPLANATIONS_FILE = Path("/tmp/claude-change-tracker-explanations.jsonl")


def load_explanations() -> dict:
    """Load Claude-generated explanations keyed by change ID."""
    explanations = {}
    if not EXPLANATIONS_FILE.exists():
        return explanations
    try:
        for line in EXPLANATIONS_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                explanations[entry["id"]] = entry.get("explanation", "")
            except (json.JSONDecodeError, KeyError):
                continue
    except Exception:
        pass
    return explanations


def load_changelog(path: Path) -> dict:
    """Load changelog from JSON or JSONL format."""
    text = path.read_text(encoding="utf-8").strip()

    # Try JSON first (legacy format — single JSON object with "changes" key)
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and "changes" in parsed:
                return parsed
        except json.JSONDecodeError:
            pass  # Fall through to JSONL parsing

    # Load Claude-generated explanations
    explanations = load_explanations()

    # JSONL format: one JSON object per line (from the hook)
    changes = []
    for i, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            entry.setdefault("id", i)
            # Use Claude-generated explanation if available
            if i in explanations and not entry.get("reason"):
                entry["reason"] = explanations[i]
            entry.setdefault("reason", "")
            entry.setdefault("category", "other")
            entry.setdefault("pros", [])
            entry.setdefault("cons", [])
            entry.setdefault("notes", "")
            changes.append(entry)
        except json.JSONDecodeError:
            continue

    return {
        "task": "Session changes",
        "timestamp": changes[0]["timestamp"] if changes else datetime.now().isoformat(),
        "changes": changes,
    }


def main():
    parser = argparse.ArgumentParser(description="Generate HTML diff viewer from change-tracker changelog")
    parser.add_argument("changelog", type=Path, nargs="?", default=Path("/tmp/claude-change-tracker.jsonl"),
                        help="Path to changelog JSON/JSONL file (default: /tmp/claude-change-tracker.jsonl)")
    parser.add_argument("--output", "-o", type=Path, default=None, help="Output HTML path")
    parser.add_argument("--no-open", action="store_true", help="Don't open in browser")
    parser.add_argument("--live", action="store_true", help="Live mode: fixed path + auto-refresh HTML")
    parser.add_argument("--task", "-t", type=str, default=None, help="Override task description")
    args = parser.parse_args()

    if not args.changelog.exists():
        print(f"Error: {args.changelog} not found", file=sys.stderr)
        sys.exit(1)

    data = load_changelog(args.changelog)
    if args.task:
        data["task"] = args.task
    html_content = generate_html(data, live=args.live)

    if args.live:
        output = args.output or Path("/tmp/claude-changelog-live.html")
    else:
        output = args.output or Path(f"/tmp/claude-changelog-{datetime.now().strftime('%Y%m%d-%H%M%S')}.html")
    output.write_text(html_content, encoding="utf-8")

    print(f"Changelog generado: {output}")
    print(f"  {len(data.get('changes', []))} cambios en {len(set(c.get('file','') for c in data.get('changes',[])))} archivos")

    if not args.no_open:
        webbrowser.open(f"file://{output.resolve()}")

    return str(output)


if __name__ == "__main__":
    main()
