"use client";

import { useEffect, useState } from "react";
import {
  PaperLeg, PaperOrder, LiquidityResult, PaperPosition,
  previewPaperOrder, placePaperOrder, getPaperPositions, closePaperPosition,
} from "@/lib/api";

// Paper options trading desk — human-in-the-loop, paper-only.
// You read the strategist's recommendation, build the exact order ticket here,
// preview the live liquidity, then place it on IBKR paper.

const BLANK_LEG: PaperLeg = { right: "P", action: "SELL", strike: 0, expiry: "", qty: 1 };

export default function PaperPage() {
  const [ticker, setTicker] = useState("");
  const [strategy, setStrategy] = useState("cash_secured_put");
  const [maxLoss, setMaxLoss] = useState(300);
  const [legs, setLegs] = useState<PaperLeg[]>([{ ...BLANK_LEG }]);

  const [preview, setPreview] = useState<LiquidityResult | null>(null);
  const [previewReason, setPreviewReason] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [positions, setPositions] = useState<PaperPosition[]>([]);

  const loadPositions = async () => {
    try { setPositions((await getPaperPositions()).positions); } catch { /* offline */ }
  };
  useEffect(() => { loadPositions(); }, []);

  const order = (): PaperOrder => ({
    ticker: ticker.toUpperCase(), strategy, legs, max_loss_usd: maxLoss,
  });

  const setLeg = (i: number, patch: Partial<PaperLeg>) =>
    setLegs(legs.map((l, j) => (j === i ? { ...l, ...patch } : l)));

  const tradeable = preview?.liquid && preview?.spot_sanity_ok;

  const doPreview = async () => {
    setBusy(true); setMsg(null); setPreview(null); setPreviewReason(null);
    try {
      const res = await previewPaperOrder(order());
      if (res.tradeable && res.liquidity) setPreview(res.liquidity);
      else setPreviewReason(res.reason || "not tradeable");
    } catch (e) { setMsg(`Preview failed: ${e}`); }
    finally { setBusy(false); }
  };

  const doPlace = async () => {
    if (!tradeable) return;
    setBusy(true); setMsg(null);
    try {
      const res = await placePaperOrder(order());
      setMsg(`✓ Placed — order ${res.order_id}, IB ids ${res.ib_order_ids.join(", ")}`);
      setPreview(null);
      await loadPositions();
    } catch (e) { setMsg(`Place rejected: ${e}`); }
    finally { setBusy(false); }
  };

  const doClose = async (id: string) => {
    const pnl = prompt("Realized P&L for this position ($)?");
    if (pnl === null) return;
    setBusy(true);
    try { await closePaperPosition(id, null, Number(pnl) || 0); await loadPositions(); }
    catch (e) { setMsg(`Close failed: ${e}`); }
    finally { setBusy(false); }
  };

  return (
    <div className="max-w-3xl mx-auto">
      <h1 className="text-2xl font-semibold tracking-tight mb-1">Paper Trade</h1>
      <p className="text-sm mb-5" style={{ color: "var(--text-muted)" }}>
        Build the order ticket from a strategist recommendation, preview the live
        liquidity, then place on IBKR paper. Every order re-checks liquidity + spot
        sanity and is hard-capped paper-only.
      </p>

      {/* Order ticket */}
      <div className="card mb-4">
        <div className="flex gap-2 mb-3">
          <input className="input" placeholder="Ticker (e.g. SPY)" value={ticker}
            onChange={(e) => setTicker(e.target.value)} style={{ width: 140 }} />
          <input className="input" placeholder="strategy" value={strategy}
            onChange={(e) => setStrategy(e.target.value)} style={{ flex: 1 }} />
          <input className="input" type="number" placeholder="max loss $" value={maxLoss}
            onChange={(e) => setMaxLoss(Number(e.target.value))} style={{ width: 120 }} />
        </div>

        <div className="text-xs mb-1" style={{ color: "var(--text-muted)" }}>Legs</div>
        {legs.map((leg, i) => (
          <div key={i} className="flex gap-2 mb-2 items-center">
            <select className="input" value={leg.right}
              onChange={(e) => setLeg(i, { right: e.target.value as "P" | "C" })}>
              <option value="P">Put</option><option value="C">Call</option>
            </select>
            <select className="input" value={leg.action}
              onChange={(e) => setLeg(i, { action: e.target.value as "BUY" | "SELL" })}>
              <option value="SELL">Sell</option><option value="BUY">Buy</option>
            </select>
            <input className="input" type="number" placeholder="strike" value={leg.strike || ""}
              onChange={(e) => setLeg(i, { strike: Number(e.target.value) })} style={{ width: 100 }} />
            <input className="input" type="date" value={leg.expiry}
              onChange={(e) => setLeg(i, { expiry: e.target.value })} style={{ width: 150 }} />
            <input className="input" type="number" value={leg.qty} min={1}
              onChange={(e) => setLeg(i, { qty: Number(e.target.value) })} style={{ width: 70 }} />
            {legs.length > 1 && (
              <button className="slide-panel-close"
                onClick={() => setLegs(legs.filter((_, j) => j !== i))}>✕</button>
            )}
          </div>
        ))}
        <button className="text-xs" style={{ color: "var(--accent)", background: "none", cursor: "pointer" }}
          onClick={() => setLegs([...legs, { ...BLANK_LEG }])}>+ add leg</button>

        <div className="flex items-center gap-3 mt-4">
          <button className="btn" onClick={doPreview} disabled={busy || !ticker}>Preview liquidity</button>
          <button className="btn btn-primary" onClick={doPlace} disabled={busy || !tradeable}>
            Place paper order
          </button>
          {!tradeable && preview && (
            <span className="text-xs" style={{ color: "var(--yellow)" }}>not tradeable — see below</span>
          )}
        </div>
      </div>

      {/* Preview result */}
      {previewReason && (
        <div className="card mb-4" style={{ borderColor: "var(--yellow)" }}>
          <b>Not tradeable:</b> {previewReason}
        </div>
      )}
      {preview && (
        <div className="card mb-4">
          <div className="flex justify-between mb-2">
            <span>Spot {preview.spot} (close {preview.reference_close})</span>
            <span style={{ color: tradeable ? "var(--green)" : "var(--yellow)" }}>
              {tradeable ? "✓ tradeable" : "✗ not tradeable"}
            </span>
          </div>
          {preview.reasons.length > 0 && (
            <div className="text-xs mb-2" style={{ color: "var(--yellow)" }}>{preview.reasons.join(" · ")}</div>
          )}
          <table className="text-xs w-full">
            <thead><tr style={{ color: "var(--text-muted)" }}>
              <td>Leg</td><td>Bid</td><td>Ask</td><td>Mid</td><td>Spread</td><td>OI</td><td>OK</td>
            </tr></thead>
            <tbody>
              {preview.legs.map((l, i) => (
                <tr key={i}>
                  <td>{l.type} {l.requested_strike}</td>
                  <td>{l.bid}</td><td>{l.ask}</td><td>{l.mid}</td>
                  <td>{l.spread_pct != null ? `${(l.spread_pct * 100).toFixed(0)}%` : "—"}</td>
                  <td>{l.open_interest}</td>
                  <td style={{ color: l.tradeable ? "var(--green)" : "var(--yellow)" }}>{l.tradeable ? "✓" : "✗"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {msg && <div className="card mb-4 text-sm">{msg}</div>}

      {/* Positions */}
      <h2 className="text-lg font-semibold mb-2">Positions</h2>
      {positions.length === 0 ? (
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>No paper positions yet.</p>
      ) : (
        <div className="card">
          <table className="text-sm w-full">
            <thead><tr style={{ color: "var(--text-muted)" }}>
              <td>Ticker</td><td>Strategy</td><td>Status</td><td>P&L</td><td>Opened</td><td></td>
            </tr></thead>
            <tbody>
              {positions.map((p) => (
                <tr key={p.id}>
                  <td>{p.ticker}</td><td>{p.strategy}</td>
                  <td style={{ color: p.status === "open" ? "var(--green)" : "var(--text-muted)" }}>{p.status}</td>
                  <td style={{ color: (p.realized_pnl ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>
                    {p.realized_pnl != null ? `$${p.realized_pnl.toFixed(2)}` : "—"}
                  </td>
                  <td>{new Date(p.opened_at).toLocaleString()}</td>
                  <td>{p.status === "open" && (
                    <button className="text-xs" style={{ color: "var(--accent)", background: "none", cursor: "pointer" }}
                      onClick={() => doClose(p.id)}>close</button>
                  )}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
