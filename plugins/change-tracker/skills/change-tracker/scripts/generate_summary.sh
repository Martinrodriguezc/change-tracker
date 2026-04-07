#!/bin/bash
# Generates commit message + PR description from all session changes using Claude Haiku.
# Called in background by hook-capture.sh — does NOT block the hook.
# Self-debouncing: skips if last generation was <10 seconds ago.

SUMMARY_FILE="/tmp/claude-change-tracker-summary.json"
LOCK_FILE="/tmp/claude-change-tracker-summary.lock"
SESSION_FILE="$HOME/.claude-change-tracker/current-session.jsonl"
EXPLANATIONS_FILE="/tmp/claude-change-tracker-explanations.jsonl"

# Debounce: skip if summary was generated less than 10 seconds ago
if [ -f "$SUMMARY_FILE" ]; then
  SUMMARY_AGE=$(( $(date +%s) - $(stat -f %m "$SUMMARY_FILE" 2>/dev/null || stat -c %Y "$SUMMARY_FILE" 2>/dev/null || echo 0) ))
  if [ "$SUMMARY_AGE" -lt 10 ]; then
    exit 0
  fi
fi

# Lock: skip if another instance is already running
if [ -f "$LOCK_FILE" ]; then
  LOCK_PID=$(cat "$LOCK_FILE" 2>/dev/null)
  if [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
    exit 0
  fi
fi
echo $$ > "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

if [ ! -f "$SESSION_FILE" ]; then
  exit 0
fi

CHANGE_COUNT=$(wc -l < "$SESSION_FILE" 2>/dev/null | tr -d ' ')
if [ "$CHANGE_COUNT" -lt 1 ]; then
  exit 0
fi

# Build a compact summary of all changes
CHANGES_SUMMARY=$(python3 -c "
import json
from pathlib import Path

session = Path('$SESSION_FILE')
expl_file = Path('$EXPLANATIONS_FILE')

explanations = {}
if expl_file.exists():
    for line in expl_file.read_text().splitlines():
        line = line.strip()
        if not line: continue
        try:
            e = json.loads(line)
            explanations[e['id']] = {'explanation': e.get('explanation',''), 'category': e.get('category','')}
        except: pass

lines = []
files_seen = set()
for i, line in enumerate(session.read_text().splitlines(), 1):
    line = line.strip()
    if not line: continue
    try:
        c = json.loads(line)
        f = c.get('file','').split('/')[-1]
        ct = c.get('type','edit')
        expl = explanations.get(i, {})
        reason = expl.get('explanation', '')
        cat = expl.get('category', '')
        files_seen.add(c.get('file',''))
        desc = f'[{cat or ct}] {f}'
        if reason:
            desc += f': {reason}'
        lines.append(desc)
    except: pass

print(f'{len(lines)} changes, {len(files_seen)} files:')
for l in lines:
    print(l)
" 2>/dev/null | head -c 2000)

if [ -z "$CHANGES_SUMMARY" ]; then
  exit 0
fi

RESPONSE=$(claude -p --model haiku "Output TWO things separated by the exact line ---SEPARATOR--- (nothing else on that line).

FIRST: A git commit message. Start directly with the type — no labels, no markdown fencing. Format:
type(scope): short description

- key change 1
- key change 2

SECOND: A PR description. Start directly with ## What — no labels, no intro.

## What
What this PR does (1 paragraph, reference actual files).

## Why
What problem it solves (1 paragraph).

## How
Technical approach (1 paragraph).

## Changes
Grouped bullet points.

## How to test
Step-by-step instructions with expected results.

Be specific. English. No filler. No markdown code fences around the output.

$CHANGES_SUMMARY" 2>/dev/null)

if [ -z "$RESPONSE" ]; then
  rm -f "$LOCK_FILE"
  exit 0
fi

# Split response into commit message and PR description
python3 -c "
import json, sys

response = sys.stdin.read()
parts = response.split('---SEPARATOR---', 1)

commit_msg = parts[0].strip() if len(parts) > 0 else ''
pr_desc = parts[1].strip() if len(parts) > 1 else ''

# If no separator found, try to split on first ## heading
if not pr_desc and '## ' in commit_msg:
    idx = commit_msg.index('## ')
    pr_desc = commit_msg[idx:].strip()
    commit_msg = commit_msg[:idx].strip()

summary = {
    'commit_message': commit_msg,
    'pr_description': pr_desc,
    'change_count': $CHANGE_COUNT,
}

with open('$SUMMARY_FILE', 'w') as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)
" <<< "$RESPONSE"
