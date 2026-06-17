"use client";

import { useState } from "react";
import { getEvents, EventReport, Dossier, MarketEvent } from "@/lib/api";

const VERDICT_COLOR: Record<string, string> = {
  PROMOTE: "var(--green)", REVIEW: "var(--yellow)", HOLD: "var(--red)",
};
const RISK_BADGE: Record<string, string> = {
  LOW: "badge badge-green", MEDIUM: "badge badge-yellow", HIGH: "badge badge-red",
};

function EventRow({ e }: { e: MarketEvent }) {
  return (
    <div className="flex items-center gap-3 py-2 border-b last:border-0" style={{ borderColor: "var(--border)" }}>
      <span className="font-medium w-16">{e.ticker}</span>
      <span className="text-xs w-24" style={{ color: "var(--text-muted)" }}>{e.sector}</span>
      <span className={RISK_BADGE[e.risk]}>{e.risk}</span>
      <span className="text-sm font-mono" style={{ color: "var(--text-secondary)" }}>{e.forms.join(", ")}</span>
    </div>
  );
}

function DossierRow({ d }: { d: Dossier }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-b last:border-0" style={{ borderColor: "var(--border)" }}>
      <button onClick={() => setOpen(!open)} className="w-full flex items-center gap-3 py-2 text-left">
        <span style={{ color: VERDICT_COLOR[d.verdict] }}>●</span>
        <span className="font-medium w-24">{d.pair}</span>
        <span className={RISK_BADGE[d.structural_risk]}>{d.structural_risk}</span>
        <span className="text-sm flex-1 truncate" style={{ color: "var(--text-secondary)" }}>{d.reasons[0]}</span>
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <div className="pb-3 pl-7 text-xs space-y-1" style={{ color: "var(--text-secondary)" }}>
          <div className="flex gap-4 flex-wrap font-mono">
            <span>adf_p {String(d.stats.adf_p)}</span>
            <span>half-life {String(d.stats.half_life)}d</span>
            <span>hurst {String(d.stats.hurst)}</span>
          </div>
          {Object.entries(d.leg_filings).map(([leg, f]) => (
            <div key={leg}><b>{leg}</b>: {f.n_filings} filings, {f.risk}
              {f.high_forms.length ? ` (${f.high_forms.join(", ")})` : ""}
              {f.medium_forms.length ? ` · ${f.medium_forms.join(", ")}` : ""}</div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function Signals() {
  const [report, setReport] = useState<EventReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [days, setDays] = useState(7);

  const run = async () => {
    if (loading) return;
    setLoading(true);
    try { setReport(await getEvents(days)); }
    catch { setReport(null); }
    finally { setLoading(false); }
  };

  return (
    <div className="max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-2">
        <h1 className="text-2xl font-semibold tracking-tight">Signals</h1>
        <div className="flex items-center gap-2">
          <select className="input" value={days} onChange={(e) => setDays(Number(e.target.value))}>
            <option value={7}>last 7 days</option>
            <option value={14}>last 14 days</option>
            <option value={30}>last 30 days</option>
          </select>
          <button className="btn btn-primary" onClick={run} disabled={loading}>
            {loading ? "Scanning…" : "Detect ▸"}
          </button>
        </div>
      </div>
      <p className="text-sm mb-5" style={{ color: "var(--text-muted)" }}>
        Material SEC filings on tracked tickers point at a sector → we scan that field and research-gate the pairs.
      </p>

      {loading && <div className="text-sm" style={{ color: "var(--text-muted)" }}>
        Checking SEC filings across tracked tickers, then scanning the implicated sectors…
      </div>}

      {report && !loading && (
        <>
          <div className="text-sm mb-4" style={{ color: "var(--text-secondary)" }}>{report.summary}</div>

          <div className="card mb-4">
            <div className="text-sm font-semibold mb-2">Triggering Events</div>
            {report.events.length === 0
              ? <div className="text-sm" style={{ color: "var(--text-muted)" }}>No material filings in this window.</div>
              : report.events.map((e) => <EventRow key={e.ticker} e={e} />)}
          </div>

          {report.results.map((r) => (
            <div key={r.sector} className="card mb-4">
              <div className="text-sm font-semibold mb-2">
                {r.sector} <span style={{ color: "var(--text-muted)" }}>· {r.candidates_found} candidate(s)</span>
              </div>
              {r.promote.length === 0 && r.review.length === 0 && r.hold.length === 0
                ? <div className="text-sm" style={{ color: "var(--text-muted)" }}>No durable pairs to act on.</div>
                : <>
                    {r.promote.map((d) => <DossierRow key={d.pair} d={d} />)}
                    {r.review.map((d) => <DossierRow key={d.pair} d={d} />)}
                    {r.hold.map((d) => <DossierRow key={d.pair} d={d} />)}
                  </>}
            </div>
          ))}
        </>
      )}
      {!report && !loading && (
        <div className="text-sm" style={{ color: "var(--text-muted)" }}>
          Hit Detect to find recent material filings and the pairs they implicate.
        </div>
      )}
    </div>
  );
}
