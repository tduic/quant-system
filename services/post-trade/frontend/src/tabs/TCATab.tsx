import { api } from '../api';
import { Card } from '../components/Card';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { usePolling } from '../hooks/usePolling';

export function TCATab() {
  const { data, loading, error } = usePolling(api.getTCA, 5000);

  if (loading) return <LoadingSpinner />;
  if (error) return <div className="text-red-400 p-4">Error: {error}</div>;
  if (!data) return null;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <Card title="Avg Spread (bps)" value={data.averages.spread_cost_bps.toFixed(2)} />
        <Card title="Avg Slippage (bps)" value={data.averages.slippage_bps.toFixed(2)} />
        <Card title="Avg Impact (bps)" value={data.averages.market_impact_bps.toFixed(2)} />
        <Card title="Avg Fee (bps)" value={data.averages.fee_bps.toFixed(2)} />
        <Card title="Avg Total Cost (bps)" value={data.averages.total_cost_bps.toFixed(2)} />
      </div>

      {data.fills.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
            Fill-Level TCA ({data.num_fills} fills)
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-400 border-b border-gray-800">
                  <th className="text-left py-2 px-3">Fill ID</th>
                  <th className="text-left py-2 px-3">Symbol</th>
                  <th className="text-left py-2 px-3">Side</th>
                  <th className="text-right py-2 px-3">Spread (bps)</th>
                  <th className="text-right py-2 px-3">Slippage (bps)</th>
                  <th className="text-right py-2 px-3">Impact (bps)</th>
                  <th className="text-right py-2 px-3">Fee (bps)</th>
                  <th className="text-right py-2 px-3">Total (bps)</th>
                </tr>
              </thead>
              <tbody>
                {data.fills.map((fill) => (
                  <tr key={fill.fill_id} className="border-b border-gray-800/50 hover:bg-gray-900/50">
                    <td className="py-2 px-3 font-mono text-xs">{fill.fill_id.slice(0, 12)}</td>
                    <td className="py-2 px-3 font-medium">{fill.symbol}</td>
                    <td className={`py-2 px-3 ${fill.side === 'buy' ? 'text-emerald-400' : 'text-red-400'}`}>
                      {fill.side.toUpperCase()}
                    </td>
                    <td className="text-right py-2 px-3">{fill.spread_cost_bps.toFixed(2)}</td>
                    <td className="text-right py-2 px-3">{fill.slippage_bps.toFixed(2)}</td>
                    <td className="text-right py-2 px-3">{fill.market_impact_bps.toFixed(2)}</td>
                    <td className="text-right py-2 px-3">{fill.fee_bps.toFixed(2)}</td>
                    <td className="text-right py-2 px-3 font-medium">{fill.total_cost_bps.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
