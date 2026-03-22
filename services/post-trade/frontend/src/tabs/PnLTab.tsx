import { api } from '../api';
import { Card } from '../components/Card';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { usePolling } from '../hooks/usePolling';

export function PnLTab() {
  const { data, loading, error } = usePolling(api.getPnL, 5000);

  if (loading) return <LoadingSpinner />;
  if (error) return <div className="text-red-400 p-4">Error: {error}</div>;
  if (!data) return null;

  const returnPositive = data.total_return_pct >= 0;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card title="Current Equity" value={`$${data.current_equity.toLocaleString()}`} />
        <Card title="Total Return" value={`${data.total_return_pct.toFixed(2)}%`} positive={returnPositive} />
        <Card title="Realized P&L" value={`$${data.total_realized_pnl.toLocaleString()}`} positive={data.total_realized_pnl >= 0} />
        <Card title="Unrealized P&L" value={`$${data.total_unrealized_pnl.toLocaleString()}`} positive={data.total_unrealized_pnl >= 0} />
        <Card title="Total Fees" value={`$${data.total_fees.toFixed(4)}`} />
        <Card title="Total Fills" value={data.num_fills} />
        <Card title="Initial Equity" value={`$${data.initial_equity.toLocaleString()}`} />
      </div>

      {Object.keys(data.positions).length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">Positions</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-400 border-b border-gray-800">
                  <th className="text-left py-2 px-3">Symbol</th>
                  <th className="text-right py-2 px-3">Qty</th>
                  <th className="text-right py-2 px-3">Avg Entry</th>
                  <th className="text-right py-2 px-3">Current</th>
                  <th className="text-right py-2 px-3">Realized</th>
                  <th className="text-right py-2 px-3">Unrealized</th>
                  <th className="text-right py-2 px-3">Fees</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(data.positions).map(([sym, pos]) => (
                  <tr key={sym} className="border-b border-gray-800/50 hover:bg-gray-900/50">
                    <td className="py-2 px-3 font-medium">{sym}</td>
                    <td className="text-right py-2 px-3">{pos.quantity.toFixed(6)}</td>
                    <td className="text-right py-2 px-3">${pos.avg_entry_price.toLocaleString()}</td>
                    <td className="text-right py-2 px-3">${pos.current_price.toLocaleString()}</td>
                    <td className={`text-right py-2 px-3 ${pos.realized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                      ${pos.realized_pnl.toFixed(2)}
                    </td>
                    <td className={`text-right py-2 px-3 ${pos.unrealized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                      ${pos.unrealized_pnl.toFixed(2)}
                    </td>
                    <td className="text-right py-2 px-3">${pos.total_fees.toFixed(4)}</td>
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
