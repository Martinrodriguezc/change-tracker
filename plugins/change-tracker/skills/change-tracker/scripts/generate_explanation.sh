#!/bin/bash
# Generates a Claude-powered explanation + category for a code change.
# Called in background by hook-capture.sh — does NOT block the hook.

EXPLANATIONS_FILE="/tmp/claude-change-tracker-explanations.jsonl"
CHANGE_FILE="$1"

if [ ! -f "$CHANGE_FILE" ]; then
  exit 0
fi

# Extract fields from the JSON change file (single parse)
read CHANGE_ID FILE_PATH CHANGE_TYPE <<< $(python3 -c "
import json, sys
d = json.load(open('$CHANGE_FILE'))
print(d.get('id',''), d.get('file',''), d.get('type','edit'))
" 2>/dev/null)

if [ -z "$CHANGE_ID" ]; then
  exit 0
fi

# Build a concise diff summary for Claude
DIFF_SUMMARY=$(python3 -c "
import json
d = json.load(open('$CHANGE_FILE'))
ct = d.get('type', 'edit')
old = d.get('old_text', '')
new = d.get('new_text', '')
if ct == 'create':
    print(f'New file created with content:\n{new}')
else:
    print(f'File: {d[\"file\"]}\nChanged from:\n{old}\nTo:\n{new}')
" 2>/dev/null | head -c 2000)

RESPONSE=$(claude -p --model haiku "You are a commit message assistant. Given this code change, respond with EXACTLY two lines:
Line 1: One of these categories: feat, fix, refactor, style, docs, test
Line 2: A single concise sentence describing WHAT was changed, WHY it matters, and HOW it was done. Be specific — reference actual variable names, function names, or values from the diff. Do NOT be generic. Do NOT mention file paths.

Output ONLY those two lines, nothing else.

$DIFF_SUMMARY" 2>/dev/null)

CATEGORY=$(echo "$RESPONSE" | head -1 | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')
EXPLANATION=$(echo "$RESPONSE" | sed -n '2p')

# Validate category — fall back to 'refactor' if invalid
case "$CATEGORY" in
  feat|fix|refactor|style|docs|test) ;;
  feature) CATEGORY="feat" ;;
  *) CATEGORY="refactor" ;;
esac

# If explanation is empty, the whole response might be on one line
if [ -z "$EXPLANATION" ]; then
  EXPLANATION=$(echo "$RESPONSE" | head -1)
  CATEGORY="refactor"
fi

if [ -n "$EXPLANATION" ]; then
  python3 -c "
import json, sys
entry = {'id': int(sys.argv[1]), 'explanation': sys.argv[2], 'category': sys.argv[3]}
with open(sys.argv[4], 'a') as f:
    f.write(json.dumps(entry, ensure_ascii=False) + '\n')
" "$CHANGE_ID" "$EXPLANATION" "$CATEGORY" "$EXPLANATIONS_FILE" 2>/dev/null
fi
