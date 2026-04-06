# Change Tracker — Full Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the change-tracker plugin with all remaining Tier 1 and Tier 2 improvements: per-change timestamps in the viewer, relative file paths, keyboard navigation, search within diffs, export to markdown, and auto-generate PR descriptions.

**Architecture:** The changes are spread across two files: `generate_changelog.py` (Python data processing + HTML template) and `SKILL.md` (instructions). A new `to_pr_description.py` script is added. The HTML template inside `generate_changelog.py` receives all visual upgrades. No new dependencies — everything uses Python stdlib and vanilla JS.

**Tech Stack:** Python 3.6+ (stdlib only: difflib, json, pathlib, datetime), vanilla HTML/CSS/JS

**Already Implemented (do NOT redo):**
- Auto-capture via PostToolUse hooks (hook-capture.sh, hook_capture_worker.py, init_changelog.py, finalize_changelog.py, install_hook.py)
- Character-level diff highlighting (compute_char_segments, add_char_highlights, char-hl-add/char-hl-remove CSS)
- PROs, CONs, Notes fields and rendering
- Category filters, file sidebar, search, dark/light theme

---

### Task 1: Display per-change timestamps in the HTML viewer

The hook already captures `timestamp` per change (ISO format). The `build_embedded_data()` function currently drops it. Pass it through and render it in the HTML.

**Files:**
- Modify: `plugins/change-tracker/skills/change-tracker/scripts/generate_changelog.py`

- [ ] **Step 1: Pass timestamp through build_embedded_data**

In `generate_changelog.py`, inside `build_embedded_data()`, find the `processed.append({...})` block (around line 191-202). Add `"timestamp"` to the dict:

```python
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
```

- [ ] **Step 2: Add CSS for the timestamp display**

In the HTML_TEMPLATE CSS section, after the `.change-id` rule (around line 510-513), add:

```css
  .change-timestamp {
    font-size: 11px;
    color: var(--text-muted);
    font-family: var(--mono);
  }
```

- [ ] **Step 3: Render timestamp in change card header**

In the JS `renderChanges()` function, after the `idEl` is appended to `meta` (around line 820), add before the category badge:

```javascript
    if (change.timestamp) {
      const tsEl = document.createElement('span');
      tsEl.className = 'change-timestamp';
      const d = new Date(change.timestamp);
      tsEl.textContent = d.toLocaleTimeString('es-CL', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      tsEl.title = change.timestamp;
      meta.appendChild(tsEl);
    }
```

- [ ] **Step 4: Test with sample data**

Create `/tmp/test-timestamp.json` with 2 changes that have timestamps (use ISO format like `"2026-04-06T13:45:22.123456"`). Run:

```bash
python3 plugins/change-tracker/skills/change-tracker/scripts/generate_changelog.py /tmp/test-timestamp.json --no-open -o /tmp/test-timestamp.html
```

Verify the HTML contains `change-timestamp` class and the time renders correctly. Open in browser to visually verify.

- [ ] **Step 5: Commit**

```bash
git add plugins/change-tracker/skills/change-tracker/scripts/generate_changelog.py
git commit -m "feat: display per-change timestamps in HTML viewer"
```

---

### Task 2: Show relative file paths in the viewer

Absolute paths like `/Users/martin/Desktop/personal/backend/src/services/auth.service.ts` are noisy. Detect the common prefix of all file paths and strip it, showing `backend/src/services/auth.service.ts` instead. Full path stays in the tooltip.

**Files:**
- Modify: `plugins/change-tracker/skills/change-tracker/scripts/generate_changelog.py`

- [ ] **Step 1: Add compute_relative_paths to Python**

In `generate_changelog.py`, after `build_embedded_data()`, add a new function. Then call it inside `build_embedded_data()` to add a `"display_file"` field to each processed change and to each file entry:

```python
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
```

In `build_embedded_data()`, after building the `files` list, compute the prefix and add `display_file`:

```python
    all_paths = [c["file"] for c in processed]
    prefix = compute_common_prefix(all_paths)
    prefix_len = len(prefix)

    for c in processed:
        c["display_file"] = c["file"][prefix_len:] if prefix_len else c["file"]

    files = [{"path": f, "count": c, "display": f[prefix_len:] if prefix_len else f} for f, c in file_counts.items()]
```

- [ ] **Step 2: Update JS to use display_file**

In the `renderChanges()` function, change `fileEl.textContent = change.file;` to:

```javascript
    fileEl.textContent = change.display_file || change.file;
    fileEl.title = change.file;
```

In the `renderFileList()` function, change the shortPath calculation to:

```javascript
    const displayName = f.display || f.path;
    const parts = displayName.split('/');
    const shortPath = parts.length > 3 ? '.../' + parts.slice(-3).join('/') : displayName;
    el.innerHTML = '<span class="file-name" title="' + escapeHtml(f.path) + '">' + escapeHtml(shortPath) + '</span>'
      + '<span class="file-count">' + f.count + '</span>';
```

- [ ] **Step 3: Test**

Use a changelog where all files share `/Users/martin/Desktop/personal/backend/src/`. Verify the viewer strips the prefix. Hover over a file path — tooltip should show the full path.

```bash
python3 plugins/change-tracker/skills/change-tracker/scripts/generate_changelog.py /tmp/test-timestamp.json --no-open -o /tmp/test-relpath.html
```

- [ ] **Step 4: Commit**

```bash
git add plugins/change-tracker/skills/change-tracker/scripts/generate_changelog.py
git commit -m "feat: show relative file paths in viewer, full path on hover"
```

---

### Task 3: Keyboard navigation

Add `j`/`k` to move between change cards, `f` to toggle first sidebar file filter, `/` to focus search.

**Files:**
- Modify: `plugins/change-tracker/skills/change-tracker/scripts/generate_changelog.py` (HTML template JS section)

- [ ] **Step 1: Add keyboard styles**

In the CSS, after the `.empty-state` rule, add:

```css
  .change-card.focused { outline: 2px solid var(--accent); outline-offset: -2px; }
```

- [ ] **Step 2: Add keyboard handler in JS**

At the end of the `<script>` section, before `// Initial render`, add:

```javascript
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
  // Don't hijack if typing in search
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
```

- [ ] **Step 3: Test**

Open the HTML in a browser. Press `j` — first card should get an accent outline and scroll into view. Press `j` again — second card. Press `k` — back to first. Press `/` — search input focuses. Press `Escape` in search — blurs.

- [ ] **Step 4: Commit**

```bash
git add plugins/change-tracker/skills/change-tracker/scripts/generate_changelog.py
git commit -m "feat: keyboard navigation (j/k, /, Escape)"
```

---

### Task 4: Search within diff content

Currently search only matches `file + reason`. Extend it to also search inside the diff text (old_text + new_text in the embedded data, or the diff_lines text).

**Files:**
- Modify: `plugins/change-tracker/skills/change-tracker/scripts/generate_changelog.py` (JS section)

- [ ] **Step 1: Update the filter in renderChanges()**

In the `renderChanges()` function, find the search filter block:

```javascript
    if (searchQuery) {
      const haystack = (c.file + ' ' + c.reason).toLowerCase();
      if (!haystack.includes(searchQuery)) return false;
    }
```

Replace with:

```javascript
    if (searchQuery) {
      const diffText = (c.diff_lines || []).map(l => l.text).join(' ');
      const prosText = (c.pros || []).join(' ');
      const consText = (c.cons || []).join(' ');
      const haystack = (c.file + ' ' + c.reason + ' ' + (c.notes || '') + ' ' + prosText + ' ' + consText + ' ' + diffText).toLowerCase();
      if (!haystack.includes(searchQuery)) return false;
    }
```

- [ ] **Step 2: Update search placeholder**

Change the search input placeholder from `"Filtrar por archivo o texto..."` to `"Buscar en archivos, codigo, explicaciones..."`.

- [ ] **Step 3: Test**

Open HTML. Search for a code identifier that only appears in the diff (not in the file path or reason). Verify the change card shows. Search for a pro/con text — verify it filters correctly.

- [ ] **Step 4: Commit**

```bash
git add plugins/change-tracker/skills/change-tracker/scripts/generate_changelog.py
git commit -m "feat: search within diff content, pros, cons, and notes"
```

---

### Task 5: Export to Markdown

Add an "Export MD" button in the header that generates and downloads a markdown file with all changes, explanations, and diffs.

**Files:**
- Modify: `plugins/change-tracker/skills/change-tracker/scripts/generate_changelog.py` (HTML template)

- [ ] **Step 1: Add the export button in HTML header**

In the header HTML, after the theme toggle button, add:

```html
    <button class="theme-toggle" id="exportBtn" title="Export as Markdown">&#8615;</button>
```

- [ ] **Step 2: Add the export function in JS**

At the end of the `<script>` section, before `// Initial render`, add:

```javascript
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
```

- [ ] **Step 3: Test**

Open HTML. Click the export button (down-arrow icon). A `.md` file downloads. Open it — verify it contains headers, explanations, pros/cons, notes, and code diffs in fenced blocks.

- [ ] **Step 4: Commit**

```bash
git add plugins/change-tracker/skills/change-tracker/scripts/generate_changelog.py
git commit -m "feat: export changelog as markdown file"
```

---

### Task 6: Auto-generate PR description from changelog

A standalone script that reads the changelog JSON and outputs a PR body ready for `gh pr create --body`.

**Files:**
- Create: `plugins/change-tracker/skills/change-tracker/scripts/to_pr_description.py`

- [ ] **Step 1: Write the script**

Create `plugins/change-tracker/skills/change-tracker/scripts/to_pr_description.py`:

```python
#!/usr/bin/env python3
"""Generate a GitHub PR description from a change-tracker changelog.

Usage:
    python3 to_pr_description.py /tmp/claude-changes-XXX.json
    python3 to_pr_description.py /tmp/claude-changes-XXX.json --copy

Outputs markdown suitable for `gh pr create --body "$(python3 to_pr_description.py changelog.json)"`.
"""
import argparse
import json
import sys
from pathlib import Path
from collections import Counter


def compute_common_prefix(paths):
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


def main():
    parser = argparse.ArgumentParser(description="Generate PR description from changelog")
    parser.add_argument("changelog", type=Path, help="Path to changelog JSON")
    parser.add_argument("--copy", action="store_true", help="Copy to clipboard (macOS)")
    args = parser.parse_args()

    data = json.loads(args.changelog.read_text(encoding="utf-8"))
    changes = data.get("changes", [])

    if not changes:
        print("No changes found.", file=sys.stderr)
        sys.exit(1)

    all_files = [c.get("file", "") for c in changes]
    prefix = compute_common_prefix(all_files)
    prefix_len = len(prefix)

    categories = Counter(c.get("category", "other") for c in changes)
    files_changed = len(set(all_files))

    # Build PR body
    lines = []
    lines.append("## Summary\n")
    lines.append(f"**Task:** {data.get('task', 'N/A')}\n")
    lines.append(f"**{files_changed} files changed** | {len(changes)} edits | Categories: {', '.join(f'{cat} ({n})' for cat, n in categories.most_common())}\n")

    lines.append("\n## Changes\n")
    for c in changes:
        display = c["file"][prefix_len:] if prefix_len else c["file"]
        cat = c.get("category", "other").upper()
        reason = c.get("reason", "").strip()
        line = f"- **`{display}`** [{cat}]"
        if reason:
            # Take first sentence
            first_sentence = reason.split(". ")[0].rstrip(".")
            line += f" — {first_sentence}"
        lines.append(line)

    # Collect all trade-offs
    all_cons = []
    for c in changes:
        for con in c.get("cons", []):
            all_cons.append(con)
    if all_cons:
        lines.append("\n## Trade-offs\n")
        for con in all_cons:
            lines.append(f"- {con}")

    # Collect all notes
    all_notes = [c.get("notes", "").strip() for c in changes if c.get("notes", "").strip()]
    if all_notes:
        lines.append("\n## Notes\n")
        for note in all_notes:
            lines.append(f"- {note}")

    lines.append("\n## Test plan\n")
    lines.append("- [ ] Verify all changes work as described")
    lines.append("- [ ] Review trade-offs listed above")
    lines.append("")

    output = "\n".join(lines)
    print(output)

    if args.copy:
        import subprocess
        subprocess.run(["pbcopy"], input=output.encode(), check=True)
        print("\n(Copied to clipboard)", file=sys.stderr)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test with sample data**

```bash
python3 plugins/change-tracker/skills/change-tracker/scripts/to_pr_description.py /tmp/test-timestamp.json
```

Verify output has Summary, Changes list with file paths and first-sentence reasons, Trade-offs section with cons, Notes section, and Test plan checkboxes.

- [ ] **Step 3: Commit**

```bash
git add plugins/change-tracker/skills/change-tracker/scripts/to_pr_description.py
git commit -m "feat: add to_pr_description.py for generating PR bodies from changelog"
```

---

### Task 7: Update SKILL.md with new features

Document the new capabilities: PR description generation, keyboard shortcuts, export button.

**Files:**
- Modify: `plugins/change-tracker/skills/change-tracker/SKILL.md`

- [ ] **Step 1: Add PR description generation to SKILL.md**

After the "Step 3 — Fill in explanations" section, add:

```markdown
### Optional: Generate PR description

To generate a PR body from the changelog:

```bash
python3 "$CHANGE_TRACKER_DIR/to_pr_description.py" <CHANGELOG_PATH>
```

Or copy directly to clipboard:

```bash
python3 "$CHANGE_TRACKER_DIR/to_pr_description.py" <CHANGELOG_PATH> --copy
```

Use with `gh pr create`:

```bash
gh pr create --title "feat: description" --body "$(python3 "$CHANGE_TRACKER_DIR/to_pr_description.py" <CHANGELOG_PATH>)"
```
```

- [ ] **Step 2: Add HTML viewer tips to SKILL.md**

At the end of the "Important notes" section, add:

```markdown
- **Keyboard shortcuts in the viewer.** `j`/`k` or arrow keys to navigate between changes, `/` to focus search, `Escape` to clear focus.
- **Export.** The download button in the header exports the changelog as a markdown file.
- **Search is deep.** The search box filters across file paths, explanations, pros, cons, notes, and diff content.
```

- [ ] **Step 3: Commit**

```bash
git add plugins/change-tracker/skills/change-tracker/SKILL.md
git commit -m "docs: add PR generation, keyboard shortcuts, and export to SKILL.md"
```

---

### Task 8: Update README.md

Document the new features for users.

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update features list**

In the "The Solution" section, add these bullets:

```markdown
- **Character-level diff highlighting** — within changed lines, the exact characters that differ are highlighted with a stronger background
- **Per-change timestamps** — see when each edit was made during the session
- **Auto-capture via hooks** — edits are recorded automatically, no manual logging needed
- **Keyboard navigation** — j/k to move between changes, / to search, Escape to clear
- **Export to Markdown** — download the full changelog as a .md file
- **PR description generator** — auto-generate a PR body from the changelog
```

- [ ] **Step 2: Add "Generating PR Descriptions" section**

After the "Retroactive Mode" section, add:

```markdown
### Generating PR Descriptions

After a task is complete, generate a ready-to-use PR body:

```bash
# Output to stdout
python3 <scripts-dir>/to_pr_description.py /tmp/claude-changes-XXX.json

# Copy to clipboard (macOS)
python3 <scripts-dir>/to_pr_description.py /tmp/claude-changes-XXX.json --copy

# Use directly with gh
gh pr create --title "feat: my feature" --body "$(python3 <scripts-dir>/to_pr_description.py /tmp/claude-changes-XXX.json)"
```

The PR description includes a summary, per-file change list with reasons, trade-offs section (from CONs), notes, and a test plan checklist.
```

- [ ] **Step 3: Add keyboard shortcuts section**

After "What the HTML Report Looks Like", add:

```markdown
## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `j` / `↓` | Next change |
| `k` / `↑` | Previous change |
| `/` | Focus search |
| `Escape` | Clear focus / blur search |
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: update README with all new features"
```

---

### Task 9: Update screenshots

Take new screenshots that show timestamps, relative paths, and char-level highlights.

**Files:**
- Modify: `assets/screenshot-light.png`
- Modify: `assets/screenshot-dark.png`

- [ ] **Step 1: Create a rich test changelog**

Create a test JSON with 3 changes that have: timestamps, pros/cons/notes, varied categories, absolute paths with a shared prefix. Use the same auth refactor theme as the current screenshots for continuity.

- [ ] **Step 2: Generate HTML and take screenshots**

```bash
python3 plugins/change-tracker/skills/change-tracker/scripts/generate_changelog.py /tmp/test-screenshots.json --no-open -o /tmp/screenshot-changelog.html

# Start server
cd /tmp && python3 -m http.server 8899 &

# Take screenshots using Playwright
node -e "
const { chromium } = require('/Users/martin/Desktop/personal/frontend/node_modules/playwright');
(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1050 }, deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  await page.goto('http://localhost:8899/screenshot-changelog.html');
  await page.waitForTimeout(500);
  await page.screenshot({ path: 'assets/screenshot-light.png', fullPage: true });
  await page.click('button.theme-toggle');
  await page.waitForTimeout(300);
  await page.screenshot({ path: 'assets/screenshot-dark.png', fullPage: true });
  await browser.close();
})();
"
```

- [ ] **Step 3: Commit**

```bash
git add assets/
git commit -m "chore: update screenshots with timestamps, relative paths, and char highlights"
```

---

### Task 10: Sync local install and push

Sync all changes to the local skill installation and push to GitHub.

- [ ] **Step 1: Sync to local skill directory**

```bash
cp -r plugins/change-tracker/skills/change-tracker/scripts/* ~/.claude-personal/.claude/skills/change-tracker/scripts/
cp plugins/change-tracker/skills/change-tracker/SKILL.md ~/.claude-personal/.claude/skills/change-tracker/SKILL.md
```

- [ ] **Step 2: Push to GitHub**

```bash
git push origin main
```

- [ ] **Step 3: Verify on GitHub**

```bash
gh repo view Martinrodriguezc/change-tracker --web
```

Verify README renders correctly with all new sections and screenshots.
