"use client";

import { useEffect } from "react";

export function SlidePanel({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, onClose]);

  return (
    <>
      {/* backdrop */}
      <div
        className={`slide-backdrop ${open ? "open" : ""}`}
        onClick={onClose}
      />
      {/* panel */}
      <aside className={`slide-panel ${open ? "open" : ""}`}>
        <div className="slide-panel-header">
          <h3 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
            {title}
          </h3>
          <button onClick={onClose} className="slide-panel-close" aria-label="Close panel">
            ✕
          </button>
        </div>
        <div className="slide-panel-body">{children}</div>
      </aside>
    </>
  );
}
