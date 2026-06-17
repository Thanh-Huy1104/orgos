"use client";

import { useEffect, useState } from "react";
import { getUniverses, runScan, ScanResult } from "@/lib/api";

export default function Scanner() {
  const [universes, setUniverses] = useState<Record<string, string[]>>({});
  const [universe, setUniverse] = useState("utilities");
  const [custom, setCustom] = useState("");
  const [res, setRes] = useState<ScanResult | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    getUniverses().then((u) => setUniverses(u.universes)).catch(() => {});
  }, []);

  const run = async () => {
    if (loading) return;
    setLoading(true);
    try { setRes(await runScan(custom.trim() || universe)); }
    catch { setRes(null); }
    finally { setLoading(false); }
  };

  return (
    <div className="max-w-4xl mx-auto">
      <h1 className="text-2xl font-semibold tracking-tight mb-5">Scanner</h1>

      <div className="card mb-4">
        <div className="text-sm font-semibold mb-3">Universe</div>
        <div className="flex items-center gap-2 flex-wrap mb-3">
          {Object.keys(universes).map((u) => (
            <button key={u} onClick={() => { setUniverse(u); setCustom(""); }}
              className={!custom && universe === u ? "badge badge-blue" : "badge badge-gray"}
              style={{ cursor: "pointer" }}>{u}</button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <input className="input flex-1" placeholder="…or custom tickers, e.g. DUK SO DTE AEP"
            value={custom} onChange={(e) => setCustom(e.target.value)} />
          <button className="btn btn-primary" onClick={run} disabled={loading}>
            {loading ? "Scanning…" : "Scan ▸"}
          </button>
        </div>
        {!custom && universes[universe] && (
          <div className="text-xs mt-2" style={{ color: "var(--text-muted)" }}>
            {universes[universe].length} tickers: {universes[universe].join(", ")}
          </div>
        )}
      </div>

      {loading && <div className="text-sm" style={{ color: "var(--text-muted)" }}>Pulling cached bars and running cointegration on every pair…</div>}

      {res && !loading && (res.error
        ? <div className="card" style={{ borderColor: "var(--red)" }}><span style={{ color: "var(--red)" }}>{res.error}</span></div>
        : (
          <div className="card">
            <div className="text-sm mb-3" style={{ color: "var(--text-secondary)" }}>
              Scanned {res.tickers_scanned.length} tickers · factor {res.factor} ·{" "}
              <b style={{ color: "var(--text-primary)" }}>{res.candidates_found}</b> durable candidate(s)
            </div>
            {res.candidates.length === 0
              ? <div className="text-sm" style={{ color: "var(--text-muted)" }}>No pair cleared the durability funnel (stable + hurst&lt;0.5 + half-life&lt;30 + factor-independent).</div>
              : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs" style={{ color: "var(--text-muted)" }}>
                      <th className="py-1.5">Pair</th><th>adf_p</th><th>half-life</th>
                      <th>hurst</th><th>β</th><th>drift</th><th>rate_r²</th><th>sub-period p</th>
                    </tr>
                  </thead>
                  <tbody>
                    {res.candidates.map((c) => (
                      <tr key={c.pair} className="border-t" style={{ borderColor: "var(--border)" }}>
                        <td className="py-2 font-medium">{c.pair}</td>
                        <td className="font-mono">{c.adf_p}</td>
                        <td>{c.half_life}d</td>
                        <td>{c.hurst}</td>
                        <td>{c.beta}</td>
                        <td>{c.beta_drift}</td>
                        <td>{c.factor_r2 ?? "—"}</td>
                        <td className="font-mono text-xs">[{c.sub_pvalues.map((p) => p ?? "na").join(", ")}]</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
          </div>
        ))}
    </div>
  );
}
