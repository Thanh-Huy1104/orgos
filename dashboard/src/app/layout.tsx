import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Quant Desk",
  description: "Cointegration research desk for the Icarus engine",
};

const nav = [
  { href: "/", label: "Desk", icon: "◫" },
  { href: "/scanner", label: "Scanner", icon: "⊞" },
  { href: "/signals", label: "Signals", icon: "⚡" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="flex min-h-screen">
        <aside className="w-56 shrink-0 border-r flex flex-col" style={{ borderColor: "var(--border)", background: "var(--bg-sidebar)" }}>
          <div className="h-14 flex items-center px-4 border-b" style={{ borderColor: "var(--border)" }}>
            <Link href="/" className="font-semibold text-lg tracking-tight" style={{ color: "var(--text-primary)" }}>
              Quant Desk
            </Link>
          </div>
          <nav className="flex flex-col gap-0.5 p-3 flex-1">
            {nav.map(({ href, label, icon }) => (
              <Link key={href} href={href} className="sidebar-link">
                <span className="text-base">{icon}</span>
                {label}
              </Link>
            ))}
          </nav>
          <div className="p-3 border-t text-xs" style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}>
            Quant Fund · v1.0
          </div>
        </aside>
        <main className="flex-1 p-6 min-w-0 overflow-y-auto" style={{ height: "calc(100vh - 0px)" }}>{children}</main>
      </body>
    </html>
  );
}
