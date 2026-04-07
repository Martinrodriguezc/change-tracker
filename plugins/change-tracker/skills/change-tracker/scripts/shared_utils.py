#!/usr/bin/env python3
"""Shared utilities for change-tracker scripts.

Centralizes duplicated logic: explanation loading, JSONL parsing,
path prefix computation, and clipboard operations.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

EXPLANATIONS_FILE = Path("/tmp/claude-change-tracker-explanations.jsonl")
SUMMARY_FILE = Path("/tmp/claude-change-tracker-summary.json")
PRE_CAPTURE_DIR = Path("/tmp/claude-change-tracker-pre")
LAST_CHANGE_FILE = Path("/tmp/claude-change-tracker-last-change.json")


def load_explanations(path: Path = EXPLANATIONS_FILE) -> dict[int, dict]:
    """Load Claude-generated explanations keyed by change ID."""
    if not path.exists():
        return {}
    explanations = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                explanations[entry["id"]] = {
                    "explanation": entry.get("explanation", ""),
                    "category": entry.get("category", ""),
                }
            except (json.JSONDecodeError, KeyError):
                continue
    except OSError:
        pass
    return explanations


def compute_common_prefix(paths: list[str]) -> str:
    """Find the longest common directory prefix across file paths."""
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


def load_changes_from_jsonl(source: Path) -> tuple[dict, list[dict]]:
    """Load changes from JSONL or JSON file, merging explanations.

    Returns (metadata, changes).
    """
    text = source.read_text(encoding="utf-8").strip()
    if not text:
        return {}, []

    # Try as JSON first
    if text.startswith("{"):
        try:
            data = json.loads(text)
            return data, data.get("changes", [])
        except json.JSONDecodeError:
            pass

    explanations = load_explanations()

    changes = []
    for i, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            entry.setdefault("id", i)
            if entry["id"] in explanations:
                expl = explanations[entry["id"]]
                if not entry.get("reason"):
                    entry["reason"] = expl["explanation"]
                if not entry.get("category") or entry.get("category") == "other":
                    entry["category"] = expl.get("category") or ""
            entry.setdefault("reason", "")
            entry.setdefault("category", "")
            changes.append(entry)
        except json.JSONDecodeError:
            continue

    meta = {"task": "Session changes", "changes": changes}
    return meta, changes


def copy_to_clipboard(text: str) -> bool:
    """Copy text to system clipboard. Returns True if successful."""
    for cmd in (["pbcopy"], ["xclip", "-selection", "clipboard"]):
        try:
            subprocess.run(cmd, input=text.encode(), check=True)
            return True
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    return False
