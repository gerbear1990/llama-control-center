# Terminal-Instrument Design Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the LCC web UI so machine data reads in monospace, structure is drawn with 1px hairlines instead of shadows/lifts, and the active pane carries an accent left edge — with zero colour changes.

**Architecture:** `lcc_api/static/styles.css` already contains two layered passes (original design, then a "reference-aligned dashboard pass" from line ~2701 that re-declares `:root` and many components). This plan edits broken/obsolete rules in place and appends one new final layer ("terminal-instrument pass") whose rules win by cascade order. Small companion edits to `index.html` (eyebrow spans) and `app.js` (running-state class, bounce removal).

**Tech Stack:** Vanilla CSS/HTML/JS served by FastAPI (`lcc_api`). No build step — edits are live on reload. Node used only for syntax checks and the existing unit tests.

**Spec:** `docs/superpowers/specs/2026-07-17-terminal-instrument-design.md`

## Global Constraints

- **No colour changes.** Never edit any colour value, colour token, or `[data-theme="dark"]` colour override. New rules may only *reference* existing tokens.
- No bundled webfonts. The mono stack is `"Cascadia Code", "JetBrains Mono", Consolas, ui-monospace, monospace`.
- No references to external design-system names in code, comments, or commit messages.
- Do not touch the `prefers-reduced-motion` blocks.
- New CSS goes in one appended section at the end of `styles.css` headed `/* ===== Terminal-instrument pass ... ===== */`, except where a step explicitly says "edit in place".
- App under test: `python start-lcc.py` serves `http://127.0.0.1:8716`. Stop with `python stop-lcc.py`.
- Commit after every task. End commit messages with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Foundations — tokens, broken-fragment fixes, mono consolidation

**Files:**
- Modify: `lcc_api/static/styles.css` (first `:root` block ~line 1-35; fragments at ~267 and ~3890; six `font-family` declarations)

**Interfaces:**
- Produces: CSS custom properties `--font-mono`, `--dur-fast`, `--dur-base`, `--dur-slow`, `--hairline`, `--rule`, `--inset-top` — consumed by every later task.

- [ ] **Step 1: Fix the orphaned fragment in the nav rules (edit in place)**

Replace:

```css
.nav-item.active {
  background: color-mix(in srgb, var(--accent) 12%, var(--surface));
  color: var(--text);
}
  color: var(--accent);
}
```

with:

```css
.nav-item.active {
  background: color-mix(in srgb, var(--accent) 12%, var(--surface));
  color: var(--text);
}
```

- [ ] **Step 2: Fix the orphaned fragment after `.sparkline` (edit in place)**

Replace:

```css
.sparkline {
  width: 100%;
  height: 18px;
  display: block;
  margin: 2px 0;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 3px;
}
  color: var(--text);
}
```

with:

```css
.sparkline {
  width: 100%;
  height: 18px;
  display: block;
  margin: 2px 0;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 3px;
}
```

- [ ] **Step 3: Add tokens to the FIRST `:root` block (edit in place)**

Replace:

```css
  --shadow: 0 1px 2px rgba(23, 39, 45, 0.06), 0 14px 32px rgba(23, 39, 45, 0.04);
  --radius: 8px;
```

with:

```css
  --shadow: 0 1px 2px rgba(23, 39, 45, 0.06), 0 14px 32px rgba(23, 39, 45, 0.04);
  --radius: 8px;
  /* Type */
  --font-mono: "Cascadia Code", "JetBrains Mono", Consolas, ui-monospace, monospace;
  /* Motion */
  --dur-fast: 60ms;
  --dur-base: 120ms;
  --dur-slow: 200ms;
  /* Hairlines: structure drawn with 1px rules, not shadows */
  --hairline: 1px solid var(--border);
  --rule: var(--border);
  --inset-top: 0 1px 0 var(--inset-highlight) inset;
```

(These are theme-independent; the dark block inherits them. Do NOT add them to the second `:root` at ~line 2702.)

- [ ] **Step 4: Consolidate existing mono stacks onto the token (edit in place, 7 declarations)**

Each is a one-line `font-family` swap. Old → new value, with owning selector for locating:

| Selector | Old declaration | New declaration |
|---|---|---|
| `.server-metrics` | `font-family: ui-monospace, monospace;` | `font-family: var(--font-mono);` |
| `.portability-roots .mono` | `font-family: ui-monospace, monospace;` | `font-family: var(--font-mono);` |
| `.log-preview` | `font-family: "Cascadia Code", "SFMono-Regular", Consolas, monospace;` | `font-family: var(--font-mono);` |
| `#hf-cli-path` | `font-family: ui-monospace, monospace;` | `font-family: var(--font-mono);` |
| `.fit-details code` | `font-family: "Cascadia Code", "SFMono-Regular", Consolas, monospace;` | `font-family: var(--font-mono);` |
| `.palette-list kbd` | `font-family: ui-monospace, monospace;` | `font-family: var(--font-mono);` |
| `.search-field kbd` | `font-family: inherit;` | `font-family: var(--font-mono);` |

- [ ] **Step 5: Verify**

Run: `grep -c "var(--font-mono)" lcc_api/static/styles.css`
Expected: `7`

Run: `grep -n "ui-monospace, monospace\|SFMono" lcc_api/static/styles.css`
Expected: exactly 1 match — the `--font-mono:` token definition line (its fallback tail contains `ui-monospace, monospace`). Any other match means a consolidation was missed.

- [ ] **Step 6: Commit**

```bash
git add lcc_api/static/styles.css
git commit -m "style(ui): add type/motion/hairline tokens, fix orphaned CSS fragments, consolidate mono stacks"
```

---

### Task 2: Mono typography for data and labels

**Files:**
- Modify: `lcc_api/static/styles.css` (append new final section)

**Interfaces:**
- Consumes: `--font-mono` from Task 1.
- Produces: the appended section `/* ===== Terminal-instrument pass ===== */` that Tasks 3-6 extend.

- [ ] **Step 1: Append the section header and typography rules at the very end of `styles.css`**

```css
/* ===== Terminal-instrument pass =====
   Rule of thumb: values the machine produced (and labels classifying them)
   are mono; anything you read or click stays Inter. Appended last so these
   override the two earlier passes by cascade order. No colour changes. */

.metric-value {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}

.badge,
.param-hint,
.live-source-badge {
  font-family: var(--font-mono);
}

th,
.runtime-table th,
#profiles th {
  font-family: var(--font-mono);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.hardware-chip span,
.hardware-chip strong,
.live-gpu-card-head .gpu-stats,
.live-bar-label {
  font-family: var(--font-mono);
}

.model-path,
.cell-subtitle,
.runtime-version {
  font-family: var(--font-mono);
}

.estimate-card span,
.estimate-card strong,
.tune-suggestion-specs span {
  font-family: var(--font-mono);
}

.profile-group-title,
.param-section-title,
.hf-label,
.sidebar-live-title,
.sidebar-footer-version {
  font-family: var(--font-mono);
}
```

Sizes and weights are intentionally NOT redeclared (existing rules keep them), except table headers where 11px/uppercase/letter-spacing is the spec'd eyebrow treatment.

- [ ] **Step 2: Verify the file still parses and the section landed**

Run: `grep -c "Terminal-instrument pass" lcc_api/static/styles.css`
Expected: `1`

- [ ] **Step 3: Commit**

```bash
git add lcc_api/static/styles.css
git commit -m "style(ui): monospace for machine data and classification labels"
```

---

### Task 3: Hairline structure — shadows off in-flow surfaces, column rule, topbar divider

**Files:**
- Modify: `lcc_api/static/styles.css` (one in-place edit + append to the terminal-instrument section)

**Interfaces:**
- Consumes: `--inset-top`, `--rule` from Task 1.

- [ ] **Step 1: Remove the sidebar's soft shadow (edit in place, second-pass block ~line 2730)**

Replace:

```css
.sidebar {
  padding: 30px clamp(14px, 1.2vw, 18px) 22px;
  gap: 32px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 10px 0 40px rgba(15, 23, 42, 0.025);
}
```

with:

```css
.sidebar {
  padding: 30px clamp(14px, 1.2vw, 18px) 22px;
  gap: 32px;
  background: rgba(255, 255, 255, 0.94);
}
```

(The sidebar's existing 1px `border-right` is the column rule.)

- [ ] **Step 2: Append structure rules to the terminal-instrument section**

```css
/* Structure: hairlines + a whisper of inset depth; no floating shadows in-flow.
   Overlays (modals, popup menus, toasts, palette) keep their shadows. */
.panel,
.metric {
  box-shadow: var(--inset-top);
}

/* Full-height rule in the gap between content column and inspector.
   Offset mirrors the .workspace grid template: inspector clamp() + half the 20px gap. */
.workspace {
  position: relative;
}

.workspace::after {
  content: "";
  position: absolute;
  top: 0;
  bottom: 0;
  right: calc(clamp(340px, 22vw, 386px) + 10px);
  width: 1px;
  background: var(--rule);
  pointer-events: none;
}

@media (max-width: 1180px) {
  .workspace::after {
    display: none;
  }
}

/* Horizontal divider separating the page-header zone from metrics + workspace. */
.topbar {
  border-bottom: 1px solid var(--rule);
  padding-bottom: 16px;
}
```

- [ ] **Step 3: Verify**

Run: `grep -c "workspace::after" lcc_api/static/styles.css`
Expected: `2` (rule + media override)

- [ ] **Step 4: Commit**

```bash
git add lcc_api/static/styles.css
git commit -m "style(ui): hairline structure - column rule, topbar divider, inset depth instead of shadows"
```

---

### Task 4: Panel eyebrows

**Files:**
- Modify: `lcc_api/static/index.html` (12 panel headings)
- Modify: `lcc_api/static/styles.css` (append to terminal-instrument section)

**Interfaces:**
- Consumes: `--font-mono` from Task 1.
- Produces: `.panel-eyebrow` class.

- [ ] **Step 1: Append eyebrow CSS to the terminal-instrument section**

```css
/* Category eyebrow above each panel title. */
.panel-eyebrow {
  display: block;
  margin: 0 0 3px;
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
}
```

- [ ] **Step 2: Insert eyebrow spans in `index.html`**

For each row below, replace `<h3>TITLE</h3>` with the span + h3 (each `<h3>` string is unique in the file — "Servers" ≠ "Active Servers", "Models" ≠ "Model Notes"):

| Old string | New string |
|---|---|
| `<h3>Runtimes</h3>` | `<span class="panel-eyebrow">Inventory</span>` then `<h3>Runtimes</h3>` on the next line |
| `<h3>Profiles</h3>` | `<span class="panel-eyebrow">Launch config</span>` + `<h3>Profiles</h3>` |
| `<h3>Models</h3>` | `<span class="panel-eyebrow">Inventory</span>` + `<h3>Models</h3>` |
| `<h3>Active Servers</h3>` | `<span class="panel-eyebrow">Running</span>` + `<h3>Active Servers</h3>` |
| `<h3>Chat</h3>` | `<span class="panel-eyebrow">Running</span>` + `<h3>Chat</h3>` |
| `<h3>Parameters</h3>` | `<span class="panel-eyebrow">Launch config</span>` + `<h3>Parameters</h3>` |
| `<h3>Model Notes</h3>` | `<span class="panel-eyebrow">Analysis</span>` + `<h3>Model Notes</h3>` |
| `<h3>Benchmark History</h3>` | `<span class="panel-eyebrow">Diagnostics</span>` + `<h3>Benchmark History</h3>` |
| `<h3>Servers</h3>` | `<span class="panel-eyebrow">Running</span>` + `<h3>Servers</h3>` |
| `<h3>Logs</h3>` | `<span class="panel-eyebrow">Diagnostics</span>` + `<h3>Logs</h3>` |
| `<h3>Portability &amp; Paths</h3>` | `<span class="panel-eyebrow">Diagnostics</span>` + `<h3>Portability &amp; Paths</h3>` |
| `<h3>Hugging Face Tools</h3>` | `<span class="panel-eyebrow">Acquisition</span>` + `<h3>Hugging Face Tools</h3>` |

Match surrounding indentation (headings sit at ~18 spaces). Note: the spec's table said "Fit → VRAM PLANNER", but there is no standalone Fit panel — fit output renders inside Model Notes, hence `Analysis`. Chat/Model Notes/Benchmark History/Servers were absent from the spec table; this mapping extends it consistently.

- [ ] **Step 3: Verify**

Run: `grep -c "panel-eyebrow" lcc_api/static/index.html`
Expected: `12`

- [ ] **Step 4: Commit**

```bash
git add lcc_api/static/index.html lcc_api/static/styles.css
git commit -m "feat(ui): category eyebrows on panel headings"
```

---

### Task 5: Active-pane edges

**Files:**
- Modify: `lcc_api/static/app.js` (`renderActiveServers`, ~line 1412)
- Modify: `lcc_api/static/styles.css` (append to terminal-instrument section)

**Interfaces:**
- Consumes: `--inset-top` from Task 1; `isRunning` local already computed at `app.js:1400`.
- Produces: `.active-server-row.running` state class.

- [ ] **Step 1: Emit a `running` class from `renderActiveServers` (edit in place)**

In `app.js`, replace:

```javascript
      <article class="active-server-row" data-server-id="${escapeHtml(server.id)}">
```

with:

```javascript
      <article class="active-server-row${isRunning ? ' running' : ''}" data-server-id="${escapeHtml(server.id)}">
```

- [ ] **Step 2: Verify JS syntax**

Run: `node --check lcc_api/static/app.js`
Expected: exit 0, no output.

- [ ] **Step 3: Append active-edge CSS to the terminal-instrument section**

```css
/* Active-pane edge: accent inset-left rail, same language as nav + selected rows. */
.active-server-row.running {
  box-shadow: inset 3px 0 0 var(--accent);
}

.panel:focus-within {
  box-shadow: inset 3px 0 0 var(--accent), var(--inset-top);
}
```

- [ ] **Step 4: Commit**

```bash
git add lcc_api/static/app.js lcc_api/static/styles.css
git commit -m "feat(ui): accent active-pane edge on running servers and focused panel"
```

---

### Task 6: Calm the surfaces — motion

**Files:**
- Modify: `lcc_api/static/styles.css` (in-place edits)
- Modify: `lcc_api/static/app.js` (~line 3506)

**Interfaces:**
- Consumes: `--dur-base` from Task 1.

- [ ] **Step 1: Remove hover lifts and hover shadows (edit in place, first-pass blocks)**

Six replacements:

(a) Replace:
```css
.metric {
  min-height: 66px;
  padding: 13px 15px;
  border: 1px solid var(--border);
  background: var(--surface);
  border-radius: var(--radius);
  box-shadow: 0 1px 0 var(--inset-highlight) inset;
  transition: transform 160ms ease, box-shadow 160ms ease, border-color 140ms ease;
}

.metric:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.05);
}
```
with:
```css
.metric {
  min-height: 66px;
  padding: 13px 15px;
  border: 1px solid var(--border);
  background: var(--surface);
  border-radius: var(--radius);
  box-shadow: 0 1px 0 var(--inset-highlight) inset;
  transition: border-color var(--dur-base) ease;
}
```

(b) Replace:
```css
  transition: transform 120ms ease, background 140ms ease, border-color 140ms ease;
}

.badge:hover {
  transform: scale(1.04);
}
```
with:
```css
  transition: background var(--dur-base) ease, border-color var(--dur-base) ease;
}
```

(c) In `.model-row`, replace:
```css
  transition: background 140ms ease, transform 160ms ease;
}

.model-row:hover {
  background: color-mix(in srgb, var(--accent) 5%, var(--surface));
  transform: translateY(-1px);
}
```
with:
```css
  transition: background var(--dur-base) ease;
}

.model-row:hover {
  background: color-mix(in srgb, var(--accent) 5%, var(--surface));
}
```

(d) Replace:
```css
.server-item,
.issue-item,
.empty-state {
  border: 1px solid var(--border);
  background: var(--surface-2);
  border-radius: 7px;
  padding: 11px;
  transition: transform 160ms ease, box-shadow 160ms ease, background 140ms ease;
}

.server-item:hover,
.active-server-row:hover,
.issue-item:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
  background: color-mix(in srgb, var(--surface) 60%, var(--surface-2));
}
```
with:
```css
.server-item,
.issue-item,
.empty-state {
  border: 1px solid var(--border);
  background: var(--surface-2);
  border-radius: 7px;
  padding: 11px;
  transition: background var(--dur-base) ease;
}

.server-item:hover,
.active-server-row:hover,
.issue-item:hover {
  background: color-mix(in srgb, var(--surface) 60%, var(--surface-2));
}
```

(e) In `.active-server-row`, replace:
```css
  transition: transform 160ms ease, box-shadow 160ms ease, background 140ms ease;
}
```
with:
```css
  transition: background var(--dur-base) ease;
}
```
(the remaining occurrence of that exact transition line after edit (d))

(f) In `.estimate-card`, replace:
```css
  transition: background 220ms ease, border-color 220ms ease, transform 160ms ease;
}

.estimate-card:hover {
  transform: translateY(-1px);
}
```
with:
```css
  transition: background 220ms ease, border-color 220ms ease;
}
```

(g) In `.live-gpu-card`, replace:
```css
  transition: transform 160ms ease, box-shadow 160ms ease;
}

.live-gpu-card:hover {
  transform: translateY(-1px);
  box-shadow: 0 3px 10px rgba(0, 0, 0, 0.05);
}
```
with:
```css
  transition: border-color var(--dur-base) ease;
}
```

- [ ] **Step 2: Delete the bounce animation (edit in place)**

Replace:
```css
@keyframes panel-bounce {
  0% {
    transform: scale(0.96) translateY(10px);
    opacity: 0.85;
  }
  35% {
    transform: scale(1.025) translateY(-3px);
  }
  65% {
    transform: scale(0.995) translateY(1px);
  }
  100% {
    transform: scale(1) translateY(0);
    opacity: 1;
  }
}

.bounce-target {
  animation: panel-bounce 620ms cubic-bezier(0.34, 1.56, 0.64, 1);
}
```
with nothing (delete, leaving one blank line).

- [ ] **Step 3: Remove the bounce-class application in `app.js` (edit in place, ~line 3506)**

Replace:
```javascript
          target.scrollIntoView({ behavior: 'smooth', block: 'start' });
          target.classList.add('bounce-target');
          // Remove after animation
          setTimeout(() => {
            target.classList.remove('bounce-target');
          }, 700);
```
with:
```javascript
          target.scrollIntoView({ behavior: 'smooth', block: 'start' });
```

- [ ] **Step 4: Retime remaining micro-interactions onto the token**

Run (PowerShell):
```powershell
$f = 'lcc_api/static/styles.css'
$css = Get-Content $f -Raw
$css = $css -replace '140ms ease', 'var(--dur-base) ease' -replace '160ms ease', 'var(--dur-base) ease' -replace '180ms ease', 'var(--dur-base) ease'
Set-Content $f $css -NoNewline
```
This intentionally leaves 200/220/260/320ms (sidebar, panel collapse, modal) and all `animation` durations untouched.

- [ ] **Step 5: Verify**

Run: `node --check lcc_api/static/app.js` — expected exit 0.
Run: `grep -n "panel-bounce\|bounce-target" lcc_api/static/styles.css lcc_api/static/app.js` — expected: no matches.
Run: `grep -c "translateY(-1px)" lcc_api/static/styles.css` — expected: `0`.
Run: `grep -n "140ms ease\|160ms ease\|180ms ease" lcc_api/static/styles.css` — expected: no matches.

- [ ] **Step 6: Commit**

```bash
git add lcc_api/static/styles.css lcc_api/static/app.js
git commit -m "style(ui): calm surface motion - flat hovers, no bounce, tokenized durations"
```

---

### Task 7: End-to-end verification

**Files:**
- Test: `tests/test_server_metrics_formatter.js`, `tests/test_models_pane_matcher.js`
- No source changes expected (fix-forward if checks fail).

- [ ] **Step 1: Run the node unit tests**

```bash
node tests/test_server_metrics_formatter.js
node tests/test_models_pane_matcher.js
```
Expected: both exit 0 (guards the `app.js` edits).

- [ ] **Step 2: Launch the app**

```powershell
python start-lcc.py
```
App serves `http://127.0.0.1:8716`.

- [ ] **Step 3: Visual checklist in the browser (light AND dark theme, at ~1500px, ~1250px, ~900px widths)**

- Mono appears on: metric values, badges, table headers (uppercase), hardware chips, VRAM/RAM bar labels, model paths, estimate cards, section labels, sidebar version. NOT on buttons, nav, panel titles, form inputs, chat.
- Vertical hairline sits centered in the content/inspector gap at desktop widths; disappears below 1180px.
- Topbar divider spans the main column; no layout jump.
- Panels/metrics have no drop shadows; modals/popups/toasts still do.
- Clicking into any panel (e.g. a Parameters input) shows the accent left rail; it moves when focus moves to another panel.
- A running server row shows the accent left rail.
- Hovers are flat (background shift only); jump-to-panel navigation scrolls without bounce.

- [ ] **Step 4: Stop the app**

```powershell
python stop-lcc.py
```

- [ ] **Step 5: Commit any fix-forward changes**

```bash
git add -A lcc_api/static
git commit -m "fix(ui): visual verification follow-ups for terminal-instrument pass"
```
(Skip if the checklist passed clean with no edits.)
