"use client";

import { useEffect, useState } from "react";
import {
  getEvolveProposals,
  getProposals,
  triggerAnalysis,
  approveProposal,
  denyProposal,
  resolveCredential,
  EvolveProposal,
  CredentialRequest,
  ToolRequest,
} from "@/lib/api";

type Tab = "evolve" | "requests";

export default function ProposalsPage() {
  const [tab, setTab] = useState<Tab>("evolve");
  const [proposals, setProposals] = useState<EvolveProposal[]>([]);
  const [creds, setCreds] = useState<CredentialRequest[]>([]);
  const [tools, setTools] = useState<ToolRequest[]>([]);
  const [msg, setMsg] = useState("");
  const [analyzing, setAnalyzing] = useState(false);

  const loadEvolve = () =>
    getEvolveProposals().then((d) => setProposals(d.proposals || []));
  const loadRequests = () =>
    getProposals().then((d) => {
      setCreds(d.credential_requests);
      setTools(d.tool_requests);
    });

  useEffect(() => {
    if (tab === "evolve") loadEvolve();
    else loadRequests();
  }, [tab]);

  const doAnalyze = async (mode: "basic" | "deep") => {
    setAnalyzing(true);
    setMsg("");
    try {
      const r = await triggerAnalysis(mode);
      setMsg(
        `Analysis complete: ${r.proposals_found} proposals found (${mode}).`
      );
      loadEvolve();
    } catch (e: any) {
      setMsg(`Error: ${e.message}`);
    }
    setAnalyzing(false);
  };

  const doApprove = async (id: string) => {
    try {
      const r = await approveProposal(id);
      setMsg(r.approved ? `Approved: ${r.message}` : `Failed: ${r.message}`);
      loadEvolve();
    } catch (e: any) {
      setMsg(`Error: ${e.message}`);
    }
  };

  const doDeny = async (id: string) => {
    try {
      await denyProposal(id);
      setMsg("Proposal denied.");
      loadEvolve();
    } catch (e: any) {
      setMsg(`Error: ${e.message}`);
    }
  };

  const doResolve = async (i: number) => {
    try {
      const r = await resolveCredential(i);
      setMsg(`Resolved. ${r.remaining} remaining.`);
      loadRequests();
    } catch (e: any) {
      setMsg(`${e.message}`);
    }
  };

  const typeLabel = (t: string) => {
    const labels: Record<string, string> = {
      create_department: "New Dept",
      add_role: "Add Role",
      add_sop: "New SOP",
      add_handoff: "Add Handoff",
      modify_threshold: "Threshold",
      modify_cadence: "Cadence",
      add_policy_rule: "Policy",
      needs_tools: "Tools",
      needs_credentials: "Credentials",
    };
    return labels[t] || t;
  };

  const riskColor = (r: string) =>
    r === "high" ? "var(--red)" : r === "medium" ? "var(--yellow)" : "var(--green)";

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Proposals</h1>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 border-b" style={{ borderColor: "var(--border)" }}>
        {(["evolve", "requests"] as Tab[]).map((t) => (
          <button
            key={t}
            className={`px-3 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === t
                ? ""
                : "border-transparent"
            }`}
            style={
              tab === t
                ? { borderColor: "var(--blue)", color: "var(--blue)" }
                : { color: "var(--text-muted)" }
            }
            onClick={() => setTab(t)}
          >
            {t === "evolve" ? "Evolution" : "Requests"}
          </button>
        ))}
      </div>

      {msg && (
        <div
          className="text-sm p-3 rounded-lg"
          style={{ background: "var(--bg-secondary)" }}
        >
          {msg}
        </div>
      )}

      {/* Evolution tab */}
      {tab === "evolve" && (
        <div className="space-y-4">
          <div className="flex gap-2">
            <button
              className="btn btn-primary text-sm"
              disabled={analyzing}
              onClick={() => doAnalyze("basic")}
            >
              {analyzing ? "Analyzing..." : "Run Basic Analysis"}
            </button>
            <button
              className="btn btn-secondary text-sm"
              disabled={analyzing}
              onClick={() => doAnalyze("deep")}
            >
              Deep Analysis (LLM)
            </button>
          </div>

          {proposals.length === 0 && (
            <div className="card text-sm" style={{ color: "var(--text-muted)" }}>
              No pending proposals. Run an analysis to discover improvement
              opportunities.
            </div>
          )}

          {proposals.map((p) => (
            <div key={p.id} className="card space-y-3">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 space-y-2">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span
                      className="text-xs px-2 py-0.5 rounded font-medium"
                      style={{
                        background: "var(--bg-secondary)",
                        color: "var(--text-secondary)",
                      }}
                    >
                      {typeLabel(p.type)}
                    </span>
                    <span className="text-sm font-medium">{p.summary}</span>
                    <span
                      className="text-xs"
                      style={{ color: riskColor(p.risk) }}
                    >
                      {p.risk}
                    </span>
                  </div>
                  <div
                    className="text-xs"
                    style={{ color: "var(--text-muted)" }}
                  >
                    Target: {p.target}
                  </div>
                  <div
                    className="text-sm"
                    style={{ color: "var(--text-secondary)" }}
                  >
                    {p.reasoning}
                  </div>
                  {Object.keys(p.evidence).length > 0 && (
                    <div
                      className="text-xs space-y-0.5"
                      style={{ color: "var(--text-muted)" }}
                    >
                      {Object.entries(p.evidence).map(([k, v]) => (
                        <div key={k}>
                          <span className="font-medium">{k}:</span>{" "}
                          {String(v)}
                        </div>
                      ))}
                    </div>
                  )}
                  {p.recommended_tools.length > 0 && (
                    <div className="flex gap-1 flex-wrap">
                      {p.recommended_tools.map((t) => (
                        <span key={t} className="badge badge-blue">
                          {t}
                        </span>
                      ))}
                    </div>
                  )}
                  {p.credential_needs.length > 0 && (
                    <div
                      className="text-xs p-2 rounded"
                      style={{ background: "var(--bg-secondary)" }}
                    >
                      {p.credential_needs.map((n, j) => (
                        <div key={j}>
                          <span
                            className="font-mono"
                            style={{ color: "var(--blue)" }}
                          >
                            {n.name}
                          </span>
                          <span
                            className="ml-2"
                            style={{ color: "var(--text-secondary)" }}
                          >
                            — {n.purpose}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
              <div className="flex gap-2 justify-end">
                <button
                  className="btn btn-green text-xs"
                  onClick={() => doApprove(p.id)}
                >
                  Approve
                </button>
                <button
                  className="btn btn-secondary text-xs"
                  style={{ color: "var(--red)" }}
                  onClick={() => doDeny(p.id)}
                >
                  Deny
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Requests tab — legacy credential + tool requests */}
      {tab === "requests" && (
        <div className="space-y-4">
          {creds.length === 0 && tools.length === 0 && (
            <div className="card text-sm" style={{ color: "var(--text-muted)" }}>
              No pending requests. The org will ask for credentials and tools
              when needed.
            </div>
          )}
          {creds.map((c, i) => (
            <div
              key={i}
              className="card"
              style={{ borderColor: "var(--yellow)" }}
            >
              <div className="flex justify-between items-center">
                <span
                  className="text-sm font-medium"
                  style={{ color: "var(--yellow)" }}
                >
                  {c.department} — Credential Request
                </span>
                <button
                  className="btn btn-green text-xs"
                  onClick={() => doResolve(i)}
                >
                  Resolved
                </button>
              </div>
              {c.credential_needs.map((n, j) => (
                <div
                  key={j}
                  className="text-sm p-2 rounded mt-1"
                  style={{ background: "var(--bg-secondary)" }}
                >
                  <span
                    className="font-mono"
                    style={{ color: "var(--blue)" }}
                  >
                    {n.name}
                  </span>
                  <span
                    className="ml-2"
                    style={{ color: "var(--text-secondary)" }}
                  >
                    — {n.purpose}
                  </span>
                  {n.url && (
                    <div
                      className="text-xs mt-0.5"
                      style={{ color: "var(--text-muted)" }}
                    >
                      {n.url}
                    </div>
                  )}
                </div>
              ))}
            </div>
          ))}
          {tools.map((t, i) => (
            <div
              key={i}
              className="card"
              style={{ borderColor: "var(--blue)" }}
            >
              <span
                className="text-sm font-medium"
                style={{ color: "var(--blue)" }}
              >
                {t.department} — Tool Request
              </span>
              <div className="flex gap-1 mt-2">
                {t.recommended_tools.map((tool) => (
                  <span key={tool} className="badge badge-blue">
                    {tool}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
