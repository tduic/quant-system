import { api } from "../api";
import { Card } from "../components/Card";
import { LoadingSpinner } from "../components/LoadingSpinner";
import { usePolling } from "../hooks/usePolling";

function formatTimestamp(ts: number): string {
  return new Date(ts).toLocaleString();
}

import { useCallback } from "react";

export function FillsTab({ symbol }: { symbol?: string }) {
  const fetcher = useCallback(() => api.getFills(symbol), [symbol]);
  const { data, loading, error } = usePolling(fetcher, 5000);

  if (loading) return <LoadingSpinner />;
  if (error) return <div className="text-red-400 p-4">Error: {error}</div>;
  if (!data) return null;

  const { summary } = data;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <Card title="Total Fills" value={summary.total_fills} />
        <Card title="Buy Fills" value={summary.buy_fills} />
        <Card title="Sell Fills" value={summary.sell_fills} />
        <Card
          title="Avg Slippage (bps)"
          value={summary.avg_slippage_bps.toFixed(2)}
        />
        <Card title="Total Fees" value={`$${summary.total_fees.toFixed(4)}`} />
      </div>

      {data.fills.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
            Fill Log ({data.fills.length} fills)
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-400 border-b border-gray-800">
                  <th className="text-left py-2 px-3">Time</th>
                  <th className="text-left py-2 px-3">Fill ID</th>
                  <th className="text-left py-2 px-3">Symbol</th>
                  <th className="text-left py-2 px-3">Side</th>
                  <th className="text-right py-2 px-3">Qty</th>
                  <th className="text-right py-2 px-3">Price</th>
                  <th className="text-right py-2 px-3">Fee</th>
                  <th className="text-right py-2 px-3">Slippage (bps)</th>
                  <th className="text-left py-2 px-3">Strategy</th>
                </tr>
              </thead>
              <tbody>
                {[...data.fills].reverse().map((fill) => (
                  <tr
                    key={fill.fill_id}
                    className="border-b border-gray-800/50 hover:bg-gray-900/50"
                  >
                    <td className="py-2 px-3 text-xs text-gray-400">
                      {formatTimestamp(fill.timestamp)}
                    </td>
                    <td className="py-2 px-3 font-mono text-xs">
                      {fill.fill_id.slice(0, 12)}
                    </td>
                    <td className="py-2 px-3 font-medium">{fill.symbol}</td>
                    <td
                      className={`py-2 px-3 ${fill.side === "buy" ? "text-emerald-400" : "text-red-400"}`}
                    >
                      {fill.side.toUpperCase()}
                    </td>
                    <td className="text-right py-2 px-3">
                      {fill.quantity.toFixed(6)}
                    </td>
                    <td className="text-right py-2 px-3">
                      ${fill.fill_price.toLocaleString()}
                    </td>
                    <td className="text-right py-2 px-3">
                      ${fill.fee.toFixed(4)}
                    </td>
                    <td className="text-right py-2 px-3">
                      {fill.slippage_bps.toFixed(2)}
                    </td>
                    <td className="py-2 px-3 text-xs text-gray-400">
                      {fill.strategy_id}
                    </td>
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
