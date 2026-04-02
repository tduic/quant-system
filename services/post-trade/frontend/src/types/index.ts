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

// Alpha Decay / IC Analysis
export interface HorizonIC {
  horizon_ms: number;
  horizon_label: string;
  ic: number | null;
  filled_count: number;
  total_signals: number;
}

export interface StrategyAlphaDecay {
  signal_count: number;
  horizons: Omit<HorizonIC, "total_signals">[];
}

export interface AlphaDecayData {
  horizons: HorizonIC[];
  total_signals: number;
  strategies: Record<string, StrategyAlphaDecay>;
}

// Backtest Analysis
export type AnalysisType =
  | "sensitivity"
  | "walk_forward"
  | "monte_carlo"
  | "cost_sweep"
  | "validate"
  | "run_all";

export type DataSource = "generated" | "historical";

export interface BacktestRun {
  backtest_id: string;
  symbol: string;
  timestamp: string;
  trades_replayed: number;
  duration_seconds: number;
  has_trades: boolean;
}

export interface AnalysisJobSummary {
  job_id: string;
  analysis_type: AnalysisType;
  status: "pending" | "running" | "completed" | "failed";
  progress: number;
  created_at: number;
  completed_at: number | null;
  has_result: boolean;
  error: string | null;
}

export interface AnalysisJobStatus {
  job_id: string;
  analysis_type: string;
  status: "pending" | "running" | "completed" | "failed";
  progress: number;
  error: string | null;
  has_result: boolean;
}

export interface AnalysisJobResult {
  job_id: string;
  analysis_type: string;
  status: string;
  result: Record<string, unknown>;
  error?: string;
}

export type TabId =
  | "pnl"
  | "tca"
  | "alpha-decay"
  | "risk-metrics"
  | "drawdown"
  | "fills"
  | "analysis";
