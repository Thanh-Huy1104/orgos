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

export async function createProject(goal: string, name?: string): Promise<any> {
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
export interface Candidate {
  pair: string; y: string; x: string;
  adf_p: number; beta: number; half_life: number; hurst: number;
  stable: boolean; beta_drift: number; spread_vol: number;
  factor_r2: number | null; sub_pvalues: (number | null)[]; sector: string;
}
export interface ScanResult {
  universe: string; sector: string; tickers_scanned: string[];
  factor: string; candidates_found: number; candidates: Candidate[]; error?: string;
}
export interface LegFiling { risk: string; high_forms: string[]; medium_forms: string[]; n_filings: number; }
export interface Dossier {
  pair: string;
  verdict: "PROMOTE" | "REVIEW" | "HOLD";
  structural_risk: "LOW" | "MEDIUM" | "HIGH";
  reasons: string[];
  stats: Record<string, unknown>;
  leg_filings: Record<string, LegFiling>;
}
export interface RecommendReport {
  live: QuantBook;
  propose_spawn: Dossier[];
  promote_already_held: Dossier[];
  review: Dossier[];
  hold: Dossier[];
  summary: string;
}

export const getUniverses = () => fetchAPI<{ universes: Record<string, string[]> }>("/api/quant/universes");
export const getBook = () => fetchAPI<QuantBook>("/api/quant/book");
export const runScan = (universe: string, lookback_days = 504) =>
  postJSON<ScanResult>("/api/quant/scan", { universe, lookback_days });
export const getRecommend = (universes: string[], gate_days = 90) =>
  postJSON<RecommendReport>("/api/quant/recommend", { universes, gate_days });
