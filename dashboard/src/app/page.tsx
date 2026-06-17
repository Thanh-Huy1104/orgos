"use client";

import { useEffect, useState } from "react";
import {
  getBook, getRisk, postHalt,
  QuantBook, ActivePair, RiskReport,
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

export default function Desk() {
  const [book, setBook] = useState<QuantBook | null>(null);
  const [bookErr, setBookErr] = useState(false);
  const [risk, setRisk] = useState<RiskReport | null>(null);
  const [halting, setHalting] = useState<number | null>(null);

  const loadRisk = () => getRisk().then(setRisk).catch(() => {});
  useEffect(() => {
    getBook().then(setBook).catch(() => setBookErr(true));
    loadRisk();
  }, []);

  const doHalt = async (pairId: number, pair: string) => {
    if (!confirm(`HALT ${pair}? This sets Icarus's kill switch — the engine stops `
      + `trading this pair. orgos cannot un-halt; you re-enable it in Icarus.`)) return;
    setHalting(pairId);
    try { await postHalt(pairId, `manual halt from desk (${pair})`); await loadRisk(); }
    catch { /* surfaced by risk reload */ }
    finally { setHalting(null); }
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
            can&apos;t reach the Icarus trading DB.
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

      <div className="card">
        <div className="flex items-center justify-between mb-3">
          <div className="text-sm font-semibold">Live Book</div>
          {risk && <div className="text-xs" style={{ color: "var(--text-muted)" }}>{risk.summary}</div>}
        </div>
        {book?.active_pairs?.length
          ? book.active_pairs.map((p: ActivePair) => {
              const r = risk?.active_pairs.find((a) => a.pair === p.pair);
              const halted = r?.already_halted;
              return (
                <div key={p.pair} className="flex items-center gap-3 py-2 border-b last:border-0" style={{ borderColor: "var(--border)" }}>
                  <span className="font-medium w-24">{p.pair}</span>
                  <div className="flex-1"><ZBar z={p.z_score} /></div>
                  {r && r.structural_risk !== "LOW" && (
                    <span className={r.structural_risk === "HIGH" ? "badge badge-red" : "badge badge-yellow"}>
                      {r.structural_risk}
                    </span>
                  )}
                  {halted
                    ? <span className="badge badge-gray">halted</span>
                    : r && <button className="btn btn-secondary" style={{ padding: "2px 10px", fontSize: 12 }}
                        onClick={() => doHalt(r.pair_id, p.pair)} disabled={halting === r.pair_id}>
                        {halting === r.pair_id ? "…" : (r.recommend_halt ? "⚠ Halt" : "Halt")}
                      </button>}
                </div>
              );
            })
          : <div className="text-sm" style={{ color: "var(--text-muted)" }}>No active pairs.</div>}
      </div>
    </div>
  );
}
