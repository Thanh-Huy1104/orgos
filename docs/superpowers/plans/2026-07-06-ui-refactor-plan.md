# UI Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Full dashboard UI overhaul — modern design tokens, reusable component system, dark sidebar, responsive, accessible, across all 14 pages.

**Architecture:** New design tokens in globals.css using slate+indigo palette. Five shared UI components extracted to `src/lib/ui.tsx`. Layout rewritten with dark sidebar + mobile hamburger using `usePathname()` for active nav. Each page refactored to use the new component system.

**Tech Stack:** React 19, Next.js 16, Tailwind CSS 4, TypeScript 5, D3 (existing)

## Global Constraints

- Remove all dead CSS: ~220 lines (journal, desk, stale classes)
- Every page uses consistent `px-6 py-6` padding — no double padding
- Every form input gets a `<label>`
- All interactive elements get `:focus-visible` ring
- Sidebar collapses to hamburger at < 768px
- Color contrast meets WCAG AA (4.5:1)
- All builds must pass: `npx tsc --noEmit && npx next build`

---

### Task 1: Design tokens + globals.css rewrite

**Files:**
- Modify: `src/app/globals.css`

**Interfaces:**
- Produces: CSS custom properties `--bg-primary`, `--bg-secondary`, `--bg-sidebar`, `--bg-hover`, `--border`, `--text-primary`, `--text-secondary`, `--text-muted`, `--accent`, `--accent-light`, `--green`, `--green-bg`, `--red`, `--red-bg`, `--yellow`, `--yellow-bg`, `--blue`, `--blue-bg`

- [ ] **Step 1: Replace `:root` block with new design tokens**

Replace lines 1-22 of `src/app/globals.css`:

```css
@import "tailwindcss";

:root {
  --bg-primary: #F8FAFC;
  --bg-secondary: #F1F5F9;
  --bg-sidebar: #0F172A;
  --bg-hover: #E2E8F0;
  --border: #CBD5E1;
  --text-primary: #0F172A;
  --text-secondary: #475569;
  --text-muted: #94A3B8;
  --accent: #4F46E5;
  --accent-light: #E0E7FF;
  --green: #059669;
  --green-bg: #ECFDF5;
  --red: #DC2626;
  --red-bg: #FEF2F2;
  --yellow: #D97706;
  --yellow-bg: #FFFBEB;
  --blue: #2563EB;
  --blue-bg: #EFF6FF;
}
```

- [ ] **Step 2: Update body background**

Replace line 24-28:

```css
body {
  background: var(--bg-primary);
  color: var(--text-primary);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Inter', sans-serif;
}
```

- [ ] **Step 3: Add focus-visible utility**

Insert after the body block (after line 28):

```css
*:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
  border-radius: 4px;
}
```

- [ ] **Step 4: Update sidebar-link styles for dark sidebar**

Replace lines 30-48 (`.sidebar-link` and `.sidebar-link.active`):

```css
.sidebar-link {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 14px;
  color: #94A3B8;
  transition: all 0.15s;
  text-decoration: none;
}
.sidebar-link:hover {
  background: rgba(255,255,255,0.06);
  color: #F1F5F9;
}
.sidebar-link.active {
  background: rgba(79,70,229,0.2);
  color: #C7D2FE;
  font-weight: 500;
}
```

- [ ] **Step 5: Delete dead CSS sections**

Remove entirely:
- Lines 460-604: `.journal-*` block (all journal layout classes + @media query)
- Lines 949-991: `.desk-*` block (all desk layout classes + @media query)
- Lines 152-156: `.modal-open` class
- Lines 44-48: original `.sidebar-link.active` (already replaced above)

Verify with bash:
```bash
rg "journal-layout|desk-layout|modal-open" src/app/globals.css
```
Expected: no matches

- [ ] **Step 6: Add responsive sidebar classes**

Append to end of globals.css:

```css
.sidebar-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.4);
  z-index: 50;
  display: none;
}

@media (max-width: 767px) {
  .sidebar-overlay.open {
    display: block;
  }
  .sidebar-panel {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    width: 260px;
    z-index: 51;
    transform: translateX(-100%);
    transition: transform 0.25s ease;
  }
  .sidebar-panel.open {
    transform: translateX(0);
  }
}
```

- [ ] **Step 7: Commit**

```bash
git add src/app/globals.css
git commit -m "feat: new design tokens, focus-visible, remove dead CSS, responsive sidebar classes"
```

---

### Task 2: Reusable UI components

**Files:**
- Create: `src/lib/ui.tsx`

**Interfaces:**
- Produces: `Heading`, `Button`, `Card`, `Badge`, `Input` React components

- [ ] **Step 1: Create `src/lib/ui.tsx`**

```tsx
import React from "react";

export function Heading({
  level = 1,
  className = "",
  children,
}: {
  level?: 1 | 2 | 3;
  className?: string;
  children: React.ReactNode;
}) {
  const Tag = `h${level}` as keyof JSX.IntrinsicElements;
  const sizes: Record<number, string> = {
    1: "text-2xl font-bold tracking-tight",
    2: "text-xl font-semibold",
    3: "text-base font-semibold",
  };
  return <Tag className={`${sizes[level]} ${className}`} style={{ color: "var(--text-primary)" }}>{children}</Tag>;
}

export function Button({
  variant = "primary",
  size = "md",
  className = "",
  children,
  ...props
}: {
  variant?: "primary" | "secondary" | "danger" | "ghost";
  size?: "sm" | "md";
  className?: string;
  children: React.ReactNode;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const base = "inline-flex items-center justify-center font-medium transition-all duration-150 cursor-pointer border-none rounded-lg";
  const sizes: Record<string, string> = {
    sm: "text-xs px-3 py-1.5",
    md: "text-sm px-4 py-2",
  };
  const variants: Record<string, string> = {
    primary: "bg-[var(--accent)] text-white hover:brightness-110",
    secondary: "bg-[var(--bg-secondary)] text-[var(--text-primary)] border border-[var(--border)] hover:bg-[var(--bg-hover)]",
    danger: "bg-[var(--red)] text-white hover:brightness-110",
    ghost: "text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-secondary)]",
  };
  return (
    <button className={`${base} ${sizes[size]} ${variants[variant]} ${className}`} {...props}>
      {children}
    </button>
  );
}

export function Card({
  hover = false,
  className = "",
  children,
  ...props
}: {
  hover?: boolean;
  className?: string;
  children: React.ReactNode;
} & React.HTMLAttributes<HTMLDivElement>) {
  const hoverClass = hover ? "cursor-pointer transition-shadow hover:shadow-sm hover:border-[var(--accent)]" : "";
  return (
    <div
      className={`bg-white border border-[var(--border)] rounded-xl p-4 ${hoverClass} ${className}`}
      {...props}
    >
      {children}
    </div>
  );
}

export function Badge({
  variant = "gray",
  className = "",
  children,
}: {
  variant?: "green" | "red" | "yellow" | "blue" | "gray";
  className?: string;
  children: React.ReactNode;
}) {
  const colors: Record<string, string> = {
    green: "bg-[var(--green-bg)] text-[var(--green)]",
    red: "bg-[var(--red-bg)] text-[var(--red)]",
    yellow: "bg-[var(--yellow-bg)] text-[var(--yellow)]",
    blue: "bg-[var(--blue-bg)] text-[var(--blue)]",
    gray: "bg-[var(--bg-secondary)] text-[var(--text-secondary)]",
  };
  return (
    <span className={`text-[11px] font-medium px-2 py-0.5 rounded-md ${colors[variant]} ${className}`}>
      {children}
    </span>
  );
}

export function Input({
  label,
  className = "",
  ...props
}: {
  label: string;
  className?: string;
} & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="block" style={{ color: "var(--text-secondary)", fontSize: 13 }}>
      {label}
      <input
        className={`mt-1 block w-full input ${className}`}
        {...props}
      />
    </label>
  );
}
```

- [ ] **Step 2: Type-check**

```bash
npx tsc --noEmit
```
Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add src/lib/ui.tsx
git commit -m "feat: add reusable UI components (Heading, Button, Card, Badge, Input)"
```

---

### Task 3: Layout rewrite (dark sidebar, mobile, active nav)

**Files:**
- Modify: `src/app/layout.tsx`

**Interfaces:**
- Consumes: `.sidebar-link`, `.sidebar-link.active`, `.sidebar-overlay`, `.sidebar-panel` from globals.css
- Produces: Layout with dark sidebar, `usePathname()`, hamburger toggle at < 768px

- [ ] **Step 1: Rewrite `src/app/layout.tsx`**

```tsx
"use client";
import type { Metadata } from "next";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, useCallback } from "react";
import "./globals.css";

const nav = [
  { href: "/", label: "Scoreboard", icon: "◫" },
  { href: "/sprints", label: "Sprints", icon: "❖" },
  { href: "/team", label: "Topology", icon: "◈" },
  { href: "/dora", label: "DORA", icon: "▤" },
  { href: "/lab", label: "Lab", icon: "⚗" },
];

function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const pathname = usePathname();

  return (
    <>
      <div className={`sidebar-overlay ${open ? "open" : ""}`} onClick={onClose} />
      <aside
        className={`sidebar-panel lg:relative lg:translate-x-0 w-56 shrink-0 border-r flex flex-col ${open ? "open" : ""}`}
        style={{ borderColor: "rgba(255,255,255,0.08)", background: "var(--bg-sidebar)" }}
        onTransitionEnd={(e) => {
          if (e.propertyName === "transform" && !open) onClose();
        }}
      >
        <div className="h-14 flex items-center px-4 border-b" style={{ borderColor: "rgba(255,255,255,0.08)" }}>
          <Link href="/" className="font-semibold text-lg tracking-tight" style={{ color: "#F1F5F9" }}>
            Orgos
          </Link>
        </div>
        <nav className="flex flex-col gap-0.5 p-3 flex-1">
          {nav.map(({ href, label, icon }) => (
            <Link
              key={href}
              href={href}
              className={`sidebar-link ${pathname === href ? "active" : ""}`}
              onClick={onClose}
            >
              <span className="text-base">{icon}</span>
              {label}
            </Link>
          ))}
        </nav>
        <div className="p-3 border-t text-xs" style={{ borderColor: "rgba(255,255,255,0.08)", color: "#64748B" }}>
          agile-pivot
        </div>
      </aside>
    </>
  );
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const close = useCallback(() => setSidebarOpen(false), []);

  return (
    <html lang="en">
      <body className="flex min-h-screen">
        <Sidebar open={sidebarOpen} onClose={close} />
        <div className="flex flex-col flex-1 min-w-0">
          <div className="lg:hidden flex items-center h-14 px-4 border-b" style={{ borderColor: "var(--border)", background: "var(--bg-primary)" }}>
            <button
              onClick={() => setSidebarOpen(true)}
              className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] p-1"
              aria-label="Open menu"
            >
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <path d="M3 12h18M3 6h18M3 18h18" />
              </svg>
            </button>
            <Link href="/" className="ml-3 font-semibold text-lg" style={{ color: "var(--text-primary)" }}>
              Orgos
            </Link>
          </div>
          <main className="flex-1 min-w-0 overflow-y-auto" style={{ height: "calc(100vh - 0px)" }}>
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
```

- [ ] **Step 2: Type-check and build**

```bash
npx tsc --noEmit && npx next build 2>&1 | tail -5
```
Expected: no errors, successful build

- [ ] **Step 3: Commit**

```bash
git add src/app/layout.tsx
git commit -m "feat: dark sidebar, active nav, mobile hamburger menu"
```

---

### Task 4: Scoreboard page (`/`)

**Files:**
- Modify: `src/app/page.tsx`

**Interfaces:**
- Consumes: `Heading`, `Card` from `@/lib/ui`
- Produces: Polished scoreboard with consistent components

- [ ] **Step 1: Read current file to understand structure**

```bash
# Already known from audit — re-read to confirm
```

- [ ] **Step 2: Rewrite `src/app/page.tsx`**

```tsx
"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { Heading, Card, Badge } from "@/lib/ui";

type Stat = { label: string; value: number | string; color: string };

export default function HomePage() {
  const [data, setData] = useState<{ tier: string; streak: string[]; stats: Stat[] } | null>(null);

  useEffect(() => {
    fetch("/api/dashboard").then((r) => r.json()).then(setData);
  }, []);

  if (!data) return <div className="p-6">Loading...</div>;

  return (
    <div className="px-6 py-6 space-y-8">
      <div>
        <Heading level={1}>Scoreboard</Heading>
        <div className="mt-2">
          <Badge variant={data.tier === "gold" ? "yellow" : data.tier === "silver" ? "gray" : "blue"}>
            DORA {data.tier.toUpperCase()}
          </Badge>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {data.stats.map((s) => (
          <Card key={s.label} className="text-center">
            <div className="text-2xl font-bold" style={{ color: s.color }}>{s.value}</div>
            <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>{s.label}</div>
          </Card>
        ))}
      </div>

      <div>
        <Heading level={2}>Sprint Streak</Heading>
        <div className="flex gap-1.5 mt-2 flex-wrap">
          {data.streak.map((color, i) => (
            <span
              key={i}
              title={`Sprint ${i + 1}`}
              className="w-3.5 h-3.5 rounded-sm"
              style={{ background: color, opacity: color === "#E2E8F0" ? 0.3 : 1 }}
            />
          ))}
        </div>
      </div>

      <div>
        <Heading level={2}>Quick Links</Heading>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-2">
          {[
            { href: "/sprints", label: "Sprints ▶" },
            { href: "/proposals", label: "Proposals ▶" },
            { href: "/org", label: "Organization ▶" },
          ].map(({ href, label }) => (
            <Link key={href} href={href}>
              <Card hover className="text-center">
                <div className="font-medium" style={{ color: "var(--text-primary)" }}>{label}</div>
              </Card>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Verify the actual API response shape**

```bash
# Check the actual response from /api/dashboard to ensure types match
rg -l "dashboard" orgos/api.py
```

- [ ] **Step 4: Type-check and build**

```bash
npx tsc --noEmit
```
Expected: no errors. If API types mismatch, fix the useState type.

- [ ] **Step 5: Commit**

```bash
git add src/app/page.tsx
git commit -m "feat: polish scoreboard with Heading, Card, Badge components"
```

---

### Task 5: Sprints list page

**Files:**
- Modify: `src/app/sprints/page.tsx`

**Interfaces:**
- Consumes: `Heading`, `Card` from `@/lib/ui`

- [ ] **Step 1: Rewrite `src/app/sprints/page.tsx`**

```tsx
"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { Heading, Card, Badge } from "@/lib/ui";

type Sprint = { id: string; branch: string; status: string; started_at: string; picked_issue: string };

export default function SprintsPage() {
  const [sprints, setSprints] = useState<Sprint[]>([]);
  useEffect(() => {
    fetch("/api/sprints").then((r) => r.json()).then(setSprints);
  }, []);

  return (
    <div className="px-6 py-6 space-y-6">
      <Heading level={1}>Sprints</Heading>
      <Card className="overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left" style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}>
              <th className="px-4 py-2.5 font-medium">ID</th>
              <th className="px-4 py-2.5 font-medium">Branch</th>
              <th className="px-4 py-2.5 font-medium">Status</th>
              <th className="px-4 py-2.5 font-medium">Started</th>
            </tr>
          </thead>
          <tbody>
            {sprints.map((s) => (
              <tr key={s.id} className="border-t border-[var(--border)] hover:bg-[var(--bg-secondary)] transition-colors">
                <td className="px-4 py-2.5">
                  <Link href={`/sprints/${s.id}`} className="font-medium" style={{ color: "var(--blue)" }}>
                    {s.id}
                  </Link>
                </td>
                <td className="px-4 py-2.5 font-mono text-xs" style={{ color: "var(--text-secondary)" }}>{s.branch}</td>
                <td className="px-4 py-2.5">
                  <Badge variant={s.status === "completed" ? "green" : s.status === "running" ? "blue" : "gray"}>
                    {s.status}
                  </Badge>
                </td>
                <td className="px-4 py-2.5 text-xs" style={{ color: "var(--text-muted)" }}>{s.started_at?.slice(0, 10)}</td>
              </tr>
            ))}
            {sprints.length === 0 && (
              <tr><td colSpan={4} className="px-4 py-8 text-center" style={{ color: "var(--text-muted)" }}>No sprints yet</td></tr>
            )}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
```

- [ ] **Step 2: Type-check**

```bash
npx tsc --noEmit
```
Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add src/app/sprints/page.tsx
git commit -m "feat: polish sprints list with Card, Badge, styled table"
```

---

### Task 6: Sprint detail page

**Files:**
- Modify: `src/app/sprints/[sprintId]/page.tsx`

**Interfaces:**
- Consumes: `Heading`, `Card`, `Badge`, `Button` from `@/lib/ui`

- [ ] **Step 1: Rewrite `src/app/sprints/[sprintId]/page.tsx`**

Read current file first to match the data types:

```tsx
"use client";
import { useEffect, useState, use } from "react";
import Link from "next/link";
import { Heading, Card, Badge, Button } from "@/lib/ui";

type Phase = { name: string; status: string; started_at?: string; finished_at?: string; reason?: string };
type Artifact = { name: string; content_type: string; content: string };
type SprintDetail = {
  id: string; branch: string; status: string; started_at: string; picked_issue: string;
  phases: Phase[]; artifacts: Artifact[];
};

export default function SprintDetailPage({ params }: { params: Promise<{ sprintId: string }> }) {
  const { sprintId } = use(params);
  const [sprint, setSprint] = useState<SprintDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`/api/sprints/${sprintId}`)
      .then((r) => r.json())
      .then(setSprint)
      .catch(() => setError("Failed to load sprint"));
  }, [sprintId]);

  if (error) return <div className="px-6 py-6">Error: {error}</div>;
  if (!sprint) return <div className="px-6 py-6">Loading...</div>;

  const statusVariant = sprint.status === "completed" ? "green" : sprint.status === "running" ? "blue" : "gray";

  return (
    <div className="px-6 py-6 space-y-6 max-w-5xl">
      <div className="flex items-center gap-3">
        <Link href="/sprints" className="inline-flex" style={{ color: "var(--text-muted)" }}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M19 12H5m7-7l-7 7 7 7"/></svg>
        </Link>
        <Heading level={1}>{sprint.id}</Heading>
        <Badge variant={statusVariant}>{sprint.status}</Badge>
      </div>

      <div className="flex gap-4 text-sm" style={{ color: "var(--text-secondary)" }}>
        <span>Branch: <code className="font-mono text-xs bg-[var(--bg-secondary)] px-1 py-0.5 rounded">{sprint.branch}</code></span>
        <span>Started: {sprint.started_at?.slice(0, 10)}</span>
      </div>

      <div>
        <Heading level={2}>Phases</Heading>
        <div className="space-y-3 mt-2">
          {sprint.phases.map((p) => (
            <Card key={p.name}>
              <div className="flex items-center justify-between">
                <div>
                  <span className="font-semibold text-sm" style={{ color: "var(--text-primary)" }}>{p.name}</span>
                  {p.reason && <span className="text-xs ml-2" style={{ color: "var(--text-muted)" }}>— {p.reason}</span>}
                </div>
                <Badge variant={p.status === "complete" ? "green" : p.status === "running" ? "blue" : p.status === "failed" ? "red" : "gray"}>
                  {p.status}
                </Badge>
              </div>
              <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                {p.started_at && <span>Started: {p.started_at} </span>}
                {p.finished_at && <span>Finished: {p.finished_at}</span>}
              </div>
            </Card>
          ))}
          {sprint.phases.length === 0 && (
            <p className="text-sm" style={{ color: "var(--text-muted)" }}>No phases recorded for this sprint.</p>
          )}
        </div>
      </div>

      <div>
        <Heading level={2}>Artifacts</Heading>
        <div className="space-y-3 mt-2">
          {sprint.artifacts.map((a) => (
            <Card key={a.name}>
              <div className="font-mono text-sm font-medium" style={{ color: "var(--text-primary)" }}>{a.name}</div>
              <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>{a.content_type}</div>
              <details className="mt-2">
                <summary className="text-xs cursor-pointer" style={{ color: "var(--text-muted)" }}>Show content</summary>
                <pre className="text-xs whitespace-pre-wrap rounded-lg p-3 mt-2" style={{ background: "var(--bg-secondary)", maxHeight: 300, overflow: "auto" }}>
                  {a.content}
                </pre>
              </details>
            </Card>
          ))}
          {sprint.artifacts.length === 0 && (
            <p className="text-sm" style={{ color: "var(--text-muted)" }}>No artifacts found.</p>
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Type-check**

```bash
npx tsc --noEmit
```
Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add src/app/sprints/\[sprintId\]/page.tsx
git commit -m "feat: polish sprint detail with Card, Badge, Button components"
```

---

### Task 7: Team topology page

**Files:**
- Modify: `src/app/team/page.tsx`

**Interfaces:**
- Consumes: `Heading`, `Card`, `Badge`, `Button` from `@/lib/ui`

- [ ] **Step 1: Rewrite `src/app/team/page.tsx` — ADR section only (graph is fine)**

Replace the ADR section (lines 215-244 of current file) and the LegendDot:

Read current file, then apply these targeted edits:

- Replace the return block's JSX to use `Heading`, `Button`, `Card`, `Badge`
- Keep the D3 SVG graph section unchanged (it already fills correctly)
- Add SVG `<title>` and `<desc>` for accessibility

The full new file:

```tsx
"use client";
import { useEffect, useRef, useState } from "react";
import * as d3 from "d3";
import { Heading, Card, Badge, Button } from "@/lib/ui";

type Role = { name: string; tier: string; contribution: number };
type Edge = { from: string; to: string; weight: number };

type ADR = {
  id: number; kind: string; rationale: string; status: string;
  before_yaml: string; after_yaml: string; created_at: string;
};

const TIER_COLOR: Record<string, string> = {
  orchestrator: "#6366F1",
  worker: "#059669",
  validator: "#D97706",
  publisher: "#DC2626",
};

interface NodeDatum extends d3.SimulationNodeDatum {
  id: string;
  name: string;
  tier: string;
  color: string;
  val: number;
  contribution: number;
}

interface LinkDatum extends d3.SimulationLinkDatum<NodeDatum> {
  width: number;
}

export default function TeamPage() {
  const [topology, setTopology] = useState<{roles: Role[]; edges: Edge[]} | null>(null);
  const [adrs, setAdrs] = useState<Record<string, ADR[]> | null>(null);

  const graphBoxRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const refresh = () => {
    fetch("/api/team/topology").then((r) => r.json()).then(setTopology);
    fetch("/api/team/adrs").then((r) => r.json()).then(setAdrs);
  };
  useEffect(refresh, []);

  const act = async (id: number, verb: "approve" | "reject") => {
    await fetch(`/api/team/adrs/${id}/${verb}`, { method: "POST" });
    refresh();
  };

  useEffect(() => {
    if (!topology || !svgRef.current || !graphBoxRef.current) return;

    const container = graphBoxRef.current;
    const getDims = () => ({
      w: Math.floor(container.getBoundingClientRect().width),
      h: Math.floor(container.getBoundingClientRect().height),
    });
    const dims = getDims();
    if (dims.w === 0 || dims.h === 0) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    svg.append("title").text("Team topology force-directed graph");
    svg.append("desc").text("Interactive graph showing roles (nodes) and their relationships (edges). Drag nodes to rearrange.");

    svg.attr("viewBox", `0 0 ${dims.w} ${dims.h}`);

    const defs = svg.append("defs");
    defs.append("marker")
      .attr("id", "arrowhead")
      .attr("viewBox", "0 -5 10 10")
      .attr("refX", 22)
      .attr("refY", 0)
      .attr("markerWidth", 5)
      .attr("markerHeight", 5)
      .attr("orient", "auto")
      .append("path")
      .attr("d", "M0,-4L8,0L0,4")
      .attr("fill", "rgba(120,120,120,0.5)");

    const zoomGroup = svg.append("g");

    const nodes: NodeDatum[] = topology.roles.map((r) => ({
      id: r.name,
      name: r.name,
      tier: r.tier,
      color: TIER_COLOR[r.tier] ?? "#6B7280",
      val: 6 + r.contribution * 30,
      contribution: r.contribution,
      x: dims.w / 2 + (Math.random() - 0.5) * 200,
      y: dims.h / 2 + (Math.random() - 0.5) * 200,
    }));

    const links: LinkDatum[] = topology.edges.map((e) => ({
      source: e.from,
      target: e.to,
      width: 1 + e.weight * 6,
    }));

    const simulation = d3.forceSimulation<NodeDatum>(nodes)
      .force("link", d3.forceLink<NodeDatum, LinkDatum>(links).id((d) => d.id).distance(140))
      .force("charge", d3.forceManyBody().strength(-400))
      .force("center", d3.forceCenter(dims.w / 2, dims.h / 2))
      .force("collide", d3.forceCollide<NodeDatum>().radius((d) => d.val + 8));

    const linkGroup = zoomGroup.append("g")
      .selectAll<SVGLineElement, LinkDatum>("line")
      .data(links)
      .join("line")
      .attr("stroke", "rgba(120,120,120,0.4)")
      .attr("stroke-width", (d) => d.width)
      .attr("marker-end", "url(#arrowhead)");

    const nodeGroup = zoomGroup.append("g")
      .selectAll<SVGGElement, NodeDatum>("g")
      .data(nodes)
      .join("g")
      .attr("cursor", "grab");

    nodeGroup.call(
      d3.drag<SVGGElement, NodeDatum>()
        .on("start", (event, d) => {
          if (!event.active) simulation.alphaTarget(0.3).restart();
          d.fx = d.x;
          d.fy = d.y;
        })
        .on("drag", (event, d) => {
          d.fx = event.x;
          d.fy = event.y;
        })
        .on("end", (event, d) => {
          if (!event.active) simulation.alphaTarget(0);
          d.fx = null;
          d.fy = null;
        }) as any
    );

    nodeGroup.append("circle")
      .attr("r", (d) => d.val)
      .attr("fill", (d) => d.color)
      .attr("fill-opacity", 0.85)
      .attr("stroke", (d) => d.color)
      .attr("stroke-width", 1.5)
      .attr("stroke-opacity", 0.3);

    nodeGroup.append("text")
      .text((d) => d.name)
      .attr("text-anchor", "middle")
      .attr("dy", (d) => d.val + 14)
      .attr("font-size", 11)
      .attr("fill", "#475569")
      .attr("pointer-events", "none");

    simulation.on("tick", () => {
      linkGroup
        .attr("x1", (d) => (d.source as NodeDatum).x!)
        .attr("y1", (d) => (d.source as NodeDatum).y!)
        .attr("x2", (d) => (d.target as NodeDatum).x!)
        .attr("y2", (d) => (d.target as NodeDatum).y!);
      nodeGroup.attr("transform", (d) => `translate(${d.x},${d.y})`);
    });

    const zoomBehavior = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.2, 4])
      .on("zoom", (event) => {
        zoomGroup.attr("transform", event.transform.toString());
      });
    svg.call(zoomBehavior);

    const ro = new ResizeObserver(() => {
      const d = getDims();
      if (d.w === 0) return;
      svg.attr("viewBox", `0 0 ${d.w} ${d.h}`);
      simulation.force("center", d3.forceCenter(d.w / 2, d.h / 2));
      simulation.alpha(0.1).restart();
    });
    ro.observe(container);

    return () => {
      simulation.stop();
      ro.disconnect();
    };
  }, [topology]);

  if (!topology || !adrs) return <div className="px-6 py-6">Loading...</div>;

  return (
    <div className="px-6 py-6">
      <section className="mb-8">
        <Heading level={1} className="mb-3">Role topology</Heading>
        <div
          ref={graphBoxRef}
          className="border rounded-xl bg-white w-full"
          style={{ height: 500, position: "relative", overflow: "hidden", borderColor: "var(--border)" }}
        >
          <svg ref={svgRef} width="100%" height="100%" style={{ display: "block" }} />
        </div>
        <div className="mt-2 text-xs flex gap-4 flex-wrap" style={{ color: "var(--text-muted)" }}>
          {Object.entries(TIER_COLOR).map(([tier, color]) => (
            <span key={tier} className="inline-flex items-center gap-1.5">
              <span style={{ width: 8, height: 8, borderRadius: "50%", background: color, display: "inline-block" }} />
              {tier}
            </span>
          ))}
          <span>• node size = contribution</span>
          <span>• drag nodes to rearrange</span>
        </div>
      </section>

      <section>
        <Heading level={1} className="mb-3">ADRs</Heading>
        {["pending", "approved", "applied", "rejected"].map((bucket) => (
          <div key={bucket} className="mb-4">
            <Heading level={3} className="uppercase mb-2">{bucket}</Heading>
            <div className="space-y-2">
              {(adrs[bucket] ?? []).map((a) => (
                <Card key={a.id}>
                  <div className="flex justify-between items-start gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm font-medium" style={{ color: "var(--text-primary)" }}>
                          ADR-{String(a.id).padStart(3, "0")}
                        </span>
                        <Badge variant="gray">{a.kind}</Badge>
                      </div>
                      <div className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>{a.rationale}</div>
                    </div>
                    {bucket === "pending" && (
                      <div className="flex gap-2 shrink-0">
                        <Button variant="primary" size="sm" onClick={() => act(a.id, "approve")}>Approve</Button>
                        <Button variant="danger" size="sm" onClick={() => act(a.id, "reject")}>Reject</Button>
                      </div>
                    )}
                  </div>
                  <details className="mt-2">
                    <summary className="text-xs cursor-pointer" style={{ color: "var(--text-muted)" }}>Show diff</summary>
                    <pre className="text-xs whitespace-pre-wrap rounded-lg p-3 mt-2" style={{ background: "var(--bg-secondary)" }}>
                      {a.after_yaml}
                    </pre>
                  </details>
                </Card>
              ))}
              {(adrs[bucket] ?? []).length === 0 && (
                <p className="text-sm py-2" style={{ color: "var(--text-muted)" }}>None</p>
              )}
            </div>
          </div>
        ))}
      </section>
    </div>
  );
}
```

- [ ] **Step 2: Type-check and build**

```bash
npx tsc --noEmit
```
Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add src/app/team/page.tsx
git commit -m "feat: polish team topology with Button/Badge/Card, SVG accessibility"
```

---

### Task 8: DORA page

**Files:**
- Modify: `src/app/dora/page.tsx`

**Interfaces:**
- Consumes: `Heading`, `Card`, `Badge`, `Button` from `@/lib/ui`

- [ ] **Step 1: Rewrite `src/app/dora/page.tsx` without inline styles**

Read current file first. The current DORA page uses extensive inline styles. Replace all with component system:

```tsx
"use client";
import { useEffect, useState } from "react";
import { Heading, Card, Badge } from "@/lib/ui";

type Metric = { name: string; value: number; unit: string; tier: string; trend: string };
type Heuristic = { name: string; status: string; rule: string; description: string };
type HistoryRow = { sprint: string; [key: string]: string | number };

export default function DoraPage() {
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [heuristics, setHeuristics] = useState<{ candidate: Heuristic[]; active: Heuristic[] }>({ candidate: [], active: [] });
  const [history, setHistory] = useState<HistoryRow[]>([]);

  useEffect(() => {
    fetch("/api/dora").then((r) => r.json()).then((d) => {
      setMetrics(d.metrics ?? []);
      setHeuristics(d.heuristics ?? { candidate: [], active: [] });
      setHistory(d.history ?? []);
    });
  }, []);

  if (metrics.length === 0) return <div className="px-6 py-6">Loading...</div>;

  const tierVariant = (t: string) =>
    t === "gold" ? "yellow" : t === "silver" ? "gray" : t === "bronze" ? "yellow" : "blue";

  return (
    <div className="px-6 py-6 space-y-8" style={{ padding: "24px 32px" }}>
      <Heading level={1}>DORA Metrics</Heading>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {metrics.map((m) => (
          <Card key={m.name} className="flex flex-col items-center text-center">
            <Badge variant={tierVariant(m.tier)}>{m.tier.toUpperCase()}</Badge>
            <div className="text-3xl font-bold mt-2" style={{ color: "var(--text-primary)" }}>{m.value}</div>
            <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>{m.unit}</div>
            <div className="text-sm font-medium mt-2" style={{ color: "var(--text-secondary)" }}>{m.name}</div>
            <div className="text-xs mt-0.5" style={{ color: m.trend === "up" ? "var(--green)" : "var(--red)" }}>
              {m.trend === "up" ? "↑ improving" : "↓ declining"}
            </div>
          </Card>
        ))}
      </div>

      {history.length > 0 && (
        <div>
          <Heading level={2}>History</Heading>
          <Card className="overflow-x-auto p-0 mt-2">
            <table style={{ width: "100%", fontSize: 13, borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}>
                  {Object.keys(history[0]).map((k) => (
                    <th key={k} className="px-3 py-2 text-left font-medium text-xs uppercase">{k}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {history.map((row, i) => (
                  <tr key={i} className="border-t border-[var(--border)] hover:bg-[var(--bg-secondary)] transition-colors">
                    {Object.values(row).map((v, j) => (
                      <td key={j} className="px-3 py-2" style={{ color: "var(--text-secondary)" }}>{v}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
      )}

      {(["candidate", "active"] as const).map((group) => (
        <div key={group}>
          <Heading level={2} className="capitalize">{group} Heuristics</Heading>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-2">
            {heuristics[group].map((h) => (
              <Card key={h.name} className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="font-medium text-sm" style={{ color: "var(--text-primary)" }}>{h.name}</span>
                  <Badge variant={h.status === "active" ? "green" : "yellow"}>{h.status}</Badge>
                </div>
                <div className="font-mono text-xs" style={{ color: "var(--text-muted)" }}>{h.rule}</div>
                <div className="text-xs" style={{ color: "var(--text-secondary)" }}>{h.description}</div>
              </Card>
            ))}
            {heuristics[group].length === 0 && (
              <p className="text-sm" style={{ color: "var(--text-muted)" }}>None</p>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Verify the actual API response shape matches our types**

```bash
rg "GET.*dora" orgos/api.py -A 30
```
Adjust types if actual API differs.

- [ ] **Step 3: Type-check**

```bash
npx tsc --noEmit
```
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add src/app/dora/page.tsx
git commit -m "feat: polish DORA page — replace inline styles with component system"
```

---

### Task 9: Lab pages

**Files:**
- Modify: `src/app/lab/page.tsx`
- Modify: `src/app/lab/[sprintId]/page.tsx`

**Interfaces:**
- Consumes: `Heading`, `Card`, `Button`, `Input` from `@/lib/ui`

- [ ] **Step 1: Rewrite `src/app/lab/page.tsx`**

```tsx
"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { Heading, Card } from "@/lib/ui";

type Sprint = { id: string; status: string };

export default function LabPage() {
  const [sprints, setSprints] = useState<Sprint[]>([]);

  useEffect(() => {
    fetch("/api/sprints").then((r) => r.json()).then((all: Sprint[]) =>
      setSprints(all.filter((s) => s.status === "completed"))
    );
  }, []);

  return (
    <div className="px-6 py-6 space-y-6">
      <Heading level={1}>Counterfactual Lab</Heading>
      <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
        Run counterfactual experiments on completed sprints to evaluate policy changes.
      </p>
      <Card>
        <ul className="space-y-2">
          {sprints.map((s) => (
            <li key={s.id}>
              <Link href={`/lab/${s.id}`} className="text-sm font-medium hover:underline" style={{ color: "var(--blue)" }}>
                {s.id}
              </Link>
            </li>
          ))}
          {sprints.length === 0 && (
            <li className="text-sm" style={{ color: "var(--text-muted)" }}>No completed sprints available.</li>
          )}
        </ul>
      </Card>
    </div>
  );
}
```

- [ ] **Step 2: Rewrite `src/app/lab/[sprintId]/page.tsx`**

```tsx
"use client";
import { useEffect, useState, use } from "react";
import Link from "next/link";
import { Heading, Card, Button, Input, Badge } from "@/lib/ui";

type Mutation = { kind: string; args: Record<string, string> };
type Result = { sprint_id: string; mutation: Mutation; log: string };

export default function LabRunnerPage({ params }: { params: Promise<{ sprintId: string }> }) {
  const { sprintId } = use(params);
  const [mutationKind, setMutationKind] = useState("swap_role");
  const [args, setArgs] = useState<Record<string, string>>({});
  const [result, setResult] = useState<Result | null>(null);
  const [running, setRunning] = useState(false);

  const run = async () => {
    setRunning(true);
    const res = await fetch(`/api/lab/${sprintId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind: mutationKind, args }),
    });
    const data = await res.json();
    setResult(data);
    setRunning(false);
  };

  return (
    <div className="px-6 py-6 space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/lab" className="inline-flex" style={{ color: "var(--text-muted)" }}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M19 12H5m7-7l-7 7 7 7"/></svg>
        </Link>
        <Heading level={1}>Lab: {sprintId}</Heading>
      </div>

      <Card>
        <Heading level={2}>Mutation</Heading>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-3">
          <Input
            label="Kind"
            value={mutationKind}
            onChange={(e) => setMutationKind(e.target.value)}
          />
          <Input
            label="Rule / Reason"
            placeholder="rule"
            value={args.rule ?? ""}
            onChange={(e) => setArgs({ ...args, rule: e.target.value })}
          />
          <Input
            label="Why"
            placeholder="why"
            value={args.why ?? ""}
            onChange={(e) => setArgs({ ...args, why: e.target.value })}
          />
        </div>
        {mutationKind === "swap_role" && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-4">
            <Input
              label="Role Name"
              placeholder="role name"
              value={args.role_name ?? ""}
              onChange={(e) => setArgs({ ...args, role_name: e.target.value })}
            />
            <Input
              label="Alt Model"
              placeholder="alt model"
              value={args.alt_model ?? ""}
              onChange={(e) => setArgs({ ...args, alt_model: e.target.value })}
            />
          </div>
        )}
        <div className="mt-4">
          <Button variant="primary" onClick={run} disabled={running}>
            {running ? "Running..." : "Run Experiment"}
          </Button>
        </div>
      </Card>

      {result && (
        <Card>
          <Heading level={2}>Result</Heading>
          <div className="mt-2">
            <Badge variant="blue">{result.mutation.kind}</Badge>
          </div>
          <pre className="text-xs whitespace-pre-wrap rounded-lg p-3 mt-2" style={{ background: "var(--bg-secondary)", maxHeight: 500, overflow: "auto" }}>
            {result.log}
          </pre>
        </Card>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Type-check**

```bash
npx tsc --noEmit
```
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add src/app/lab/page.tsx src/app/lab/\[sprintId\]/page.tsx
git commit -m "feat: polish lab pages with Card, Input, Button components"
```

---

### Task 10: Requests, Proposals, Policies, Logs pages

**Files:**
- Modify: `src/app/requests/page.tsx`
- Modify: `src/app/proposals/page.tsx`
- Modify: `src/app/policies/page.tsx`
- Modify: `src/app/logs/page.tsx`

**Interfaces:**
- Consumes: `Heading`, `Card`, `Badge`, `Button`, `Input` from `@/lib/ui`

- [ ] **Step 1: Rewrite `src/app/requests/page.tsx`**

```tsx
"use client";
import { useEffect, useState } from "react";
import { Heading, Card, Badge, Button } from "@/lib/ui";

type CredentialRequest = { name: string; department: string; reason: string };
type ToolRequest = { name: string; department: string; reason: string };
type Proposals = { credentials: CredentialRequest[]; tools: ToolRequest[] };

export default function RequestsPage() {
  const [data, setData] = useState<Proposals | null>(null);

  const load = () => {
    fetch("/api/requests").then((r) => r.json()).then(setData);
  };
  useEffect(load, []);

  const resolve = async (kind: string, name: string) => {
    await fetch(`/api/requests/${kind}/${name}`, { method: "POST" });
    load();
  };

  if (!data) return <div className="px-6 py-6">Loading...</div>;

  return (
    <div className="px-6 py-6 space-y-6">
      <Heading level={1}>Requests</Heading>

      <div>
        <Heading level={2}>Credentials</Heading>
        <div className="space-y-3 mt-2">
          {data.credentials.map((c) => (
            <Card key={c.name} className="border-l-4" style={{ borderLeftColor: "var(--yellow)" }}>
              <div className="flex justify-between items-start gap-4">
                <div>
                  <div className="font-medium text-sm" style={{ color: "var(--text-primary)" }}>{c.name}</div>
                  <div className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>{c.reason}</div>
                  <div className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>{c.department}</div>
                </div>
                <Button variant="primary" size="sm" onClick={() => resolve("credential", c.name)}>
                  Resolve
                </Button>
              </div>
            </Card>
          ))}
          {data.credentials.length === 0 && <p className="text-sm" style={{ color: "var(--text-muted)" }}>None</p>}
        </div>
      </div>

      <div>
        <Heading level={2}>Tools</Heading>
        <div className="space-y-3 mt-2">
          {data.tools.map((t) => (
            <Card key={t.name} className="border-l-4" style={{ borderLeftColor: "var(--blue)" }}>
              <div className="flex justify-between items-start gap-4">
                <div>
                  <div className="font-medium text-sm" style={{ color: "var(--text-primary)" }}>{t.name}</div>
                  <div className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>{t.reason}</div>
                  <div className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>{t.department}</div>
                </div>
                <Button variant="primary" size="sm" onClick={() => resolve("tool", t.name)}>
                  Resolve
                </Button>
              </div>
            </Card>
          ))}
          {data.tools.length === 0 && <p className="text-sm" style={{ color: "var(--text-muted)" }}>None</p>}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Rewrite `src/app/proposals/page.tsx`**

Read current file first, then replace the button and badge patterns with components:

Key changes:
- Replace `className="btn btn-primary text-sm"` → `<Button variant="primary" size="sm">`
- Replace `className="btn btn-secondary text-xs"` → `<Button variant="secondary" size="sm">`
- Replace `className="badge badge-green"` → `<Badge variant="green">`
- Replace the tab bar inline styles with cleaner component-based layout
- Replace ad-hoc card divs with `<Card>`
- Add `px-6 py-6` wrapper (currently just `space-y-5`)

Since this file is large and mostly needs targeted component swaps, do targeted edits rather than full rewrite.

- [ ] **Step 3: Rewrite `src/app/policies/page.tsx`**

Replace:
- `className="input"` → `<Input label="...">`
- `className="btn btn-primary"` → `<Button variant="primary">`
- `className="badge badge-*"` → `<Badge variant="*">`
- `className="card"` → `<Card>`
- Add `px-6 py-6` wrapper (currently just `space-y-5`)

- [ ] **Step 4: Update `src/app/logs/page.tsx`**

Mostly already polished. Just:
- Add `px-6 py-6` wrapper to the `max-w-3xl mx-auto` div
- Any ad-hoc buttons → `<Button>`

- [ ] **Step 5: Type-check**

```bash
npx tsc --noEmit
```
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add src/app/requests/page.tsx src/app/proposals/page.tsx src/app/policies/page.tsx src/app/logs/page.tsx
git commit -m "feat: polish requests/proposals/policies/logs with component system"
```

---

### Task 11: Projects page + modal fix

**Files:**
- Modify: `src/app/projects/page.tsx`

**Interfaces:**
- Consumes: `Heading`, `Card`, `Badge`, `Button` from `@/lib/ui`

- [ ] **Step 1: Rewrite `src/app/projects/page.tsx` with modal fix**

Read current file first. Key fix: toggle the modal's visibility properly.

```tsx
"use client";
import { useEffect, useState } from "react";
import { Heading, Card, Badge, Button } from "@/lib/ui";

type Project = {
  id: string; objective: string; status: string; created_at: string;
  done: number; in_progress: number; todo: number;
};

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selected, setSelected] = useState<Project | null>(null);

  useEffect(() => {
    fetch("/api/projects").then((r) => r.json()).then(setProjects);
  }, []);

  const statusVariant = (s: string) =>
    s === "done" ? "green" : s === "running" ? "blue" : "gray";

  return (
    <div className="px-6 py-6 space-y-6">
      <Heading level={1}>Projects</Heading>

      <div className="space-y-3">
        {projects.map((p) => (
          <Card
            key={p.id}
            hover
            className="cursor-pointer"
            onClick={() => setSelected(p)}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setSelected(p); }}
          >
            <div className="flex items-center justify-between">
              <div>
                <div className="font-mono text-sm font-medium" style={{ color: "var(--text-primary)" }}>{p.id}</div>
                <div className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>{p.objective}</div>
              </div>
              <Badge variant={statusVariant(p.status)}>{p.status}</Badge>
            </div>
            <div className="text-xs mt-2" style={{ color: "var(--text-muted)" }}>
              Created: {p.created_at?.slice(0, 10)}
            </div>
          </Card>
        ))}
        {projects.length === 0 && <p className="text-sm" style={{ color: "var(--text-muted)" }}>No projects found.</p>}
      </div>

      {/* Modal */}
      {selected && (
        <>
          <div
            className="fixed inset-0 z-50 flex items-center justify-center"
            style={{ background: "rgba(0,0,0,0.4)", backdropFilter: "blur(2px)" }}
            onClick={() => setSelected(null)}
          >
            <div
              className="bg-white rounded-2xl p-6 max-w-xl w-[90%] max-h-[80vh] overflow-y-auto shadow-xl"
              style={{ border: "1px solid var(--border)" }}
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between mb-4">
                <Heading level={2}>{selected.id}</Heading>
                <button
                  onClick={() => setSelected(null)}
                  className="text-lg p-1 rounded-md hover:bg-[var(--bg-secondary)]"
                  style={{ color: "var(--text-muted)" }}
                  aria-label="Close"
                >
                  ×
                </button>
              </div>

              <Badge variant={statusVariant(selected.status)}>{selected.status}</Badge>
              <p className="text-sm mt-3" style={{ color: "var(--text-secondary)" }}>{selected.objective}</p>

              <div className="mt-4" style={{ background: "var(--bg-secondary)", borderRadius: 8, overflow: "hidden", height: 8 }}>
                <div style={{
                  height: "100%",
                  width: `${selected.done + selected.in_progress + selected.todo === 0 ? 0 : (selected.done / (selected.done + selected.in_progress + selected.todo)) * 100}%`,
                  background: "var(--green)",
                  borderRadius: 8,
                  transition: "width 0.3s",
                }} />
              </div>

              <div className="grid grid-cols-3 gap-4 mt-4">
                {[
                  { label: "Done", value: selected.done, color: "var(--green)" },
                  { label: "In Progress", value: selected.in_progress, color: "var(--yellow)" },
                  { label: "Todo", value: selected.todo, color: "var(--text-muted)" },
                ].map((s) => (
                  <Card key={s.label} className="text-center">
                    <div className="text-xl font-bold" style={{ color: s.color }}>{s.value}</div>
                    <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>{s.label}</div>
                  </Card>
                ))}
              </div>

              <div className="mt-6">
                <Button variant="primary" className="w-full">Dispatch Tasks</Button>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Type-check**

```bash
npx tsc --noEmit
```
Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add src/app/projects/page.tsx
git commit -m "feat: polish projects page, fix modal with proper open/close behavior"
```

---

### Task 12: Org page

**Files:**
- Modify: `src/app/org/page.tsx`

**Interfaces:**
- Consumes: `Heading`, `Card`, `Badge` from `@/lib/ui`

- [ ] **Step 1: Targeted edits on `src/app/org/page.tsx`**

Read current file. The org page is already polished with `.org-layout`. Make these targeted changes:
- Replace all ad-hoc badge divs with `<Badge variant="*">`
- Replace raw heading divs with `<Heading level={2|3}>`
- Any ad-hoc card-style divs → `<Card>`
- The `.org-detail-panel` agent cards, SOP cards, stats → use `<Card>` and `<Badge>`

Since the org page is large and complex with its own layout system, do surgical edits rather than full rewrite. Use `edit` tool for targeted replacements.

- [ ] **Step 2: Type-check**

```bash
npx tsc --noEmit
```
Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add src/app/org/page.tsx
git commit -m "feat: polish org page with Badge/Card/Heading components"
```

---

### Task 13: Calendar page + mobile grid

**Files:**
- Modify: `src/app/calendar/page.tsx`

**Interfaces:**
- Consumes: `Heading`, `Card`, `Button`, `Badge` from `@/lib/ui`

- [ ] **Step 1: Targeted edits on `src/app/calendar/page.tsx`**

Read current file. The calendar has its own CSS class system that's well-structured. Make targeted changes:
- Replace nav buttons with `<Button variant="secondary" size="sm">`
- Replace job cards in the job list section with `<Card>`
- Add `overflow-x: auto` wrapper around the calendar grid for mobile
- Any ad-hoc badges → `<Badge>`

Since the calendar uses its own CSS class names (`.calendar-page`, `.calendar-grid`, etc.), keep those and just swap inline button/badge patterns for components.

- [ ] **Step 2: Type-check**

```bash
npx tsc --noEmit
```
Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add src/app/calendar/page.tsx
git commit -m "feat: polish calendar with Button/Badge components, mobile overflow"
```

---

### Task 14: API cleanup

**Files:**
- Modify: `src/lib/api.ts`

**Interfaces:**
- Removes unused API functions and types

- [ ] **Step 1: Remove unused API functions from `src/lib/api.ts`**

Based on the audit, the following are never imported by any page component:
- `getDashboard()`, `getDepartments()`, `getDepartmentRuns()`, `getLogs()` (department variant)
- All Quant desk APIs: `getBook`, `getRisk`, `postHalt`, `startStrategist`, `getStrategistJob`, `getJournal`, `getVolatility`, `scanIvRank`, `startOptionsStrategist`, `getOptionsStrategistJob`, `getOptionsSurface`, `getOptionsSuggest`, `computeGreeks`, `previewPaperOrder`, `placePaperOrder`, `getPaperPositions`, `closePaperPosition`
- `getScheduler()`, `runScheduler()`, `runDepartment()`, `getCredentials()`, `getToolRequests()`, `createProject()`
- Unused types: `DashboardData`, `DepartmentMetric`, `RunEntry`

- [ ] **Step 2: Verify no remaining imports reference removed code**

```bash
rg "getDashboard|getBook|getRisk|postHalt|getJournal|getVolatility|scanIvRank|getScheduler|runScheduler|runDepartment|getCredentials|getToolRequests|createProject|DashboardData|DepartmentMetric|RunEntry" src/app/ --include="*.tsx"
```
Expected: no matches

- [ ] **Step 3: Type-check**

```bash
npx tsc --noEmit
```
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add src/lib/api.ts
git commit -m "chore: remove unused API functions and types"
```

---

### Task 15: Final verification

**Files:** All

- [ ] **Step 1: Full build**

```bash
npx tsc --noEmit && npx next build 2>&1 | tail -20
```
Expected: no errors, all pages listed in output

- [ ] **Step 2: Check for remaining dead CSS classes**

```bash
rg "journal-layout|desk-layout|modal-open" src/app/globals.css
```
Expected: no matches

- [ ] **Step 3: Check for inconsistent padding patterns**

```bash
rg "className=\"p-6\"" src/app/ --include="*.tsx"
```

All remaining `p-6` should be from loading/error states (acceptable) or intentional. No page should have `p-6` wrapping the entire content.

- [ ] **Step 4: Verify all imports resolve correctly**

```bash
rg "from \"@/lib/ui\"" src/app/ --include="*.tsx" --count
```
All pages that use the component system should show matches.

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "chore: final verification — build passes, dead code removed"
```
