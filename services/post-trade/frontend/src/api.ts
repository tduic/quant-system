import type {
  PnLSummary,
  TCASummary,
  RiskMetrics,
  DrawdownData,
  FillAnalysis,
  AlphaDecayData,
  AnalysisType,
  AnalysisJobSummary,
  AnalysisJobStatus,
  AnalysisJobResult,
  BacktestRun,
} from "./types";

const BASE = "/api";

async function fetchJson<T>(
  path: string,
  params?: Record<string, string>,
): Promise<T> {
  const url = new URL(`${BASE}${path}`, window.location.origin);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v) url.searchParams.set(k, v);
    }
  }
  const res = await fetch(url.toString());
  if (!res.ok) throw new Error(`API error: ${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`API error: ${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export const api = {
  getSymbols: () => fetchJson<{ symbols: string[] }>("/symbols"),
  getPnL: (symbol?: string) =>
    fetchJson<PnLSummary>("/pnl", symbol ? { symbol } : undefined),
  getTCA: (symbol?: string) =>
    fetchJson<TCASummary>("/tca", symbol ? { symbol } : undefined),
  getRiskMetrics: () => fetchJson<RiskMetrics>("/risk-metrics"),
  getDrawdown: () => fetchJson<DrawdownData>("/drawdown"),
  getFills: (symbol?: string) =>
    fetchJson<FillAnalysis>("/fills", symbol ? { symbol } : undefined),
  getAlphaDecay: (symbol?: string) =>
    fetchJson<AlphaDecayData>("/alpha-decay", symbol ? { symbol } : undefined),
  exportExcel: () => {
    window.open(`${BASE}/export/excel`, "_blank");
  },

  // Analysis jobs
  submitAnalysis: (
    analysisType: AnalysisType,
    params: Record<string, unknown> = {},
  ) =>
    postJson<{ job_id: string }>("/analysis/submit", {
      analysis_type: analysisType,
      params,
    }),
  getJobStatus: (jobId: string) =>
    fetchJson<AnalysisJobStatus>(`/analysis/status/${jobId}`),
  getJobResult: (jobId: string) =>
    fetchJson<AnalysisJobResult>(`/analysis/result/${jobId}`),
  listJobs: (limit = 20) =>
    fetchJson<{ jobs: AnalysisJobSummary[] }>(`/analysis/jobs`, {
      limit: String(limit),
    }),
  listBacktests: () =>
    fetchJson<{ backtests: BacktestRun[] }>("/analysis/backtests"),
};
