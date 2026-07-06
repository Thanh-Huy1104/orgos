# UI Refactor — Design Spec

**Date:** 2026-07-06
**Scope:** Full dashboard UI overhaul — design system, components, pages, responsive, accessibility
**Approach:** Single unified change across all pages

---

## 1. Design Tokens (new palette)

Replace warm paper/cream with a modern slate + indigo scheme. Dark sidebar as visual anchor.

```css
:root {
  --bg-primary: #F8FAFC;       /* slate-50 */
  --bg-secondary: #F1F5F9;     /* slate-100 */
  --bg-sidebar: #0F172A;       /* slate-900 dark */
  --bg-hover: #E2E8F0;         /* slate-200 */
  --border: #CBD5E1;           /* slate-300 */
  --text-primary: #0F172A;     /* slate-900 */
  --text-secondary: #475569;   /* slate-600 */
  --text-muted: #94A3B8;       /* slate-400 */
  --accent: #4F46E5;           /* indigo-600 */
  --accent-light: #E0E7FF;     /* indigo-100 */
  --green: #059669;            /* unchanged */
  --green-bg: #ECFDF5;
  --red: #DC2626;              /* unchanged */
  --red-bg: #FEF2F2;
  --yellow: #D97706;           /* unchanged */
  --yellow-bg: #FFFBEB;
  --blue: #2563EB;             /* unchanged */
  --blue-bg: #EFF6FF;
}
```

---

## 2. Reusable Components

Extract duplicated patterns as shared components in `src/lib/`:

### `<Heading>`
- `level={1|2|3}` — consistent font sizes and weights
- h1: text-2xl font-bold, h2: text-xl font-semibold, h3: text-base font-semibold

### `<Button>`
- `variant="primary"|"secondary"|"danger"|"ghost"`, `size="sm"|"md"`
- Encodes consistent padding, radius, colors, focus-visible ring
- Replaces all ad-hoc Tailwind button classes and inline styles

### `<Card>`
- Wrapper with `bg-white border border-border rounded-xl p-4`
- Optional `hover` prop for interactive cards
- Replaces all ad-hoc `border rounded p-3 bg-white` patterns

### `<Badge>`
- `variant="green"|"red"|"yellow"|"blue"|"gray"`
- Replaces both the `.badge-*` CSS classes and ad-hoc inline badge styles
- Fixed sizing: 11px font, 2px 8px padding, 6px radius

### `<Input>`
- Wraps `<input>`/`<select>`/`<textarea>` with automatic `<label>`
- Uses existing `.input` focus ring pattern
- `label` prop for the label text, `type` prop forwarded
- Accessibility: always renders a `<label>` element

---

## 3. Layout Changes

### Sidebar (layout.tsx)
- Background: `var(--bg-sidebar)` (dark slate-900)
- Text/icons: white / slate-300
- Active route: `usePathname()` from next/navigation to apply `.active` styles
- Mobile: hamburger toggle, sidebar slides in/out. State managed via React state.
- Remove `p-6` from `<main>` — each page manages its own padding

### Main content
- `flex-1 min-w-0 overflow-y-auto` — no padding
- Pages use consistent `px-6 py-6` on their outermost wrapper

---

## 4. Page Refactor Details

### `/` — Scoreboard
- Wrap content in `px-6 py-6 space-y-8`
- Replace DORA tier `text-6xl` with `<Heading level={1}>`
- Replace 4 stat cards with `<Card>` + proper layout
- Replace streak dots with labeled circles
- Replace quick-link grid with `<Card>`-wrapped links

### `/sprints` — Sprint List
- `px-6 py-6`
- `<Heading level={1}>Sprints</Heading>`
- Table in a `<Card>` with styled thead, row hover
- Consistent alternating-row or divider styling

### `/sprints/[id]` — Sprint Detail
- `px-6 py-6 space-y-6 max-w-5xl`
- All phase cards and summary cards use `<Card>`
- Status badges use `<Badge>`
- Action buttons use `<Button>`

### `/team` — Topology
- `px-6 py-6`
- Graph container unchanged (D3 SVG, 500px height)
- Legend uses `<Badge>`-style colored dots
- ADR approve/reject buttons use `<Button>`
- ADR cards use `<Card>`

### `/dora` — DORA Metrics
- `px-6 py-6 space-y-8`
- Replace ALL inline styles with component system
- Metric cards use `<Card>`
- History table in a `<Card>` with overflow-x auto for mobile
- Tier badges use `<Badge>`
- Heuristic cards use `<Card>`

### `/lab` — Lab Picker
- `px-6 py-6`
- `<Heading level={1}>Counterfactual Lab</Heading>`
- Sprint list inside a `<Card>`
- Links styled as a proper list

### `/lab/[id]` — Lab Runner
- `px-6 py-6`
- Form controls use `<Input>` component
- Buttons use `<Button>`
- Results in a `<Card>` wrapper

### `/requests` — Requests
- `space-y-6` — no double padding issue
- Buttons use `<Button variant="primary">`
- Cards already use `.card` class — migrate to `<Card>`

### `/proposals` — Proposals
- `space-y-6`
- Tabs get better styling
- All buttons use `<Button>`
- Cards and badges use components

### `/logs` — Logs
- `max-w-3xl mx-auto px-6 py-6`
- Already polished — just confirm component consistency

### `/policies` — Policies
- `space-y-6`
- Form inputs use `<Input>` with proper labels
- Toggle chips get better styling
- Buttons use `<Button>`
- Policy cards use `<Card>`

### `/projects` — Projects
- `space-y-6`
- **Fix modal:** toggle `.modal-open` class when modal is visible
- Project cards use `<Card>`
- Status badges use `<Badge>`
- All buttons use `<Button>`

### `/org` — Organization
- Already polished — confirm heading consistency, responsive is fine
- Use `<Badge>` for agent tool counts
- Use `<Card>` for agent SOP cards

### `/calendar` — Calendar
- Nav buttons use `<Button variant="secondary" size="sm">`
- Job cards use `<Card>`
- Add mobile breakpoint: stack jobs below calendar, reduce grid cell size

---

## 5. Dead Code Removal

### CSS (globals.css)
- Remove `.journal-*` block (~144 lines)
- Remove `.desk-*` block (~42 lines)
- Remove `.sidebar-link.active` (replaced by `usePathname()`-based active class)
- Remove `.modal-open` (replaced by React state toggling)

### TypeScript
- Stale API functions in `api.ts` that have zero callers — remove

---

## 6. Accessibility

- Every form input gets a `<label>` via the `<Input>` component
- Every interactive element gets `:focus-visible` ring (accent color, 2px offset)
- Graphs get `<title>` and `<desc>` elements
- Keyboard-navigable: all clickable `<div>`s replaced with `<button>` or given `role`/`tabIndex`
- Color contrast: all text meets WCAG AA (4.5:1 for normal text)

---

## 7. Responsive

- Sidebar collapses to hamburger at < 768px
- Calendar grid reduces to fit mobile (4-column fallback or horizontal scroll for 7-cols)
- DORA history table: `overflow-x: auto` wrapper
- Lab runner: 2-column grid stacks at < 640px
- All `max-w-*` pages center correctly on mobile
- Org page already has responsive breakpoint at 800px — keep

---

## 8. Files Touched

| File | Action |
|------|--------|
| `layout.tsx` | Rewrite sidebar (dark bg, active nav, mobile collapse), remove main p-6 |
| `globals.css` | New tokens, remove dead code, add focus-visible, responsive utilities |
| `src/lib/ui.tsx` | New: Heading, Button, Card, Badge, Input components |
| `page.tsx` | Scoreboard rewrite |
| `sprints/page.tsx` | Card wrap, table polish |
| `sprints/[sprintId]/page.tsx` | Card/badge/button migration |
| `team/page.tsx` | Button/badge migration, SVG a11y |
| `dora/page.tsx` | Full inline-style replacement |
| `lab/page.tsx` | Card wrap |
| `lab/[sprintId]/page.tsx` | Input/button migration |
| `requests/page.tsx` | Button migration |
| `proposals/page.tsx` | Button/badge migration |
| `logs/page.tsx` | Confirm consistency |
| `policies/page.tsx` | Input with labels, button migration |
| `projects/page.tsx` | Fix modal, card/badge/button migration |
| `org/page.tsx` | Badge/card migration |
| `calendar/page.tsx` | Button migration, mobile grid fix |
| `api.ts` | Remove unused endpoints |
