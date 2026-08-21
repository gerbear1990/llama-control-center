# Terminal-instrument design pass — spec

Date: 2026-07-17
Scope: `lcc_api/static/styles.css`, `lcc_api/static/index.html`, minor `lcc_api/static/app.js` cleanup.
Constraint: **no colour changes.** All existing colour tokens, light and dark theme values stay exactly as they are. This pass touches typography, structure, borders, and motion only.

## Intent

Give the control center the character of a steady instrument panel: machine data set in
monospace, structure drawn with 1px hairlines instead of floating shadows, an accent left
edge marking the active pane, and calm, flat hover behavior. The current soft, friendly
personality stays; this is a selective infusion, not a re-theme.

## Context: the stylesheet today

`styles.css` (4072 lines) contains two layered passes — the original design, then a
"reference-aligned dashboard pass" appended at line ~2701 that re-declares `:root`, the
dark theme, and many components. This spec's changes are applied as a third layer where
overriding is cleanest, and edit-in-place where a rule is only declared once. Two
pre-existing broken fragments are fixed in passing:

- `styles.css:267` — orphaned `color: var(--accent); }` between two `.nav-item.active` rules
- `styles.css:3890` — stray `color: var(--text); }` after `.sparkline`

## 1. Foundations (design tokens)

Added to the existing `:root` (values identical in dark theme; nothing colour-bearing):

```css
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

`--radius: 8px` stays. Existing ad-hoc mono stacks (`.log-preview`, `.server-metrics`,
`kbd`, `.portability-roots .mono`, `#hf-cli-path`, `.fit-details code`, `.palette-list kbd`)
consolidate onto `--font-mono`.

## 2. Typography — mono for data and labels

Rule: **if it's a value the machine produced or a label classifying one, it's mono; if
it's something you read or click, it's Inter.**

Switched to `var(--font-mono)`, keeping existing sizes/weights unless noted:

- `.metric-value` — plus `font-variant-numeric: tabular-nums`
- `.badge`, `.param-hint`, `.live-source-badge`
- `th`, `.runtime-table th`, `#profiles th` — restored to `text-transform: uppercase`,
  11px, `letter-spacing: 0.05em` (the second pass had reverted these to sentence case)
- `.hardware-chip span` and `.hardware-chip strong`
- `.gpu-stats`, `.live-bar-label`
- `.model-path`, `.cell-subtitle`, `.estimate-card strong`, `.estimate-card span`,
  `.tune-suggestion-specs span`, `.profile-group-title`, `.param-section-title`,
  `.hf-label`, `.sidebar-live-title`, `.sidebar-footer-version`

Explicitly staying Inter: buttons, mini-buttons, nav items, segments, panel titles,
topbar headings, body copy, form inputs, chat, tooltips, toasts, modals.

## 3. Structure — hairlines, rules, eyebrows, active edges

### Hairlines over shadows
- Sidebar loses its `10px 0 40px` soft shadow; its 1px border-right is the column rule.
- Hover-lift shadows on in-flow surfaces removed (see Motion).
- Panels, metrics, chips: 1px border + `box-shadow: var(--inset-top)` only.
- Overlays (modals, popup menus, toasts, command palette) keep their shadows — they
  genuinely float.

### Column rules
- Full-height 1px vertical rule in the gap between content column and inspector: an
  absolutely-positioned pseudo-element on `.workspace`, offset from the right edge by
  `calc(clamp(340px, 22vw, 386px) + 10px)` (inspector width + half the 20px gap),
  `background: var(--rule)`, width 1px, `aria`-irrelevant (pure CSS decoration).
  Hidden below the 1180px breakpoint where the workspace stacks to one column.
- Horizontal 1px divider under `.topbar` (border-bottom + adjusted padding/margin),
  separating the page-header zone from metrics + workspace.

### Mono eyebrows
Each `.panel-heading` title block gains `<span class="panel-eyebrow">` above the `h3`:
10px `var(--font-mono)`, uppercase, `letter-spacing: 0.08em`, `color: var(--muted)`.
Eyebrow text is category metadata, not a repeat of the title:

| Panel | Eyebrow |
|---|---|
| Runtimes | INVENTORY |
| Models | INVENTORY |
| Active servers | RUNNING |
| Profiles | LAUNCH CONFIG |
| Parameters | LAUNCH CONFIG |
| Fit | VRAM PLANNER |
| Logs | DIAGNOSTICS |
| Portability | DIAGNOSTICS |
| Hugging Face | ACQUISITION |
| Live hardware (sidebar) | unchanged — already has an uppercase title |

### Active-pane edges
Existing 3px accent inset-left language (active nav, selected table rows) extends to:
- The running server row in Active servers (state class applied from `app.js` render).
- `.panel:focus-within` — the panel containing focus shows the accent rail on its left
  edge. No JS required.

## 4. Motion — calm the surfaces

Removed:
- All hover `transform: translateY(-1px)` lifts and their hover shadows: `.metric`,
  `.server-item`, `.active-server-row`, `.issue-item`, `.model-row`, `.estimate-card`,
  `.live-gpu-card`. Hover = flat background/border shift only.
- `.badge:hover { transform: scale(1.04) }`.
- `panel-bounce` keyframes, `.bounce-target` rule, and the `app.js` code that applies
  the class.

Kept, retimed:
- Micro-interaction transitions consolidate from 140/160/180ms onto `var(--dur-base)`.
- Sidebar collapse, panel collapse, modal enter/exit keep current durations/easings
  (expressed via `var(--dur-slow)` where the value fits).
- Press feedback (`:active` scale), busy spinner, port-status pulse, chat pop-in,
  estimate-update pulse all stay — they communicate state.

## Verification

- Launch the app; screenshot light + dark at desktop, 1180px, and 760px widths.
- Check: mono lands only where specified; column rule aligns with the grid gap across
  viewport widths; `:focus-within` rail behaves sanely; no layout shifts from the
  topbar divider.
- `node` unit tests in `tests/` still pass (guards the `app.js` bounce removal).
- `prefers-reduced-motion` behavior unchanged (existing global overrides remain).

## Out of scope

- Any colour value, light or dark.
- Bundling webfonts (mono stack is system-font based, led by Cascadia Code).
- Radius changes, density modes, chart styling, focus-outline restyling.
- Consolidating the stylesheet's two existing passes into one (worthwhile, but a
  separate refactor).
