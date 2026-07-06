"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, useCallback } from "react";

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

export default function AppShell({ children }: { children: React.ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const close = useCallback(() => setSidebarOpen(false), []);

  return (
    <>
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
    </>
  );
}
