// API response types matching FastAPI endpoints

export interface Position {
  quantity: number;
  avg_entry_price: number;
  realized_pnl: number;
  unrealized_pnl: number;
  total_fees: number;
  current_price: number;
}

export interface PnLSummary {
  initial_equity: number;
  current_equity: number;
  total_realized_pnl: number;
  total_unrealized_pnl: number;
  total_fees: number;
  total_return_pct: number;
  positions: Record<string, Position>;
  num_fills: number;
}

export interface TCAFill {
  fill_id: string;
  symbol: string;
  side: string;
  spread_cost_bps: number;
  slippage_bps: number;
  market_impact_bps: number;
  fee_bps: number;
  total_cost_bps: number;
}

export interface TCAAverages {
  spread_cost_bps: number;
  slippage_bps: number;
  market_impact_bps: number;
  fee_bps: number;
  total_cost_bps: number;
}

export interface TCASummary {
  fills: TCAFill[];
  averages: TCAAverages;
  num_fills: number;
}

export interface RiskMetrics {
  sharpe_ratio: number;
  sortino_ratio: number | string;
  calmar_ratio: number;
  max_drawdown_pct: number;
  max_drawdown_duration_periods: number;
  total_return_pct: number;
  annualized_return_pct: number;
  win_rate_pct: number;
  profit_factor: number;
  num_trades: number;
  current_equity: number;
  peak_equity: number;
}

export interface EquityPoint {
  timestamp: number;
  equity: number;
}

export interface DrawdownPoint {
  timestamp: number;
  drawdown_pct: number;
}

export interface DrawdownData {
  equity_curve: EquityPoint[];
  drawdown_curve: DrawdownPoint[];
  current_drawdown_pct: number;
  peak_equity: number;
}

export interface FillRecord {
  fill_id: string;
  timestamp: number;
  symbol: string;
  side: string;
  quantity: number;
  fill_price: number;
  fee: number;
  slippage_bps: number;
  strategy_id: string;
}

export interface FillSummary {
  total_fills: number;
  buy_fills: number;
  sell_fills: number;
  avg_slippage_bps: number;
  total_fees: number;
}

export interface FillAnalysis {
  fills: FillRecord[];
  summary: FillSummary;
}

export type TabId = 'pnl' | 'tca' | 'alpha-decay' | 'risk-metrics' | 'drawdown' | 'fills';
