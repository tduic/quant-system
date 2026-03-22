import type { PnLSummary, TCASummary, RiskMetrics, DrawdownData, FillAnalysis } from './types';

const BASE = '/api';

async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`API error: ${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export const api = {
  getPnL: () => fetchJson<PnLSummary>('/pnl'),
  getTCA: () => fetchJson<TCASummary>('/tca'),
  getRiskMetrics: () => fetchJson<RiskMetrics>('/risk-metrics'),
  getDrawdown: () => fetchJson<DrawdownData>('/drawdown'),
  getFills: () => fetchJson<FillAnalysis>('/fills'),
  getAlphaDecay: () => fetchJson<{ status: string; description: string }>('/alpha-decay'),
  exportExcel: () => {
    window.open(`${BASE}/export/excel`, '_blank');
  },
};
