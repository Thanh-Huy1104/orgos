"use client";

import { useEffect, useState, useRef } from "react";
import { JournalEntry, getJournal, TrailStep, getTrail, startStrategist, startOptionsStrategist } from "@/lib/api";
import { Markdown } from "@/lib/markdown";
import { Digest, Trail } from "@/lib/trail";

// ── Helpers ──────────────────────────────────────────────────────────────

function fmtTime(ts: string): string {
  const d = new Date(ts);
  const now = new Date();
  const diff = now.getTime() - d.getTime();
  if (diff < 24 * 60 * 60 * 1000 && d.getDate() === now.getDate())
    return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  if (diff < 48 * 60 * 60 * 1000 && d.getDate() === now.getDate() - 1)
    return "Yesterday";
  if (diff < 7 * 24 * 60 * 60 * 1000)
    return d.toLocaleDateString(undefined, { weekday: "short" });
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function fmtFull(ts: string): string {
  return new Date(ts).toLocaleString();
}

// ── Dispatch modal ────────────────────────────────────────────────────────

type DispatchMode = "pairs" | "options";
type OptionsView = "neutral" | "bullish" | "bearish" | "volatile";

function DispatchModal({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const [objective, setObjective] = useState("");
  const [mode, setMode] = useState<DispatchMode>("pairs");
  const [view, setView] = useState<OptionsView>("neutral");
  const [sending, setSending] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Focus on mount — parent remounts via key when modal opens
  useEffect(() => {
    const t = setTimeout(() => inputRef.current?.focus(), 50);
    return () => clearTimeout(t);
  }, []);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !sending) onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, sending, onClose]);

  const dispatch = async () => {
    if (!objective.trim() || sending) return;
    setSending(true);
    try {
      if (mode === "options") {
        await startOptionsStrategist(objective, view, 2);
      } else {
        await startStrategist(objective, "equity", false, 2);
      }
    } catch { /* hunt runs in background regardless */ }
    finally {
      setSending(false);
      onClose();
      onDone();
    }
  };

  return (
    <>
      {open && <div className="modal-overlay" onClick={sending ? undefined : onClose} />}
      <div className={`modal ${open ? "modal-open" : ""}`} style={{ maxWidth: 640 }}>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <span className="text-2xl">✦</span>
            <h2 className="text-lg font-semibold">New Hunt</h2>
          </div>
          {!sending && (
            <button onClick={onClose} className="slide-panel-close">✕</button>
          )}
        </div>

        {sending ? (
          <div className="text-center py-10">
            <div className="text-3xl mb-3">✦</div>
            <div className="text-sm" style={{ color: "var(--text-muted)" }}>
              Dispatching…
            </div>
          </div>
        ) : (
          <>
            {/* Mode toggle */}
            <div className="flex gap-1 mb-4" style={{ borderBottom: "1px solid var(--border)" }}>
              {(["pairs", "options"] as DispatchMode[]).map((m) => (
                <button
                  key={m}
                  onClick={() => setMode(m)}
                  className="text-sm px-3 py-1.5"
                  style={{
                    borderBottom: mode === m ? "2px solid var(--accent)" : "2px solid transparent",
                    color: mode === m ? "var(--text-primary)" : "var(--text-muted)",
                    background: "none",
                    cursor: "pointer",
                    fontWeight: mode === m ? 600 : 400,
                  }}
                >
                  {m === "pairs" ? "Pair Hunting" : "Options Edge"}
                </button>
              ))}
            </div>

            <p className="text-sm mb-4" style={{ color: "var(--text-muted)", lineHeight: 1.6 }}>
              {mode === "pairs" ? (
                <>
                  Describe what you want the strategist to hunt for. It reasons about where
                  non-obvious cointegration might live, proposes its own ticker universes,
                  tests each with the scanner, and reports back — no hardcoded universe.
                </>
              ) : (
                <>
                  Describe an options edge to hunt. The agent scans news catalysts for candidate
                  tickers, runs IV-surface and vol scans on each, and recommends a defined-risk
                  options structure only when a structural edge exists.
                </>
              )}
            </p>
            <textarea
              ref={inputRef}
              className="input w-full"
              rows={5}
              placeholder={mode === "pairs"
                ? "e.g. Within US regulated electric & gas utilities, find the single most tradeable cointegrated pair…"
                : "e.g. Find a defined-risk options strategy on a liquid large-cap with high IV rank…"}
              value={objective}
              onChange={(e) => setObjective(e.target.value)}
              style={{ resize: "vertical", fontSize: 14, lineHeight: 1.6 }}
              disabled={sending}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) dispatch();
              }}
            />
            {mode === "options" && (
              <div className="flex items-center gap-2 mt-3">
                <span className="text-xs" style={{ color: "var(--text-muted)" }}>Directional view</span>
                <select
                  className="input"
                  value={view}
                  onChange={(e) => setView(e.target.value as OptionsView)}
                  style={{ fontSize: 13, padding: "4px 8px", width: "auto" }}
                  disabled={sending}
                >
                  <option value="neutral">neutral</option>
                  <option value="bullish">bullish</option>
                  <option value="bearish">bearish</option>
                  <option value="volatile">volatile</option>
                </select>
              </div>
            )}
            <div className="flex items-center justify-between mt-4">
              <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                {mode === "pairs" ? "equity only" : `options · ${view}`} · up to 2 attempts · {sending ? "running…" : "⌘+Enter to dispatch"}
              </span>
              <button
                className="btn btn-primary"
                onClick={dispatch}
                disabled={sending || !objective.trim()}
                style={{ padding: "10px 24px", fontSize: 14 }}
              >
                {sending ? "Dispatching…" : "Dispatch ✦"}
              </button>
            </div>
          </>
        )}
      </div>
    </>
  );
}

// ── List item ────────────────────────────────────────────────────────────

function ListItem({
  e,
  selected,
  onClick,
}: {
  e: JournalEntry;
  selected: boolean;
  onClick: () => void;
}) {
  const ok = e.status === "completed";
  return (
    <button
      onClick={onClick}
      className={`journal-item ${selected ? "selected" : ""}`}
    >
      <div className="flex items-start gap-2.5">
        <span
          className="shrink-0 mt-0.5"
          style={{
            width: 8,
            height: 8,
            borderRadius: "50%",
            background: ok ? "var(--green)" : "var(--yellow)",
            flexShrink: 0,
          }}
        />
        <div className="min-w-0 flex-1 text-left">
          <div className="journal-item-objective">{e.objective}</div>
          <div className="journal-item-date">{fmtTime(e.ts)}</div>
        </div>
      </div>
    </button>
  );
}

// ── Detail view ──────────────────────────────────────────────────────────

function DetailView({ e, onClose }: { e: JournalEntry; onClose: () => void }) {
  const ok = e.status === "completed";
  const others = (e.attempt_run_ids ?? []).filter((id) => id && id !== e.run_id);
  const allRunIds = [e.run_id, ...others].filter(Boolean) as string[];

  return (
    <div className="journal-detail">
      {/* header */}
      <div className="journal-detail-header">
        <button onClick={onClose} className="journal-back-btn" aria-label="Back to list">
          ← Back
        </button>
        <div className="flex items-center gap-2 flex-wrap ml-auto">
          <span className={ok ? "badge badge-green" : "badge badge-yellow"}>{e.status || "—"}</span>
          {e.score != null && <span className="badge badge-gray">strength {e.score.toFixed(4)}</span>}
          {e.attempts != null && (
            <span className="text-xs" style={{ color: "var(--text-muted)" }}>
              {e.attempts} attempt{e.attempts === 1 ? "" : "s"}
            </span>
          )}
          {e.tokens != null && (
            <span className="text-xs" style={{ color: "var(--text-muted)" }}>
              {e.tokens.toLocaleString()} tokens
            </span>
          )}
          <span className="text-xs" style={{ color: "var(--text-muted)" }}>
            {fmtFull(e.ts)}
          </span>
        </div>
      </div>

      {/* objective */}
      <div className="journal-detail-objective">{e.objective}</div>

      {/* findings */}
      <div className="mt-3">
        <div className="text-xs font-semibold mb-1.5" style={{ color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.04em" }}>
          Findings
        </div>
        <div className="text-sm" style={{ color: "var(--text-secondary)" }}>
          <Markdown text={e.summary} />
        </div>
      </div>

      {/* approach & sources */}
      {allRunIds.length > 0 && (
        <>
          <div className="journal-section-divider" />
          <div>
            <div className="text-xs font-semibold mb-2" style={{ color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.04em" }}>
              Approach & Sources
            </div>
            {allRunIds.map((runId, idx) => (
              <TrailSection
                key={runId}
                runId={runId}
                label={idx === 0 ? "kept run" : `attempt ${idx}`}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function TrailSection({ runId, label }: { runId: string; label: string }) {
  const [steps, setSteps] = useState<TrailStep[] | null>(null);
  const [loading, setLoading] = useState(false);
  const loaded = useRef(false);

  useEffect(() => {
    if (loaded.current) return;
    loaded.current = true;
    setLoading(true);
    getTrail(runId)
      .then((r) => setSteps(r.trail))
      .catch(() => setSteps([]))
      .finally(() => setLoading(false));
  }, [runId]);

  return (
    <div className="mb-3">
      <div className="text-xs mb-1" style={{ color: "var(--text-muted)" }}>
        <span className="font-mono" style={{ color: "var(--border)" }}>{runId}</span>
        <span className="ml-1.5" style={{ color: "var(--text-muted)" }}>({label})</span>
      </div>
      {loading && (
        <div className="text-xs" style={{ color: "var(--text-muted)" }}>Loading trail…</div>
      )}
      {steps && steps.length === 0 && (
        <div className="text-xs" style={{ color: "var(--text-muted)" }}>No trail recorded.</div>
      )}
      {steps && steps.length > 0 && (
        <>
          <Digest steps={steps} />
          <div className="mt-2">
            <Trail steps={steps} />
          </div>
        </>
      )}
    </div>
  );
}

// ── Empty state ──────────────────────────────────────────────────────────

function EmptyDetail() {
  return (
    <div className="journal-detail flex items-center justify-center">
      <div className="text-center" style={{ color: "var(--text-muted)" }}>
        <div className="text-3xl mb-3">❖</div>
        <div className="text-sm">Select a hunt from the list</div>
        <div className="text-xs mt-1">to see its findings and research trail</div>
      </div>
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────

export default function JournalPage() {
  const [entries, setEntries] = useState<JournalEntry[] | null>(null);
  const [err, setErr] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [modalKey, setModalKey] = useState(0);

  const openModal = () => { setModalOpen(true); setModalKey(k => k + 1); };

  const loadJournal = () => {
    getJournal(50)
      .then((r) => setEntries(r.entries))
      .catch(() => setErr(true));
  };

  useEffect(() => { loadJournal(); }, []);

  const selectedEntry = selected != null && entries ? entries[selected] : null;

  return (
    <div className="journal-layout">
      {/* ── Left: list ──────────────────────────────────────────── */}
      <aside className="journal-list">
        <div className="journal-list-header">
          <h1 className="text-lg font-semibold tracking-tight">Journal</h1>
          <div className="flex items-center gap-2">
            {entries && (
              <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                {entries.length}
              </span>
            )}
            <button
              className="btn btn-primary"
              onClick={() => openModal()}
              style={{ padding: "5px 12px", fontSize: 12, display: "flex", alignItems: "center", gap: 5 }}
            >
              <span>✦</span> New Hunt
            </button>
          </div>
        </div>

        {err && (
          <div className="p-3 m-2 text-xs" style={{ color: "var(--red)" }}>
            Couldn&apos;t load journal.
          </div>
        )}
        {entries && entries.length === 0 && (
          <div className="p-4 text-xs text-center" style={{ color: "var(--text-muted)" }}>
            No hunts yet. Dispatch your first one.
          </div>
        )}
        {entries && entries.length > 0 && (
          <div className="journal-list-scroll">
            {entries.map((e, i) => (
              <ListItem
                key={e.run_id ?? i}
                e={e}
                selected={selected === i}
                onClick={() => setSelected(i)}
              />
            ))}
          </div>
        )}
      </aside>

      {/* ── Right: detail ───────────────────────────────────────── */}
      <main className="journal-main">
        {selectedEntry ? (
          <DetailView
            key={selected}
            e={selectedEntry}
            onClose={() => setSelected(null)}
          />
        ) : (
          <EmptyDetail />
        )}
      </main>

      {/* ── Dispatch modal ───────────────────────────────────────── */}
      <DispatchModal key={modalKey} open={modalOpen} onClose={() => setModalOpen(false)} onDone={loadJournal} />
    </div>
  );
}
