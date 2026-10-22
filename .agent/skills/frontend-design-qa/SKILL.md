---
name: frontend-design-qa
description: Meticulous frontend UI/UX review, visual hierarchy audit, and pixel-perfect design QA checklist for web applications. Use after modifying or building frontend code to prevent alignment bugs, unstyled native controls, contrast failures, and theme inconsistencies.
---

# Frontend Design QA & Pixel-Perfect UI Audit

This skill establishes a strict, mandatory Quality Assurance workflow for all frontend work. Whenever you modify, create, or refactor HTML, CSS, or frontend JavaScript, execute this audit before presenting changes to the user.

---

## 1. Core Principles

- **Zero Tolerance for Native Form Glitches**: Never rely on browser-default `<select>`, `<input type="checkbox">`, or buttons. Browsers render native dropdown arrows and controls with inconsistent vertical alignments, jarring OS borders, and clipping issues.
- **Dynamic Theming Over Hardcoded Colors**: Never hardcode accent colors (e.g. `#ff0033`, `#ffffff`, `#e6002e`) on buttons, badges, or hover states. Every interactive surface must reference semantic CSS tokens (`--accent`, `--accent-hover`, `--accent-fg`, `--accent-surface`, `--accent-glow`).
- **Clean Inputs**: Never force-fill input boxes with hardcoded testing URLs or scratch data on mode change. Use placeholder text for format guidance and leave input values under user control.
- **Clutter Elimination**: Never display non-interactive dummy checkboxes or redundant feature cards. If backend features run automatically, do not burden the user interface with passive visual clutter.

---

## 2. Form Control Inspection Protocol

### A. `<select>` Dropdowns (Pixel-Perfect Alignment)
When inspecting or styling `<select>` elements:
```css
select.input {
  cursor: pointer;
  appearance: none;
  -webkit-appearance: none;
  -moz-appearance: none;
  /* Mathematically centered SVG chevron */
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%23aaaaaa' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 14px center;
  background-size: 14px 14px;
  padding-right: 40px; /* Essential to prevent text collision */
  height: 40px;
  line-height: 20px;
}

select.input:hover {
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%23f1f1f1' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E");
}

select.input option {
  background: var(--bg-card);
  color: var(--text-primary);
  padding: 8px 12px;
}
```
**Verification Checks**:
- [ ] Arrow icon is vertically centered exactly at `50%` (`center`), not sagging near the baseline.
- [ ] Native OS arrow is hidden across Chrome, Edge, Safari, and Firefox.
- [ ] Hover state illuminates the chevron stroke subtly to indicate interactivity.
- [ ] Text has at least 36px–40px right padding clearance.

### B. Input Fields & Textareas
- [ ] Placeholder text is subtle (`--text-faint` or `--text-muted`).
- [ ] Focused inputs show a sharp, glowing accent ring (`box-shadow: 0 0 0 2px var(--accent)`).
- [ ] Value is NOT hardcoded in JavaScript mode-switch handlers.

### C. Primary Buttons (`.btn-primary`)
- [ ] Default state background is `var(--accent)`.
- [ ] Text and SVG icons strictly use `var(--accent-fg)` (ensuring dark text on white/light buttons, white text on dark/colored buttons).
- [ ] Hover state strictly uses `var(--accent-hover)` and preserves readable `var(--accent-fg)`.
- [ ] Never transitions to an unrelated theme color on hover (e.g. flashing red in a white/monochrome theme).

---

## 3. The 5-Step Visual QA Audit Checklist

Whenever frontend changes are made, run this checklist:

1. **Alignment & Grid Scrutiny**:
   - Check vertical centering on all flex containers (`align-items: center`).
   - Check that icons and text baselines align harmoniously without 1px–3px jitter.
2. **Theme Switch Stress Test**:
   - Switch between **Default/Red**, **White/Obsidian**, and **Green/Emerald** palettes.
   - Inspect primary buttons, badges, active tabs, and hover states in each theme.
   - Verify that no white-on-white or dark-on-dark contrast failure occurs.
3. **Interactive Hover Check**:
   - Hover every button, dropdown, segmented button, and toggle.
   - Verify hover color transition feels natural and matches the active theme palette.
4. **Layout Density & Spacing**:
   - Adhere to 4px / 8px spacing rhythm (e.g., 8px, 12px, 16px, 24px).
   - Verify that cards and modal containers don't produce awkward blank voids or cramped collisions.
5. **Browser Subagent Visual Verification**:
   - Use the `browser_subagent` to render the view at 1920x1080 (and responsive breakpoints if applicable).
   - Visually confirm the DOM state and verify that zero emojis or misalignments are present.
