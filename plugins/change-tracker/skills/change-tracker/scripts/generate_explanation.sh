#!/bin/bash
# Generates a Claude-powered explanation for a code change.
# Called in background by hook-capture.sh — does NOT block the hook.

EXPLANATIONS_FILE="/tmp/claude-change-tracker-explanations.jsonl"
CHANGE_FILE="$1"

if [ ! -f "$CHANGE_FILE" ]; then
  exit 0
fi

# Extract fields from the JSON change file
CHANGE_ID=$(python3 -c "import json; print(json.load(open('$CHANGE_FILE'))['id'])" 2>/dev/null)
FILE_PATH=$(python3 -c "import json; print(json.load(open('$CHANGE_FILE'))['file'])" 2>/dev/null)
CHANGE_TYPE=$(python3 -c "import json; print(json.load(open('$CHANGE_FILE')).get('type','edit'))" 2>/dev/null)

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

EXPLANATION=$(claude -p "You are a commit message assistant. Given this code change, write a single concise sentence describing WHAT was changed, WHY it matters, and HOW it was done. Be specific — reference actual variable names, function names, or values from the diff. Do NOT be generic. Do NOT mention file paths. Output ONLY the sentence, nothing else.

$DIFF_SUMMARY" 2>/dev/null | head -1)

if [ -n "$EXPLANATION" ]; then
  python3 -c "
import json, sys
entry = {'id': int(sys.argv[1]), 'explanation': sys.argv[2]}
with open(sys.argv[3], 'a') as f:
    f.write(json.dumps(entry, ensure_ascii=False) + '\n')
" "$CHANGE_ID" "$EXPLANATION" "$EXPLANATIONS_FILE" 2>/dev/null
fi
