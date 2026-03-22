import { api } from '../api';
import { Card } from '../components/Card';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { usePolling } from '../hooks/usePolling';

function fmt(v: number | string, decimals = 2): string {
  if (typeof v === 'string') return v;
  return v.toFixed(decimals);
}

export function RiskMetricsTab() {
  const { data, loading, error } = usePolling(api.getRiskMetrics, 5000);

  if (loading) return <LoadingSpinner />;
  if (error) return <div className="text-red-400 p-4">Error: {error}</div>;
  if (!data) return null;

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">Return Ratios</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <Card title="Sharpe Ratio" value={fmt(data.sharpe_ratio)} positive={Number(data.sharpe_ratio) > 0} />
          <Card title="Sortino Ratio" value={fmt(data.sortino_ratio)} positive={Number(data.sortino_ratio) > 0} />
          <Card title="Calmar Ratio" value={fmt(data.calmar_ratio)} positive={Number(data.calmar_ratio) > 0} />
          <Card title="Profit Factor" value={fmt(data.profit_factor)} positive={Number(data.profit_factor) > 1} />
        </div>
      </div>

      <div>
        <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">Returns</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <Card title="Total Return" value={`${fmt(data.total_return_pct)}%`} positive={data.total_return_pct >= 0} />
          <Card title="Annualized Return" value={`${fmt(data.annualized_return_pct)}%`} positive={data.annualized_return_pct >= 0} />
          <Card title="Win Rate" value={`${fmt(data.win_rate_pct)}%`} positive={data.win_rate_pct > 50} />
          <Card title="Num Trades" value={data.num_trades} />
        </div>
      </div>

      <div>
        <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">Drawdown & Equity</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <Card title="Max Drawdown" value={`${fmt(data.max_drawdown_pct)}%`} positive={false} />
          <Card title="Max DD Duration" value={`${data.max_drawdown_duration_periods} periods`} />
          <Card title="Current Equity" value={`$${data.current_equity.toLocaleString()}`} />
          <Card title="Peak Equity" value={`$${data.peak_equity.toLocaleString()}`} />
        </div>
      </div>
    </div>
  );
}
