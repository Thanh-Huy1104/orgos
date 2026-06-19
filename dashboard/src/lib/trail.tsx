"use client";

import { useState } from "react";
import { TrailStep, getTrail } from "@/lib/api";

const PHASE: Record<string, string> = {
  "quant-researcher": "Research",
  "quant-scanner": "Scan",
  "quant-synth": "Synthesis",
};

// ── Resilient JSON extraction (handles truncated output_preview) ─────────

/** Pull key:value pairs from partial JSON via regex — works on truncated strings. */
function extractStr(raw: string, key: string): string {
  const m = raw.match(new RegExp(`"${key}":\\s*"((?:[^"\\\\]|\\\\.)*)"`, "s"));
  return m ? m[1].replace(/\\"/g, '"').replace(/\\n/g, "\n") : "";
}

function extractNum(raw: string, key: string): number | null {
  const m = raw.match(new RegExp(`"${key}":\\s*(-?[0-9.]+)`));
  return m ? Number(m[1]) : null;
}

function extractBool(raw: string, key: string): boolean | null {
  const m = raw.match(new RegExp(`"${key}":\\s*(true|false)`));
  return m ? m[1] === "true" : null;
}

function extractArr(raw: string, key: string): string[] {
  const start = raw.indexOf(`"${key}":`);
  if (start === -1) return [];
  // find the [ ... ] block
  let i = start + key.length + 3;
  while (i < raw.length && raw[i] !== "[") i++;
  if (i >= raw.length || raw[i] !== "[") return [];
  let depth = 0;
  const pieces: string[] = [];
  let buf = "";
  let inStr = false;
  for (i++; i < raw.length; i++) {
    const ch = raw[i];
    if (inStr) {
      if (ch === "\\") { buf += ch + raw[i + 1]; i++; continue; }
      if (ch === '"') { inStr = false; continue; }
      buf += ch;
      continue;
    }
    if (ch === '"') { inStr = true; continue; }
    if (ch === "," && depth === 0) {
      pieces.push(buf.trim());
      buf = "";
      continue;
    }
    if (ch === "[" || ch === "{") depth++;
    if (ch === "]" || ch === "}") {
      depth--;
      if (ch === "]" && depth < 0) {
        if (buf.trim()) pieces.push(buf.trim());
        break;
      }
    }
    buf += ch;
  }
  return pieces;
}

interface NewsArticle { title: string; url: string; snippet: string; }
function extractNews(raw: string): NewsArticle[] {
  // Split by article object boundaries
  const articles: NewsArticle[] = [];
  // Find the news array and extract each article object
  const blocks = extractObjBlocks(raw, "news");
  for (const block of blocks) {
    const title = extractStr(block, "title");
    const url = extractStr(block, "url");
    const snippet = extractStr(block, "snippet");
    if (title) articles.push({ title, url, snippet });
  }
  return articles;
}

function extractPapers(raw: string): { title: string; summary: string }[] {
  const blocks = extractObjBlocks(raw, "papers");
  return blocks.map((b) => ({
    title: extractStr(b, "title"),
    summary: extractStr(b, "summary"),
  })).filter((p) => p.title);
}

function extractCandidates(raw: string): Record<string, unknown>[] {
  const blocks = extractObjBlocks(raw, "candidates");
  return blocks.map((b) => {
    const obj: Record<string, unknown> = {};
    // common fields
    for (const k of ["pair","y","x","adf_p","beta","half_life","hurst","stable","factor_r2","sector","oos_sharpe","oos_return","n_trades","win_rate","max_dd","n_folds","folds_profitable"]) {
      const s = extractStr(b, k);
      if (s) { obj[k] = s; continue; }
      const n = extractNum(b, k);
      if (n !== null) { obj[k] = n; continue; }
      const bo = extractBool(b, k);
      if (bo !== null) { obj[k] = bo; continue; }
    }
    // sub_pvalues
    const subRaw = extractArr(b, "sub_pvalues");
    if (subRaw.length) {
      obj.sub_pvalues = subRaw.map((v) => {
        const n = parseFloat(v.replace(/"/g, ""));
        return isNaN(n) ? v : n;
      });
    }
    return Object.keys(obj).length > 0 ? obj : null;
  }).filter(Boolean) as Record<string, unknown>[];
}

/** Extract top-level array of objects from raw JSON string. */
function extractObjBlocks(raw: string, arrayKey: string): string[] {
  const start = raw.indexOf(`"${arrayKey}":`);
  if (start === -1) return [];
  let i = start + arrayKey.length + 3;
  while (i < raw.length && raw[i] !== "[") i++;
  if (i >= raw.length || raw[i] !== "[") return [];
  const blocks: string[] = [];
  let depth = 0, buf = "", inStr = false;
  for (i++; i < raw.length; i++) {
    const ch = raw[i];
    if (inStr) {
      buf += ch;
      if (ch === "\\") { buf += raw[++i]; continue; }
      if (ch === '"') inStr = false;
      continue;
    }
    if (ch === '"') { inStr = true; buf += ch; continue; }
    if (ch === "{" || ch === "[") depth++;
    if (ch === "}" || ch === "]") {
      depth--;
      if (ch === "}" && depth === 0) {
        // end of an object
        blocks.push(buf + "}");
        buf = "";
        continue;
      }
      if (ch === "]" && depth < 0) break; // end of array
    }
    if (depth > 0 || ch !== " " || buf.trim()) buf += ch;
  }
  // handle last truncated object
  if (buf.trim()) blocks.push(buf.trim());
  return blocks;
}

function tryParse(v: string): Record<string, unknown> | null {
  try { const o = JSON.parse(v); return typeof o === "object" && o ? (o as Record<string, unknown>) : null; }
  catch { return null; }
}

// ── Digest (summary) ─────────────────────────────────────────────────────

export interface TrailDigest {
  news: string[];
  arxiv: string[];
  sectors: string[];
  scans: { universe: string; found: number | null }[];
  bestSharpe: number | null;
  bestTrades: number | null;
  bestFolds: number | null;
}

export function digest(steps: TrailStep[]): TrailDigest {
  const inp = (s: TrailStep) => (s.tool_input ?? {}) as Record<string, unknown>;
  const str = (v: unknown) => (v == null ? "" : String(v));
  const found = (s: TrailStep) => {
    const m = /"candidates_found":\s*(\d+)/.exec(s.output_preview || "");
    return m ? Number(m[1]) : null;
  };
  const scanSteps = steps.filter((s) => s.tool === "scan_cointegrated_pairs" || s.tool === "scan_crypto_pairs");
  let bestSharpe: number | null = null, bestTrades: number | null = null, bestFolds: number | null = null;
  for (const s of scanSteps) {
    const prev = s.output_preview || "";
    const m = /"oos_sharpe":\s*(-?[0-9.]+)/.exec(prev);
    if (!m) continue;
    const sv = Number(m[1]);
    if (bestSharpe === null || sv > bestSharpe) {
      bestSharpe = sv;
      const t = /"n_trades":\s*(\d+)/.exec(prev);
      const f = /"folds_profitable":\s*(\d+)/.exec(prev);
      bestTrades = t ? Number(t[1]) : null;
      bestFolds = f ? Number(f[1]) : null;
    }
  }
  return {
    news: steps.filter((s) => s.tool === "news_catalysts").map((s) => str(inp(s).query)).filter(Boolean),
    arxiv: steps.filter((s) => s.tool === "search_arxiv").map((s) => str(inp(s).query)).filter(Boolean),
    sectors: steps.filter((s) => s.tool === "index_constituents").map((s) => str(inp(s).sector) || "all sectors").filter(Boolean),
    scans: scanSteps.map((s) => ({ universe: str(inp(s).universe), found: found(s) })),
    bestSharpe,
    bestTrades,
    bestFolds,
  };
}

function Line({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="text-xs" style={{ color: "var(--text-secondary)" }}>
      <span style={{ color: "var(--text-muted)" }}>{label} </span>
      {children}
    </div>
  );
}

export function Digest({ steps }: { steps: TrailStep[] }) {
  const d = digest(steps);
  if (!d.news.length && !d.arxiv.length && !d.sectors.length && !d.scans.length) return null;
  const survivors = d.scans.reduce((n, s) => n + (s.found ?? 0), 0);
  return (
    <div className="flex flex-col gap-1 mt-2 mb-1">
      {d.news.length > 0 && <Line label={`Researched news (${d.news.length}):`}>{d.news.join(" · ")}</Line>}
      {d.arxiv.length > 0 && <Line label={`Searched arXiv (${d.arxiv.length}):`}>{d.arxiv.join(" · ")}</Line>}
      {d.sectors.length > 0 && <Line label="Pulled constituents:">{d.sectors.join(", ")}</Line>}
      {d.scans.length > 0 && (
        <Line label={`Scanned ${d.scans.length} universe${d.scans.length === 1 ? "" : "s"}:`}>
          {d.scans.map((s, i) => (
            <span key={i}>
              {i > 0 && "; "}
              <span className="font-mono">{s.universe || "?"}</span>
              {s.found != null && <span style={{ color: s.found > 0 ? "var(--green)" : "var(--text-muted)" }}> ({s.found} durable)</span>}
            </span>
          ))}
        </Line>
      )}
      {d.scans.length > 0 && (
        <Line label="Outcome:">
          <span style={{ color: survivors > 0 ? "var(--green)" : "var(--text-muted)" }}>
            {survivors} durable pair{survivors === 1 ? "" : "s"} across all scans
          </span>
          {d.bestSharpe != null && (
            <span style={{ color: d.bestSharpe > 0.5 ? "var(--green)" : "var(--text-muted)" }}>
              {" · best OOS Sharpe "}{d.bestSharpe.toFixed(2)}
              {d.bestTrades != null && ` over ${d.bestTrades} trades`}
              {d.bestFolds != null && `, ${d.bestFolds} folds profitable`}
              {" (after costs)"}
              {d.bestTrades != null && d.bestTrades < 5 && (
                <span style={{ color: "var(--yellow)" }}> ⚠ small sample</span>
              )}
            </span>
          )}
        </Line>
      )}
    </div>
  );
}

// ── Rich tool-by-tool trail ───────────────────────────────────────────────

function StepHeader({ step }: { step: TrailStep }) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span className="badge badge-gray">{PHASE[step.role] ?? step.role}</span>
      <span className="font-mono text-xs font-medium" style={{ color: "var(--text-primary)" }}>
        {step.tool}
      </span>
      {!step.ok && <span className="badge badge-yellow">error</span>}
    </div>
  );
}

function domainFromUrl(url: string): string {
  try { return new URL(url).hostname.replace(/^www\./, ""); }
  catch { return ""; }
}

function faviconUrl(url: string): string {
  const domain = domainFromUrl(url);
  return domain ? `https://www.google.com/s2/favicons?domain=${domain}&sz=32` : "";
}

function SourcePill({ url, title, subtitle }: { url: string; title: string; subtitle?: string }) {
  const domain = domainFromUrl(url);
  const favicon = faviconUrl(url);
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="source-pill"
    >
      {favicon && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={favicon}
          alt=""
          className="source-pill-icon"
          onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
        />
      )}
      <div className="source-pill-text">
        <div className="source-pill-title">{title}</div>
        {subtitle && <div className="source-pill-sub">{subtitle}</div>}
      </div>
      <span className="source-pill-domain">{domain}</span>
    </a>
  );
}

function NewsStep({ step }: { step: TrailStep }) {
  const input = (step.tool_input ?? {}) as Record<string, unknown>;
  const query = String(input.query || "");
  const raw = step.output_preview || "";

  let articles: NewsArticle[] = [];
  const parsed = tryParse(raw);
  if (parsed && Array.isArray(parsed.news)) {
    articles = (parsed.news as unknown[]) as NewsArticle[];
  } else {
    articles = extractNews(raw);
  }

  return (
    <div className="trail-step">
      <div className="text-xs mb-1.5" style={{ color: "var(--text-muted)" }}>
        query: <span className="font-medium" style={{ color: "var(--text-primary)" }}>{query}</span>
        {articles.length > 0 && <span> · {articles.length} article{articles.length === 1 ? "" : "s"}</span>}
      </div>
      {articles.length > 0 && (
        <div className="flex flex-col gap-1.5">
          {articles.map((a, i) => (
            <SourcePill
              key={i}
              url={a.url}
              title={a.title}
              subtitle={a.snippet?.slice(0, 160)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ArxivPill({ title, summary }: { title: string; summary: string }) {
  const q = encodeURIComponent(title.split(".")[0]);
  return (
    <a
      href={`https://arxiv.org/search/?query=${q}&searchtype=all`}
      target="_blank"
      rel="noopener noreferrer"
      className="source-pill"
    >
      <span className="source-pill-icon-arxiv">arXiv</span>
      <div className="source-pill-text">
        <div className="source-pill-title">{title}</div>
        {summary && <div className="source-pill-sub">{summary.slice(0, 160)}{summary.length > 160 ? "…" : ""}</div>}
      </div>
    </a>
  );
}

function ArxivStep({ step }: { step: TrailStep }) {
  const input = (step.tool_input ?? {}) as Record<string, unknown>;
  const query = String(input.query || "");
  const raw = step.output_preview || "";

  let papers: { title: string; summary: string }[] = [];
  const parsed = tryParse(raw);
  if (parsed && Array.isArray(parsed.papers)) {
    papers = (parsed.papers as unknown[]) as { title: string; summary: string }[];
  } else {
    papers = extractPapers(raw);
  }

  return (
    <div className="trail-step">
      <div className="text-xs mb-1.5" style={{ color: "var(--text-muted)" }}>
        query: <span className="font-medium" style={{ color: "var(--text-primary)" }}>{query}</span>
        {papers.length > 0 && <span> · {papers.length} paper{papers.length === 1 ? "" : "s"}</span>}
      </div>
      {papers.length > 0 && (
        <div className="flex flex-col gap-1.5">
          {papers.map((p, i) => (
            <ArxivPill key={i} title={p.title} summary={p.summary} />
          ))}
        </div>
      )}
    </div>
  );
}

function ConstituentStep({ step }: { step: TrailStep }) {
  const input = (step.tool_input ?? {}) as Record<string, unknown>;
  const sector = String(input.sector || "all sectors");
  const raw = step.output_preview || "";

  let count: number | null = null;
  let tickers: string[] = [];
  const parsed = tryParse(raw);
  if (parsed) {
    count = parsed.count as number | null;
    tickers = Array.isArray(parsed.tickers) ? (parsed.tickers as string[]) : [];
  } else {
    count = extractNum(raw, "count");
    tickers = extractArr(raw, "tickers").map((t) => t.replace(/"/g, ""));
  }

  return (
    <div className="trail-step">
      <div className="text-xs" style={{ color: "var(--text-muted)" }}>
        sector: <span className="font-medium" style={{ color: "var(--text-primary)" }}>{sector}</span>
        {count != null && <span> · {count} constituents</span>}
      </div>
      {tickers.length > 0 && (
        <div className="text-xs mt-1 font-mono" style={{ color: "var(--text-secondary)", wordBreak: "break-all" }}>
          {tickers.join("  ")}
        </div>
      )}
    </div>
  );
}

function ScanStep({ step }: { step: TrailStep }) {
  const input = (step.tool_input ?? {}) as Record<string, unknown>;
  const universe = String(input.universe || "?");
  const lookback = input.lookback;
  const raw = step.output_preview || "";

  let found = 0;
  let candidates: Record<string, unknown>[] = [];
  const parsed = tryParse(raw);
  if (parsed) {
    found = (parsed.candidates_found as number) ?? 0;
    candidates = Array.isArray(parsed.candidates) ? (parsed.candidates as Record<string, unknown>[]) : [];
  } else {
    found = extractNum(raw, "candidates_found") ?? 0;
    candidates = extractCandidates(raw);
  }

  const cols = candidates.length > 0
    ? Object.keys(candidates[0]).filter(
        (k) => !["sector", "sub_pvalues", "beta_drift", "spread_vol", "oos_return", "max_dd"].includes(k)
      )
    : [];

  return (
    <div className="trail-step">
      <div className="text-xs mb-1.5" style={{ color: "var(--text-muted)" }}>
        universe: <span className="font-mono font-medium" style={{ color: "var(--text-primary)" }}>{universe}</span>
        {lookback != null && <span> · {String(lookback)}d</span>}
        <span style={{ color: found > 0 ? "var(--green)" : "var(--text-muted)" }}>
          {" · "}{found} durable pair{found === 1 ? "" : "s"}
        </span>
      </div>

      {candidates.length > 0 && (
        <div className="overflow-x-auto">
          <table className="trail-table">
            <thead>
              <tr>
                {cols.map((k) => (
                  <th key={k} className="trail-th">{k}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {candidates.map((c, i) => (
                <tr key={i}>
                  {cols.map((k) => (
                    <td key={k} className="trail-td">
                      <ScanCell value={c[k]} col={k} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ScanCell({ value, col }: { value: unknown; col: string }) {
  if (value == null) return <span style={{ color: "var(--text-muted)" }}>—</span>;

  if (col === "pair") {
    return <span className="font-mono font-semibold" style={{ color: "var(--text-primary)" }}>{String(value)}</span>;
  }
  if (col === "y" || col === "x") {
    return <span className="font-mono" style={{ color: "var(--text-secondary)" }}>{String(value)}</span>;
  }
  if (col === "stable") {
    const ok = value === true || value === "True" || value === 1 || String(value) === "true";
    return (
      <span style={{ color: ok ? "var(--green)" : "var(--text-muted)" }}>
        {ok ? "✓" : "✗"}
      </span>
    );
  }
  if (col === "adf_p") {
    const v = Number(value);
    if (isNaN(v)) return <span style={{ color: "var(--text-muted)" }}>{String(value)}</span>;
    return (
      <span className="font-mono" style={{ color: v < 0.01 ? "var(--green)" : v < 0.05 ? "var(--accent)" : "var(--text-muted)" }}>
        {v < 0.001 ? v.toExponential(2) : v.toFixed(4)}
      </span>
    );
  }
  if (col === "oos_sharpe") {
    const v = Number(value);
    if (isNaN(v)) return <span style={{ color: "var(--text-muted)" }}>{String(value)}</span>;
    return (
      <span className="font-mono" style={{ color: v > 1 ? "var(--green)" : v > 0 ? "var(--accent)" : "var(--text-muted)" }}>
        {v.toFixed(2)}
      </span>
    );
  }
  if (col === "win_rate") {
    const v = Number(value);
    if (isNaN(v)) return <span style={{ color: "var(--text-muted)" }}>{String(value)}</span>;
    return (
      <span style={{ color: v >= 0.6 ? "var(--green)" : "var(--text-muted)" }}>
        {(v * 100).toFixed(0)}%
      </span>
    );
  }
  if (typeof value === "number") {
    if (col === "n_trades" || col === "n_folds" || col === "folds_profitable") {
      return <span className="font-mono">{value}</span>;
    }
    if (Math.abs(value) < 1) {
      return <span className="font-mono">{value.toFixed(3)}</span>;
    }
    return <span className="font-mono">{value.toFixed(1)}</span>;
  }

  // arrays
  if (Array.isArray(value)) {
    return (
      <span className="font-mono" style={{ fontSize: 10, color: "var(--text-muted)" }}>
        {value.map((v: unknown) => (typeof v === "number" ? v.toFixed(3) : String(v))).join(", ")}
      </span>
    );
  }

  return <span>{String(value)}</span>;
}

function GenericStep({ step }: { step: TrailStep }) {
  const input = (step.tool_input ?? {}) as Record<string, unknown>;
  const vals = Object.values(input).map(String).join("  ").slice(0, 80);
  return (
    <div className="trail-step">
      <div className="text-xs font-mono" style={{ color: "var(--text-muted)" }}>{vals || "(no input)"}</div>
      {step.output_preview && (
        <details className="mt-1">
          <summary style={{ color: "var(--text-muted)", cursor: "pointer", fontSize: 11 }}>raw output</summary>
          <pre className="mt-1 whitespace-pre-wrap" style={{ color: "var(--text-secondary)", fontSize: 11, lineHeight: 1.5 }}>
            {step.output_preview}
          </pre>
        </details>
      )}
    </div>
  );
}

function Step({ step }: { step: TrailStep }) {
  let body: React.ReactNode;
  switch (step.tool) {
    case "news_catalysts":   body = <NewsStep step={step} />; break;
    case "search_arxiv":     body = <ArxivStep step={step} />; break;
    case "index_constituents": body = <ConstituentStep step={step} />; break;
    case "scan_cointegrated_pairs":
    case "scan_crypto_pairs": body = <ScanStep step={step} />; break;
    default:                 body = <GenericStep step={step} />; break;
  }

  return (
    <li className="trail-card">
      <StepHeader step={step} />
      {body}
    </li>
  );
}

export function Trail({ steps }: { steps: TrailStep[] }) {
  if (!steps.length) return <div className="text-xs" style={{ color: "var(--text-muted)" }}>No tool calls recorded.</div>;
  return (
    <ol className="flex flex-col gap-3 mt-2">
      {steps.map((s, i) => <Step key={i} step={s} />)}
    </ol>
  );
}

// ── Lazy-loaded run report ───────────────────────────────────────────────

export function RunTrail({ runId, label }: { runId: string; label?: string }) {
  const [steps, setSteps] = useState<TrailStep[] | null>(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    if (steps || loading) return;
    setLoading(true);
    try { setSteps((await getTrail(runId)).trail); }
    catch { setSteps([]); }
    finally { setLoading(false); }
  };

  return (
    <details className="mt-1" onToggle={(ev) => (ev.currentTarget as HTMLDetailsElement).open && load()}>
      <summary style={{ color: "var(--text-muted)", cursor: "pointer", fontSize: 13 }}>
        {label ?? "approach & sources"}{loading ? " · loading…" : ""}
        <span className="font-mono" style={{ color: "var(--border)" }}> {runId}</span>
      </summary>
      {steps && <><Digest steps={steps} /><Trail steps={steps} /></>}
    </details>
  );
}
