---
name: Llama Control Center
description: Bench instrument for hardware-honest local launch
colors:
  accent: "#077076"
  accent-hover: "#046165"
  accent-dark: "#20aeb5"
  accent-hover-dark: "#15969c"
  bg: "#f7f9fb"
  bg-dark: "#111315"
  surface: "#ffffff"
  surface-dark: "#181d20"
  surface-2: "#f9fbfc"
  surface-2-dark: "#202629"
  surface-3: "#eef7f7"
  surface-3-dark: "#283034"
  text: "#172330"
  text-dark: "#edf2f3"
  text-secondary: "#314155"
  muted: "#647386"
  muted-dark: "#9aa7ab"
  border: "#dde5ee"
  border-dark: "#2b3438"
  border-strong: "#cbd6e2"
  green: "#138850"
  green-dark: "#62bd79"
  amber: "#96650a"
  amber-dark: "#d79b31"
  red: "#c4453e"
  red-dark: "#e26962"
  on-solid: "#ffffff"
  on-solid-dark: "#111315"
  badge-ok-bg: "#eaf7ef"
  badge-warn-bg: "#fff6e8"
  badge-error-bg: "#fff0ef"
  toast-bg: "#162124"
  toast-text: "#ffffff"
typography:
  title:
    fontFamily: "Segoe UI Variable Text, Segoe UI Variable, ui-sans-serif, system-ui, Segoe UI, -apple-system, sans-serif"
    fontSize: "15px"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "normal"
  body:
    fontFamily: "Segoe UI Variable Text, Segoe UI Variable, ui-sans-serif, system-ui, Segoe UI, -apple-system, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.45
    letterSpacing: "normal"
  ui:
    fontFamily: "Segoe UI Variable Text, Segoe UI Variable, ui-sans-serif, system-ui, Segoe UI, -apple-system, sans-serif"
    fontSize: "13px"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "normal"
  compact:
    fontFamily: "Segoe UI Variable Text, Segoe UI Variable, ui-sans-serif, system-ui, Segoe UI, -apple-system, sans-serif"
    fontSize: "12px"
    fontWeight: 600
    lineHeight: 1.35
    letterSpacing: "normal"
  label:
    fontFamily: "Cascadia Code, JetBrains Mono, Consolas, ui-monospace, monospace"
    fontSize: "11px"
    fontWeight: 600
    lineHeight: 1.35
    letterSpacing: "0.05em"
  data:
    fontFamily: "Cascadia Code, JetBrains Mono, Consolas, ui-monospace, monospace"
    fontSize: "16px"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "normal"
rounded:
  sm: "6px"
  button: "7px"
  md: "8px"
spacing:
  sm: "8px"
  md: "12px"
  lg: "16px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.on-solid}"
    typography: "{typography.body}"
    rounded: "7px"
    padding: "0 12px"
    height: "36px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
    textColor: "{colors.on-solid}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "#30464c"
    rounded: "7px"
    padding: "0 12px"
    height: "36px"
  mini-button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.on-solid}"
    rounded: "{rounded.sm}"
    padding: "0 11px"
    height: "32px"
  field:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.text}"
    rounded: "{rounded.sm}"
    height: "36px"
    padding: "0 10px"
  badge-ok:
    backgroundColor: "{colors.badge-ok-bg}"
    textColor: "{colors.text}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
  nav-item-active:
    backgroundColor: "{colors.surface-3}"
    textColor: "{colors.accent}"
    rounded: "{rounded.sm}"
---

# Design System: Llama Control Center

## Overview

**Creative North Star: "The Bench Instrument"**

Llama Control Center looks like a workbench instrument, not a chat studio and not a SaaS admin template. The operator sits with real VRAM, real ports, and a profile that either fits or does not. The interface stays quiet and precise so those facts can be read at a glance.

Structure is drawn with 1px hairlines. Human copy uses the system sans. Values the machine produced — endpoints, PIDs, fit, tok/s, versions — use the mono stack. Instrument teal appears on the primary action, the current selection, and the live lock. Its rarity is the point.

The system refuses Inter/Geist as a costume face, card-grid KPI chrome, leftover eyebrows/kickers, mascot delight, and any mix-in of the parked Obsidian Rail overhaul. A colored left edge is allowed only as the shared `--rail` token (inset 3px accent).

**Key Characteristics:**

- One token system, two themes (`:root` light, `[data-theme="dark"]`).
- Hairline structure; only overlays float.
- System sans for people; mono for machine data.
- Four real weights (400 / 500 / 600 / 700).
- Scarce instrument teal; semantic green / amber / red for fit and status.
- Flat, exact, state-first controls. No hover lift on in-flow surfaces.

## Colors

A cool paper bench in light, a near-black instrument face in dark, with one teal accent family and three status hues.

### Primary
- **Instrument teal** (`colors.accent` / `colors.accent-dark`): Start, the 3px rail, focus rings, live/selected marks. Hover uses `accent-hover` / `accent-hover-dark`. Text on a solid teal fill is `on-solid` (white in light, page ground in dark) so contrast holds in both themes.

### Neutral
- **Bench paper / rack ground** (`bg` / `bg-dark`): page canvas.
- **Panel** (`surface` / `surface-dark`): sidebar, cards, dialogs.
- **Recessed** (`surface-2`, `surface-3` and dark pairs): fields, grouped rows, tinted wells.
- **Ink** (`text` / `text-dark`): body. `text-secondary` and `muted` for supporting copy; on a tinted status surface, mix from that hue rather than dropping raw gray.
- **Hairline** (`border` / `border-strong`): structure and stronger strokes.

### Status
- **Good** (`green`, badge-ok fill): comfortable fit, listening, launchable.
- **Tight** (`amber`, badge-warn fill): caution, needs setup.
- **Near limit / danger** (`red`, badge-error fill): stop, crash, near-limit fit.

**The Scarce Accent Rule.** Instrument teal is for primary action, current selection, focus, and live state. It is not a wash, a sidebar fill, or a decorative stripe.

**The Semantic Fit Rule.** Good / Tight / Near Limit map only to green / amber / red. Do not promote Tight to Good.

## Typography

**Display Font:** none. This is an operate surface; there is no display face.
**Body Font:** Segoe UI Variable / system UI sans (`--font-sans`)
**Label/Mono Font:** Cascadia Code, then JetBrains Mono, Consolas (`--font-mono`)

**Character:** Installed system faces only. Four weights that actually paint (400, 500, 600, 700). Inter, Geist, and fake weights (650 / 680 / 760) are rejected.

### Hierarchy
- **Title** (700, 15px, 1.2): brand name, panel titles, topbar heading.
- **Body** (400, 14px, 1.45): UI copy, dialogs, empty-state prose.
- **UI** (600, 13px buttons / 12px mini-buttons): controls.
- **Label** (600, 11px, 0.05em, often uppercase, mono): metric labels, table headers, section titles, badge text.
- **Data** (700, 16–18px, tabular-nums, mono): endpoints, fit verdict, metric values.

**The Machine Face Rule.** If the machine produced the value, or the label classifies one, it is mono. If a person reads or clicks it, it is sans.

## Layout

Two-column shell: sidebar then main. The first grid track is 218px; a later layer widens it to `clamp(236px, 14vw, 294px)`. Main is `minmax(0, 1fr)` so the Console Stage can go full width — do not reintroduce a 52rem stage cap.

Console uses session tabs (Stage / Chat / Logs / Server). Inventory and Tools are separate destinations, not a long scroll of nav lies.

Rhythm is tight inside a group (8px) and a step looser between groups (12–16px). Form grids are two columns, collapsing at 900px and 560px. Coarse pointers get 44px targets. Reduced motion kills authored animation in one last-word media block.

## Elevation & Depth

In-flow surfaces are flat: 1px hairline plus an optional 1px inset highlight. Depth between page, panel, and well is tonal (`bg` → `surface` → `surface-2` / `surface-3`).

Shadows belong to things that actually float: settings/confirm dialogs, popup menus, toasts, the command palette. Zero-offset colored halos are not depth; the 3px accent ring on focus is a focus mark, not a shadow.

### Shadow Vocabulary
- **Overlay** (`--shadow` light: `0 1px 2px rgba(15, 23, 42, 0.04), 0 18px 44px rgba(15, 23, 42, 0.035)`): dialogs and floating chrome.
- **Rail** (`--rail`: `inset 3px 0 0` accent): selected row, active nav, listening lock, palette highlight. Not a second stripe language.
- **Inset highlight** (`--inset-top`): a 1px top hairline of light, not a drop shadow.

**The Hairline Rule.** Structure is a 1px rule. If it is in the page flow, it does not drop a shadow.

**The One Rail Rule.** A colored left edge exists only as `--rail`. Do not invent a second stripe thickness or color.

## Shapes

Gently squared: 8px on panels, marks, and the radius token; 6px on fields, mini-buttons, and menus; 7px on the larger `.button`. No pills except compact toast actions. No hard-offset neobrutalist blocks.

Borders are 1px `border` or `border-strong`. Selected and live states add the rail, not a thicker frame.

## Components

Flat, exact, state-first. Default, hover, focus-visible, active, disabled, and busy are required. Hover retints; it does not lift.

### Buttons
- **Shape:** 7px on `.button`, 6px on `.mini-button`.
- **Primary:** instrument teal fill, `on-solid` label, 36px / 32px min-height. Start on Stage is 44px and full width.
- **Secondary / ghost:** surface fill, 1px border, muted ink. Hover mixes 10% accent into the surface.
- **Danger:** `red` fill for Stop / destructive confirms.
- **Hover / Focus:** hover is a color shift only. Focus-visible is a 2px accent outline, offset 2px.
- **Busy:** generic busy hides the label behind a spinner. The Start control is the exception: while waiting to listen, the label stays visible and the play glyph hides.

### Chips
- **Style:** 1px badge border, tinted fill, mono 11px. OK / warn / error use the semantic badge tokens.
- **State:** fit and launchability only. Not a filter chip system.

### Cards / Containers
- **Corner Style:** 8px (`--radius`).
- **Background:** `surface` or a status tint (estimate cards, launch lock).
- **Shadow Strategy:** none in flow; rail on the listening lock and selected rows.
- **Border:** 1px `border`, or the matching badge border when the card is a fit/status well.
- **Internal Padding:** 12–16px.

### Inputs / Fields
- **Style:** 36px tall, 6px radius, 1px border, recessed `surface-2` mix.
- **Focus:** accent border plus a 3px accent halo (`color-mix` 18%).
- **Applied (Smart Fit):** brief accent ring using the existing field-applied flash, then it settles.

### Navigation
- **Destinations:** Console, Inventory, Tools. Active item uses a light accent wash plus `--rail`.
- **Session tabs:** Stage / Chat / Logs / Server on Console only.
- **Sidebar:** sticky, hairline right edge, live hardware above the API footer.

### Launch lock (signature)
The listening readout on Stage after Start succeeds: OK badge, mono endpoint, PID, Copy URL, Open Chat. Same good-status well as a comfortable fit card, plus `--rail`. It is state, not decoration.

## Do's and Don'ts

### Do:
- **Do** put machine values in `--font-mono` with tabular nums.
- **Do** use `--rail` for selected, current, and listening.
- **Do** keep Stage full width of the main column.
- **Do** name live state as an endpoint (`Listening on 127.0.0.1:18100`).
- **Do** respect `prefers-reduced-motion` with the existing last-word kill switch.

### Don't:
- **Don't** load Inter, Geist, or any display face. Use the system sans + mono stacks.
- **Don't** add panel eyebrows or kickers.
- **Don't** draw a colored left border except via `--rail`.
- **Don't** mix in Obsidian Rail tokens or treat that parked overhaul as current.
- **Don't** celebrate ordinary clicks, autoplay sound, or delay Start to stage a flourish.
- **Don't** re-cap the Console Stage at 52rem.
- **Don't** treat Tight fit as Good.
