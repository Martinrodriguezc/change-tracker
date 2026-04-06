#!/bin/bash
# Generates a Claude-powered explanation for a code change.
# Called in background by hook-capture.sh — does NOT block the hook.
# Writes the explanation to /tmp/claude-change-tracker-explanations.jsonl

EXPLANATIONS_FILE="/tmp/claude-change-tracker-explanations.jsonl"
CHANGE_ID="$1"
FILE_PATH="$2"
OLD_TEXT="$3"
NEW_TEXT="$4"
CHANGE_TYPE="$5"

# Build a concise diff summary for Claude
if [ "$CHANGE_TYPE" = "create" ]; then
  DIFF_SUMMARY="New file created with content:
$NEW_TEXT"
else
  DIFF_SUMMARY="File: $FILE_PATH
Changed from:
$OLD_TEXT
To:
$NEW_TEXT"
fi

# Truncate if too long (keep under 2000 chars for speed)
DIFF_SUMMARY=$(echo "$DIFF_SUMMARY" | head -c 2000)

# Call Claude in print mode to generate the explanation
EXPLANATION=$(claude -p "You are a commit message assistant. Given this code change, write a single concise sentence describing WHAT was changed, WHY it matters, and HOW it was done. Be specific — reference actual variable names, function names, or values from the diff. Do NOT be generic. Do NOT mention file paths. Output ONLY the sentence, nothing else.

$DIFF_SUMMARY" 2>/dev/null | head -1)

# Write to explanations file as JSONL
if [ -n "$EXPLANATION" ]; then
  python3 -c "
import json, sys
entry = {'id': int(sys.argv[1]), 'explanation': sys.argv[2]}
with open(sys.argv[3], 'a') as f:
    f.write(json.dumps(entry, ensure_ascii=False) + '\n')
" "$CHANGE_ID" "$EXPLANATION" "$EXPLANATIONS_FILE" 2>/dev/null
fi
