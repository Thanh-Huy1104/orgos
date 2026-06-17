"use client";

import { useEffect, useState } from "react";
import {
  getBook, getUniverses, getRecommend,
  QuantBook, RecommendReport, Dossier, ActivePair,
} from "@/lib/api";

const money = (n: number) => "$" + n.toLocaleString(undefined, { maximumFractionDigits: 0 });

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="card flex-1">
      <div className="text-xs" style={{ color: "var(--text-muted)" }}>{label}</div>
      <div className="text-2xl font-semibold mt-1" style={color ? { color } : {}}>{value}</div>
    </div>
  );
}

// Live spread z-score: a bar scaled to |z|/3, coral once |z| >= 2 (stretched).
function ZBar({ z }: { z: number | null }) {
  if (z === null) {
    return <span className="text-xs" style={{ color: "var(--text-muted)" }}>idle · no live signal</span>;
  }
  const mag = Math.min(Math.abs(z) / 3, 1);
  const stretched = Math.abs(z) >= 2;
  const color = stretched ? "var(--accent)" : "var(--text-secondary)";
  return (
    <div className="flex items-center gap-3 w-full">
      <span className="font-mono text-sm w-16" style={{ color }}>z {z > 0 ? "+" : ""}{z.toFixed(2)}</span>
      <div className="flex-1 h-2 rounded-full" style={{ background: "var(--bg-secondary)" }}>
        <div className="h-2 rounded-full" style={{ width: `${mag * 100}%`, background: color }} />
      </div>
      <span className="text-xs w-20" style={{ color: stretched ? "var(--accent)" : "var(--text-muted)" }}>
        {stretched ? "stretched" : "in band"}
      </span>
    </div>
  );
}

const VERDICT_COLOR: Record<string, string> = {
  PROMOTE: "var(--green)", REVIEW: "var(--yellow)", HOLD: "var(--red)",
};
const RISK_BADGE: Record<string, string> = {
  LOW: "badge badge-green", MEDIUM: "badge badge-yellow", HIGH: "badge badge-red",
};

function DossierRow({ d }: { d: Dossier }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-b last:border-0" style={{ borderColor: "var(--border)" }}>
      <button onClick={() => setOpen(!open)} className="w-full flex items-center gap-3 py-2.5 text-left">
        <span style={{ color: VERDICT_COLOR[d.verdict] }}>●</span>
        <span className="font-medium w-28">{d.pair}</span>
        <span className={RISK_BADGE[d.structural_risk]}>{d.structural_risk}</span>
        <span className="text-sm flex-1 truncate" style={{ color: "var(--text-secondary)" }}>
          {d.reasons[0]}
        </span>
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <div className="pb-3 pl-7 text-sm space-y-2" style={{ color: "var(--text-secondary)" }}>
          <div className="flex gap-4 flex-wrap text-xs font-mono">
            <span>adf_p {String(d.stats.adf_p)}</span>
            <span>half-life {String(d.stats.half_life)}d</span>
            <span>hurst {String(d.stats.hurst)}</span>
            <span>rate_r² {String(d.stats.factor_r2)}</span>
            <span>β {String(d.stats.beta)}</span>
          </div>
          <ul className="list-disc pl-4">{d.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
          <div className="flex gap-4 flex-wrap text-xs">
            {Object.entries(d.leg_filings).map(([leg, f]) => (
              <span key={leg}>
                <b>{leg}</b>: {f.n_filings} filings, {f.risk}
                {f.high_forms.length ? ` (${f.high_forms.join(", ")})` : ""}
                {f.medium_forms.length ? ` · ${f.medium_forms.join(", ")}` : ""}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Group({ title, dot, items, empty }: { title: string; dot: string; items: Dossier[]; empty: string }) {
  return (
    <div>
      <div className="flex items-center gap-2 text-xs font-semibold mb-1 mt-3" style={{ color: "var(--text-secondary)" }}>
        <span style={{ color: dot }}>●</span>{title} <span style={{ color: "var(--text-muted)" }}>({items.length})</span>
      </div>
      {items.length === 0
        ? <div className="text-sm pl-4 py-1" style={{ color: "var(--text-muted)" }}>{empty}</div>
        : items.map((d) => <DossierRow key={d.pair} d={d} />)}
    </div>
  );
}

export default function Desk() {
  const [book, setBook] = useState<QuantBook | null>(null);
  const [bookErr, setBookErr] = useState(false);
  const [universes, setUniverses] = useState<string[]>([]);
  const [selected, setSelected] = useState<string[]>(["utilities"]);
  const [rec, setRec] = useState<RecommendReport | null>(null);
  const [scanning, setScanning] = useState(false);

  useEffect(() => {
    getBook().then(setBook).catch(() => setBookErr(true));
    getUniverses().then((u) => setUniverses(Object.keys(u.universes))).catch(() => {});
  }, []);

  const toggle = (u: string) =>
    setSelected((s) => (s.includes(u) ? s.filter((x) => x !== u) : [...s, u]));

  const run = async () => {
    if (!selected.length || scanning) return;
    setScanning(true);
    try { setRec(await getRecommend(selected)); }
    catch { setRec(null); }
    finally { setScanning(false); }
  };

  const acct = book?.account;
  const perf = book?.performance;

  return (
    <div className="max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-5">
        <h1 className="text-2xl font-semibold tracking-tight">The Desk</h1>
        {acct && (
          <div className="flex items-center gap-2 text-sm" style={{ color: "var(--text-secondary)" }}>
            <span className="font-semibold" style={{ color: "var(--text-primary)" }}>{money(acct.total_equity)}</span>
            <span style={{ color: "var(--green)" }}>●</span> live
          </div>
        )}
      </div>

      {bookErr && (
        <div className="card mb-4" style={{ borderColor: "var(--red)" }}>
          <span style={{ color: "var(--red)" }}>Engine offline</span>
          <span className="text-sm ml-2" style={{ color: "var(--text-secondary)" }}>
            can&apos;t reach the Icarus trading DB — showing research only.
          </span>
        </div>
      )}

      {perf && (
        <div className="flex gap-3 mb-4">
          <Stat label="Win rate" value={perf.win_rate !== null ? `${(perf.win_rate * 100).toFixed(1)}%` : "—"} />
          <Stat label="Realized P&L" value={money(perf.total_realized_pnl)}
                color={perf.total_realized_pnl >= 0 ? "var(--green)" : "var(--red)"} />
          <Stat label="Closed trades" value={String(perf.closed_trades)} />
          <Stat label="Open positions" value={String(acct?.open_positions ?? 0)} />
        </div>
      )}

      <div className="card mb-4">
        <div className="text-sm font-semibold mb-3">Live Book</div>
        {book?.active_pairs?.length
          ? book.active_pairs.map((p: ActivePair) => (
              <div key={p.pair} className="flex items-center gap-4 py-2 border-b last:border-0" style={{ borderColor: "var(--border)" }}>
                <span className="font-medium w-24">{p.pair}</span>
                <div className="flex-1"><ZBar z={p.z_score} /></div>
              </div>
            ))
          : <div className="text-sm" style={{ color: "var(--text-muted)" }}>No active pairs.</div>}
      </div>

      <div className="card">
        <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
          <div className="text-sm font-semibold">Recommendations</div>
          <div className="flex items-center gap-2 flex-wrap">
            {universes.map((u) => (
              <button key={u} onClick={() => toggle(u)}
                className={selected.includes(u) ? "badge badge-blue" : "badge badge-gray"}
                style={{ cursor: "pointer" }}>{u}</button>
            ))}
            <button className="btn btn-primary" onClick={run} disabled={scanning || !selected.length}>
              {scanning ? "Scanning…" : "Run ▸"}
            </button>
          </div>
        </div>

        {scanning && <div className="text-sm" style={{ color: "var(--text-muted)" }}>Scanning {selected.join(", ")} — pulling bars, running cointegration, checking SEC filings…</div>}

        {rec && !scanning && (
          <>
            <div className="text-sm mb-1" style={{ color: "var(--text-secondary)" }}>{rec.summary}</div>
            <Group title="PROPOSE" dot="var(--green)" items={rec.propose_spawn} empty="nothing clean enough to propose" />
            <Group title="REVIEW" dot="var(--yellow)" items={rec.review} empty="none flagged for review" />
            <Group title="HOLD" dot="var(--red)" items={rec.hold} empty="none on hold" />
            {rec.promote_already_held.length > 0 && (
              <Group title="ALREADY HELD" dot="var(--text-muted)" items={rec.promote_already_held} empty="" />
            )}
          </>
        )}
        {!rec && !scanning && (
          <div className="text-sm" style={{ color: "var(--text-muted)" }}>
            Pick sector(s) and run a scan to get research-gated recommendations.
          </div>
        )}
      </div>
    </div>
  );
}
