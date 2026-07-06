import type { Metadata } from "next";
import AppShell from "./sidebar";
import "./globals.css";

export const metadata: Metadata = {
  title: "Orgos",
  description: "A self-organizing agile engineering team",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="flex min-h-screen">
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
