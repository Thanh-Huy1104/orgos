"use client";

import { useState } from "react";
import { getCryptoScan, CryptoReport } from "@/lib/api";

export default function Crypto() {
  const [report, setReport] = useState<CryptoReport | null>(null);
  const [loading, setLoading] = useState(false);

  const run = async () => {
    if (loading) return;
    setLoading(true);
    try { setReport(await getCryptoScan()); }
    catch { setReport(null); }
    finally { setLoading(false); }
  };

  return (
    <div className="max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-2">
        <h1 className="text-2xl font-semibold tracking-tight">Crypto</h1>
        <button className="btn btn-primary" onClick={run} disabled={loading}>
          {loading ? "Scanning…" : "Scan ▸"}
        </button>
      </div>
      <p className="text-sm mb-5" style={{ color: "var(--text-muted)" }}>
        Recent-window durability + Benjamini-Hochberg FDR + BTC-factor independence + hub exclusion.
        Crypto cointegration is regime-bound — the <b>OOS</b> flag says whether a pair also holds out-of-sample.
      </p>

      {loading && <div className="text-sm" style={{ color: "var(--text-muted)" }}>
        Fetching OHLCV from the exchange and FDR-scanning every pair…
      </div>}

      {report && !loading && (report.error
        ? <div className="card" style={{ borderColor: "var(--red)" }}><span style={{ color: "var(--red)" }}>{report.error}</span></div>
        : (
          <div className="card">
            <div className="text-sm mb-3" style={{ color: "var(--text-secondary)" }}>
              {report.coins_scanned.length} coins · {report.pairs_tested} pairs · factor {report.factor} ·
              FDR {report.fdr} (cutoff {report.fdr_cutoff}) ·{" "}
              <b style={{ color: "var(--text-primary)" }}>{report.candidates_found}</b> durable
              {report.hubs_excluded.length > 0 &&
                <span style={{ color: "var(--text-muted)" }}> · hubs excluded: {report.hubs_excluded.join(", ")}</span>}
            </div>
            {report.candidates.length === 0
              ? <div className="text-sm" style={{ color: "var(--text-muted)" }}>No durable, regime-current pairs right now.</div>
              : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs" style={{ color: "var(--text-muted)" }}>
                      <th className="py-1.5">Pair</th><th>p_full</th><th>p_recent</th>
                      <th>OOS</th><th>half-life</th><th>hurst</th><th>btc_r²</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.candidates.map((c) => (
                      <tr key={c.pair} className="border-t" style={{ borderColor: "var(--border)" }}>
                        <td className="py-2 font-medium">{c.pair}</td>
                        <td className="font-mono">{c.adf_p}</td>
                        <td className="font-mono">{c.p_recent}</td>
                        <td>
                          <span className={c.oos_confirmed ? "badge badge-green" : "badge badge-gray"}>
                            {c.oos_confirmed ? "holds" : "regime-only"}
                          </span>
                        </td>
                        <td>{c.half_life}d</td>
                        <td>{c.hurst}</td>
                        <td>{c.factor_r2 ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
          </div>
        ))}
      {!report && !loading && (
        <div className="text-sm" style={{ color: "var(--text-muted)" }}>
          Scan the crypto universe for durable cointegrated pairs.
        </div>
      )}
    </div>
  );
}
