"use client";

import { useEffect, useState } from "react";
import {
  getBook, getRisk, postHalt,
  QuantBook, ActivePair, RiskReport,
} from "@/lib/api";

const money = (n: number) => "$" + n.toLocaleString(undefined, { maximumFractionDigits: 0 });
const fmtTok = (n: number) => n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : n >= 1000 ? `${(n / 1000).toFixed(0)}k` : String(n);

// DeepSeek V4 Pro pricing (per 1M tokens):
//   Cache hit input: $0.0036 | Cache miss input: $0.435 | Output: $0.87
// In ReAct loops ~90% of tokens are cache-hit re-feeds → effective blended ~$0.07/M
const BLENDED_RATE = 0.07;

// ── Token cost model (deepseek v4-pro estimates) ─────────────────────────

interface TokenCost {
  total_tokens_30d: number;
  budget_tokens: number;
  est_cost_30d: number;
  departments: { name: string; spend_30d: number; success_rate: number }[];
}

async function getTokenCost(): Promise<TokenCost | null> {
  try {
    const res = await fetch("/api/dashboard");
    if (!res.ok) return null;
    const d = await res.json();
    const total = d.total_spend_30d ?? 0;
    const budget = d.budget ?? 150_000;
    const estCost = (total * BLENDED_RATE) / 1_000_000;
    return {
      total_tokens_30d: total,
      budget_tokens: budget,
      est_cost_30d: estCost,
      departments: (d.departments || []).map((dp: Record<string, unknown>) => ({
        name: dp.name as string,
        spend_30d: dp.spend_30d as number,
        success_rate: dp.success_rate as number,
      })),
    };
  } catch { return null; }
}

// ── Components ───────────────────────────────────────────────────────────

function Stat({ label, value, color, sub }: { label: string; value: string; color?: string; sub?: string }) {
  return (
    <div className="card flex-1" style={{ minWidth: 140 }}>
      <div className="text-xs" style={{ color: "var(--text-muted)" }}>{label}</div>
      <div className="text-2xl font-semibold mt-1" style={color ? { color } : {}}>{value}</div>
      {sub && <div className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>{sub}</div>}
    </div>
  );
}

function BudgetBar({ used, budget }: { used: number; budget: number }) {
  const pct = Math.min((used / budget) * 100, 100);
  const color = pct > 80 ? "var(--red)" : pct > 50 ? "var(--accent)" : "var(--green)";
  return (
    <div>
      <div className="flex items-center justify-between text-xs mb-1">
        <span style={{ color: "var(--text-muted)" }}>Token budget</span>
        <span style={{ color: "var(--text-muted)" }}>
          {fmtTok(used)} / {fmtTok(budget)}
        </span>
      </div>
      <div className="w-full h-2 rounded-full" style={{ background: "var(--bg-secondary)" }}>
        <div
          className="h-2 rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
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

// ── Page ─────────────────────────────────────────────────────────────────

export default function Desk() {
  const [book, setBook] = useState<QuantBook | null>(null);
  const [bookErr, setBookErr] = useState(false);
  const [risk, setRisk] = useState<RiskReport | null>(null);
  const [halting, setHalting] = useState<number | null>(null);
  const [tokenCost, setTokenCost] = useState<TokenCost | null>(null);

  const loadRisk = () => getRisk().then(setRisk).catch(() => {});
  useEffect(() => {
    getBook().then(setBook).catch(() => setBookErr(true));
    loadRisk();
    getTokenCost().then(setTokenCost);
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
    <div className="desk-layout">
      <div className="desk-main">
        <div className="flex items-center justify-between mb-4">
          <h1 className="text-xl font-semibold tracking-tight">The Desk</h1>
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

        {/* Trading stats */}
        {perf && (
          <div className="flex gap-3 mb-4 flex-wrap">
            <Stat label="Win rate" value={perf.win_rate !== null ? `${(perf.win_rate * 100).toFixed(1)}%` : "—"} />
            <Stat label="Realized P&amp;L" value={money(perf.total_realized_pnl)}
                  color={perf.total_realized_pnl >= 0 ? "var(--green)" : "var(--red)"} />
            <Stat label="Closed trades" value={String(perf.closed_trades)} />
            <Stat label="Open positions" value={String(acct?.open_positions ?? 0)} />
          </div>
        )}

        {/* Live book */}
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

      {/* ── Right sidebar: token cost & stats ──────────────────────── */}
      <aside className="desk-sidebar">
        <h2 className="text-sm font-semibold mb-3" style={{ color: "var(--text-secondary)" }}>
          Usage &amp; Costs
        </h2>

        {tokenCost && (
          <>
            {/* Budget bar */}
            <div className="card" style={{ padding: "14px" }}>
              <BudgetBar used={tokenCost.total_tokens_30d} budget={tokenCost.budget_tokens} />
              <div className="flex items-center justify-between mt-3">
                <div className="text-xs" style={{ color: "var(--text-muted)" }}>Est. cost (30d)</div>
                <div className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                  ${tokenCost.est_cost_30d.toFixed(2)}
                </div>
              </div>
              <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                deepseek v4 pro · ~$0.07/M blended (90% cache-hit $0.004/M, 5% miss $0.44/M, 5% output $0.87/M)
              </div>
            </div>

            {/* Department breakdown */}
            <div className="mt-3">
              <div className="text-xs font-semibold mb-2" style={{ color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.04em" }}>
                Departments
              </div>
              <div className="flex flex-col gap-1.5">
                {tokenCost.departments.map(dp => {
                  const pct = tokenCost.total_tokens_30d > 0
                    ? (dp.spend_30d / tokenCost.total_tokens_30d) * 100
                    : 0;
                  return (
                    <div key={dp.name} className="card" style={{ padding: "10px 14px" }}>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-sm font-medium" style={{ color: "var(--text-primary)", textTransform: "capitalize" }}>
                          {dp.name}
                        </span>
                        <span className="text-xs" style={{ color: dp.success_rate >= 80 ? "var(--green)" : "var(--text-muted)" }}>
                          {dp.success_rate}%
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <div className="flex-1 h-1.5 rounded-full" style={{ background: "var(--bg-secondary)" }}>
                          <div
                            className="h-1.5 rounded-full"
                            style={{ width: `${pct}%`, background: "var(--accent)", minWidth: pct > 0 ? 4 : 0 }}
                          />
                        </div>
                        <span className="text-xs font-mono" style={{ color: "var(--text-muted)", width: 48, textAlign: "right" }}>
                          {fmtTok(dp.spend_30d)}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </>
        )}

        {/* Risk summary */}
        {risk && (
          <div className="mt-4">
            <div className="text-xs font-semibold mb-2" style={{ color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.04em" }}>
              Risk
            </div>
            <div className="card" style={{ padding: "10px 14px" }}>
              <div className="text-xs" style={{ color: "var(--text-secondary)", lineHeight: 1.5 }}>
                {risk.summary}
              </div>
              {risk.recommend_halt && risk.recommend_halt.length > 0 && (
                <div className="mt-2 pt-2 border-t" style={{ borderColor: "var(--border)" }}>
                  <div className="text-xs font-medium" style={{ color: "var(--red)" }}>
                    {risk.recommend_halt.length} pair{risk.recommend_halt.length === 1 ? "" : "s"} recommended for halt
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}
