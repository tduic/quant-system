import type { PnLSummary, TCASummary, RiskMetrics, DrawdownData, FillAnalysis, AlphaDecayData } from './types';

const BASE = '/api';

async function fetchJson<T>(path: string, params?: Record<string, string>): Promise<T> {
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

export const api = {
  getSymbols: () => fetchJson<{ symbols: string[] }>('/symbols'),
  getPnL: (symbol?: string) => fetchJson<PnLSummary>('/pnl', symbol ? { symbol } : undefined),
  getTCA: (symbol?: string) => fetchJson<TCASummary>('/tca', symbol ? { symbol } : undefined),
  getRiskMetrics: () => fetchJson<RiskMetrics>('/risk-metrics'),
  getDrawdown: () => fetchJson<DrawdownData>('/drawdown'),
  getFills: (symbol?: string) => fetchJson<FillAnalysis>('/fills', symbol ? { symbol } : undefined),
  getAlphaDecay: (symbol?: string) => fetchJson<AlphaDecayData>('/alpha-decay', symbol ? { symbol } : undefined),
  exportExcel: () => {
    window.open(`${BASE}/export/excel`, '_blank');
  },
};
