// Empty = same-origin relative URLs. All /api/* calls go through the Next.js
// rewrite proxy (see next.config.ts → localhost:8420), so the dashboard works
// over LAN, Tailscale, or localhost without CORS or a hardcoded host.
const API_BASE = "";

async function fetchAPI<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export interface DashboardData {
  org_name: string;
  departments: DepartmentMetric[];
  total_spend_30d: number;
  total_runs_30d: number;
  budget: number | null;
  projects: ProjectSummary[];
  recent_activity: RunEntry[];
}

export interface DepartmentMetric {
  name: string;
  spend_7d: number;
  spend_30d: number;
  runs_7d: number;
  recent_runs: number;
  success_rate: number;
  failures: number;
}

export interface ProjectSummary {
  id: string;
  name: string;
  status: string;
  goal: string;
  task_count?: number;
  created_at?: string;
  updated_at?: string;
}

export interface ProjectDetail {
  project_id: string;
  project_name: string;
  project_status: string;
  goal: string;
  tasks_total: number;
  tasks_done: number;
  tasks_in_progress: number;
  tasks_todo: number;
  tasks_blocked: number;
  progress_pct: number;
  final_report?: string;
  tasks: TaskItem[];
}

export interface TaskItem {
  id: string;
  title: string;
  status: string;
  priority: string;
  department?: string;
  description?: string;
  updated_at?: string;
}

export interface RunEntry {
  id: string;
  department: string;
  role: string;
  status: string;
  summary: string;
  objective?: string;
  tokens: number;
  created_at: string;
}

export interface SchedulerJob {
  department: string;
  sop: string;
  cadence: string;
  last_run: string | null;
}

export interface CredentialRequest {
  proposal_id: string;
  department: string;
  credential_needs: { name: string; purpose: string; url?: string }[];
  reasoning: string;
}

export interface ToolRequest {
  proposal_id: string;
  department: string;
  recommended_tools: string[];
  recommended_mcps: string[];
  reasoning: string;
}

// ── Evolve (self-improvement proposals) ──────────────────────────────────

export interface EvolveProposal {
  id: string;
  status: string;
  type: string;
  target: string;
  summary: string;
  reasoning: string;
  risk: string;
  evidence: Record<string, unknown>;
  changes: Record<string, unknown>;
  recommended_tools: string[];
  recommended_mcps: string[];
  credential_needs: { name: string; purpose: string; url?: string }[];
  created_at: string;
  resolved_at: string | null;
}

export function getDashboard(): Promise<DashboardData> {
  return fetchAPI<DashboardData>("/api/dashboard");
}

export function getDepartments(): Promise<DepartmentMetric[]> {
  return fetchAPI<DepartmentMetric[]>("/api/departments");
}

export function getDepartmentRuns(name: string): Promise<RunEntry[]> {
  return fetchAPI<RunEntry[]>(`/api/departments/${name}/runs`);
}

export function getProjects(): Promise<ProjectSummary[]> {
  return fetchAPI<ProjectSummary[]>("/api/projects");
}

export function getProject(id: string): Promise<ProjectDetail> {
  return fetchAPI<ProjectDetail>(`/api/projects/${id}`);
}

export function getLogs(department?: string): Promise<RunEntry[]> {
  const query = department ? `?department=${department}&limit=100` : "?limit=100";
  return fetchAPI<RunEntry[]>(`/api/logs${query}`);
}

export function getProposals(): Promise<{
  credential_requests: CredentialRequest[];
  tool_requests: ToolRequest[];
  policy_changes: unknown[];
}> {
  return fetchAPI("/api/proposals");
}

export function getCredentials(): Promise<CredentialRequest[]> {
  return fetchAPI<CredentialRequest[]>("/api/credentials");
}

export function getToolRequests(): Promise<ToolRequest[]> {
  return fetchAPI<ToolRequest[]>("/api/tools");
}

export function getScheduler(): Promise<{ jobs: SchedulerJob[]; total: number }> {
  return fetchAPI("/api/scheduler");
}

export function getCalendar(): Promise<{ jobs: CalendarJob[] }> {
  return fetchAPI("/api/calendar");
}

export interface CalendarJob {
  department: string;
  sop: string;
  cadence: string;
  last_run: string | null;
  recent_runs: { status: string; tokens: number; at: string }[];
}

// ── Actions ──────────────────────────────────────────────────────────────

async function postAPI<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { method: "POST" });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export function runScheduler(): Promise<{ ran: number; results: unknown[] }> {
  return postAPI("/api/scheduler/run-pending");
}

export function runDepartment(name: string): Promise<{ department: string; status: string; summary: string; tokens: unknown }> {
  return postAPI(`/api/departments/${name}/run`);
}

export function dispatchProject(id: string): Promise<{ project_id: string; dispatched: number; results: unknown[] }> {
  return postAPI(`/api/projects/${id}/dispatch`);
}

export function resolveCredential(index: number): Promise<{ resolved: string; remaining: number }> {
  return postAPI(`/api/credentials/${index}/resolve`);
}

// ── Evolve ───────────────────────────────────────────────────────────────

export function triggerAnalysis(mode: "basic" | "deep" = "basic"): Promise<{
  mode: string;
  proposals_found: number;
  proposals_stored: number;
  proposal_ids: string[];
}> {
  return postJSON("/api/evolve/analyze", { mode });
}

export function getEvolveProposals(): Promise<{ proposals: EvolveProposal[] }> {
  return fetchAPI("/api/evolve/proposals");
}

export function approveProposal(id: string): Promise<{ approved: boolean; proposal_id: string; message: string }> {
  return postAPI(`/api/evolve/proposals/${id}/approve`);
}

export function denyProposal(id: string): Promise<{ denied: boolean; proposal_id: string }> {
  return postAPI(`/api/evolve/proposals/${id}/deny`);
}

export async function createProject(goal: string, name?: string): Promise<unknown> {
  const res = await fetch(`${API_BASE}/api/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ goal, name }),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

// ── Quant desk ───────────────────────────────────────────────────────────────

async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export interface Account {
  as_of: string;
  total_equity: number;
  available_funds: number;
  open_positions: number;
}
export interface ActivePair {
  pair_id: number;
  pair: string;
  y: string;
  x: string;
  z_score: number | null;
  as_of: string | null;
}
export interface Performance {
  closed_trades: number;
  wins: number;
  win_rate: number | null;
  total_realized_pnl: number;
  avg_pnl_per_trade: number;
}
export interface QuantBook {
  account: Account | null;
  active_pairs: ActivePair[];
  performance: Performance;
}

export const getBook = () => fetchAPI<QuantBook>("/api/quant/book");

export interface LegFiling { risk: string; high_forms: string[]; medium_forms: string[]; n_filings: number; }
export interface RiskAssessment {
  pair_id: number; pair: string;
  structural_risk: "LOW" | "MEDIUM" | "HIGH";
  recommend_halt: boolean; already_halted: boolean;
  leg_filings: Record<string, LegFiling>;
}
export interface RiskReport {
  active_pairs: RiskAssessment[];
  recommend_halt: RiskAssessment[];
  summary: string;
}
export const getRisk = () => fetchAPI<RiskReport>("/api/quant/risk");
export const postHalt = (pair_id: number, reason: string) =>
  postJSON<{ pair_id: number; halted: boolean; reason: string }>("/api/quant/halt", { pair_id, reason });

// ── Quant strategist (agent-driven discovery) ────────────────────────────────

export interface TrailStep {
  role: string;
  tool: string;
  tool_input: unknown;
  ok: boolean;
  output_preview: string;
  ts: string;
}
export interface RubricVerdict {
  passed: boolean;
  score: number;
  grader: string;
  notes: string;
}
export interface StrategistResult {
  status: string;
  criteria_met: boolean;
  summary: string;
  notes: string | null;
  tokens: number | null;
  run_id?: string;
  trail?: TrailStep[];
  attempts?: number;
  rubric?: RubricVerdict | null;
  attempt_run_ids?: string[];
}
// A hunt runs for minutes — longer than any proxy will hold a connection. So we
// dispatch (returns a job id) and poll for the result.
export const startStrategist = (objective: string, asset_class = "equity", allow_research = false, max_attempts = 2) =>
  postJSON<{ job_id: string; status: string }>("/api/quant/strategist", { objective, asset_class, allow_research, max_attempts });

export interface StrategistJob {
  job_id: string;
  status: "running" | "done" | "error";
  elapsed_s?: number;
  result?: StrategistResult;
  error?: string;
}
export const getStrategistJob = (jobId: string) =>
  fetchAPI<StrategistJob>(`/api/quant/strategist/${jobId}`);

// ── Journal (past hunts / discoveries) + research trails ─────────────────────

export interface JournalEntry {
  ts: string;
  objective: string;
  status: string;
  summary: string;
  tokens: number | null;
  run_id: string | null;
  score: number | null;
  attempts: number | null;
  attempt_run_ids?: string[];
}
export const getJournal = (limit = 25) =>
  fetchAPI<{ entries: JournalEntry[] }>(`/api/quant/journal?limit=${limit}`);

export interface TrailRun {
  run_id: string;
  ts: string;
  tool_calls: number;
  ok: number;
}
export const getTrails = (limit = 30) =>
  fetchAPI<{ runs: TrailRun[] }>(`/api/quant/trails?limit=${limit}`);

export const getTrail = (runId: string) =>
  fetchAPI<{ run_id: string; trail: TrailStep[] }>(`/api/quant/trail/${runId}`);

// ── Volatility ────────────────────────────────────────────────────────────────

export interface VolatilitySnapshot {
  ticker: string;
  current_vol: number;
  vol_1m: number | null;
  vol_3m: number | null;
  regime: string;
  spike: boolean;
  suggested_position_size: number;
  vix: { level: number; regime: string } | null;
}

export const getVolatility = (ticker: string) =>
  fetchAPI<VolatilitySnapshot>(`/api/quant/volatility/${ticker}`);

export interface IvRankEntry {
  ticker: string;
  iv_rank: number | null;
  current_iv_pct: number | null;
  low_52w: number | null;
  high_52w: number | null;
  signal: string | null;
  error?: string;
}

export const scanIvRank = (tickers: string[]) =>
  postJSON<{ results: IvRankEntry[]; count: number }>("/api/quant/volatility/iv-scan", { tickers });

// ── Options strategist ────────────────────────────────────────────────────────

export const startOptionsStrategist = (objective: string, view = "neutral", max_attempts = 2) =>
  postJSON<{ job_id: string; status: string; type: string }>(
    "/api/quant/options/strategist", { objective, view, max_attempts }
  );

export interface OptionsStrategistJob {
  job_id: string;
  status: "running" | "done" | "error";
  elapsed_s?: number;
  type?: string;
  result?: StrategistResult;
  error?: string;
}

export const getOptionsStrategistJob = (jobId: string) =>
  fetchAPI<OptionsStrategistJob>(`/api/quant/options/strategist/${jobId}`);

// ── Options tools (direct) ────────────────────────────────────────────────────

export interface OptionsSurface {
  ticker: string;
  spot: number | null;
  target_dte: number;
  atm_iv: number | null;
  skew: { call_25d: number | null; put_25d: number | null; risk_reversal: number | null; interpretation: string } | null;
  term_structure: { expiry: string; dte: number; atm_iv: number | null; label: string }[];
  edge_signal: string | null;
  rv: number | null;
  iv_vs_rv: { difference: number; signal: string; rationale: string } | null;
}

export const getOptionsSurface = (ticker: string, target_dte = 30, max_expiries = 8) =>
  postJSON<OptionsSurface>("/api/quant/options/surface", { ticker, target_dte, max_expiries });

export interface StrategySuggestion {
  ticker: string;
  iv_rank: number;
  top_strategy: string;
  candidates: { strategy: string; rationale: string; score: number }[];
}

export const getOptionsSuggest = (ticker: string, view = "neutral", target_dte = 30) =>
  postJSON<StrategySuggestion>("/api/quant/options/suggest", { ticker, view, target_dte });

export interface Greeks {
  option_type: string;
  price: number;
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
  rho: number;
}

export const computeGreeks = (S: number, K: number, T: number, r: number, sigma: number, option_type: string) =>
  postJSON<Greeks>("/api/quant/options/greeks", { S, K, T, r, sigma, option_type });
