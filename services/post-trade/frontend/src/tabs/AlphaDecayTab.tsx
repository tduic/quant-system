import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import { useCallback } from "react";
import { api } from "../api";
import { Card } from "../components/Card";
import { LoadingSpinner } from "../components/LoadingSpinner";
import { usePolling } from "../hooks/usePolling";

export function AlphaDecayTab({ symbol }: { symbol?: string }) {
  const fetcher = useCallback(() => api.getAlphaDecay(symbol), [symbol]);
  const { data, loading, error } = usePolling(fetcher, 5000);

  if (loading) return <LoadingSpinner />;
  if (error) return <div className="text-red-400 p-4">Error: {error}</div>;
  if (!data) return null;

  const hasData =
    data.total_signals > 0 && data.horizons.some((h) => h.ic !== null);

  // Chart data: IC at each horizon
  const chartData = data.horizons.map((h) => ({
    horizon: h.horizon_label,
    ic: h.ic ?? 0,
    filled: h.filled_count,
    hasValue: h.ic !== null,
  }));

  const strategyIds = Object.keys(data.strategies);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card title="Total Signals" value={data.total_signals} />
        <Card
          title="Strategies"
          value={strategyIds.length}
          subtitle={strategyIds.join(", ").slice(0, 40) || "none"}
        />
        <Card
          title="Best IC"
          value={
            data.horizons.some((h) => h.ic !== null)
              ? Math.max(
                  ...data.horizons
                    .filter((h) => h.ic !== null)
                    .map((h) => h.ic!),
                ).toFixed(4)
              : "N/A"
          }
          positive={data.horizons.some((h) => h.ic !== null && h.ic > 0)}
        />
        <Card
          title="Shortest Horizon Filled"
          value={
            data.horizons.find((h) => h.filled_count > 0)?.horizon_label ??
            "N/A"
          }
        />
      </div>

      {!hasData ? (
        <div className="flex items-center justify-center py-16">
          <div className="text-center max-w-md">
            <h3 className="text-lg font-semibold text-gray-200 mb-2">
              Waiting for Signal Data
            </h3>
            <p className="text-gray-400 text-sm leading-relaxed">
              IC decay curves will appear once enough signals have been emitted
              and sufficient time has passed for horizon returns to be
              evaluated. At least 5 signals with filled horizons are needed.
            </p>
          </div>
        </div>
      ) : (
        <>
          <div>
            <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
              IC Decay Curve (All Strategies)
            </h3>
            <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis
                    dataKey="horizon"
                    tick={{ fill: "#9CA3AF", fontSize: 12 }}
                  />
                  <YAxis
                    tick={{ fill: "#9CA3AF", fontSize: 11 }}
                    domain={[-1, 1]}
                    tickFormatter={(v: number) => v.toFixed(2)}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#1F2937",
                      border: "1px solid #374151",
                      borderRadius: "8px",
                    }}
                    labelStyle={{ color: "#9CA3AF" }}
                    formatter={(value: number) => [
                      typeof value === "number" ? value.toFixed(4) : "N/A",
                      "IC",
                    ]}
                  />
                  <ReferenceLine y={0} stroke="#6B7280" strokeDasharray="3 3" />
                  <Bar dataKey="ic" fill="#3B82F6" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div>
            <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
              Horizon Detail
            </h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-gray-400 border-b border-gray-800">
                    <th className="text-left py-2 px-3">Horizon</th>
                    <th className="text-right py-2 px-3">IC</th>
                    <th className="text-right py-2 px-3">Filled Signals</th>
                    <th className="text-right py-2 px-3">Total Signals</th>
                    <th className="text-right py-2 px-3">Fill Rate</th>
                  </tr>
                </thead>
                <tbody>
                  {data.horizons.map((h) => (
                    <tr
                      key={h.horizon_ms}
                      className="border-b border-gray-800/50"
                    >
                      <td className="py-2 px-3 font-medium">
                        {h.horizon_label}
                      </td>
                      <td
                        className={`text-right py-2 px-3 font-mono ${
                          h.ic === null
                            ? "text-gray-500"
                            : h.ic > 0
                              ? "text-emerald-400"
                              : "text-red-400"
                        }`}
                      >
                        {h.ic !== null ? h.ic.toFixed(4) : "N/A"}
                      </td>
                      <td className="text-right py-2 px-3">{h.filled_count}</td>
                      <td className="text-right py-2 px-3">
                        {h.total_signals}
                      </td>
                      <td className="text-right py-2 px-3">
                        {h.total_signals > 0
                          ? `${((h.filled_count / h.total_signals) * 100).toFixed(0)}%`
                          : "0%"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {strategyIds.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
                Per-Strategy IC
              </h3>
              <div className="grid gap-4">
                {strategyIds.map((stratId) => {
                  const strat = data.strategies[stratId];
                  const stratChartData = strat.horizons.map((h) => ({
                    horizon: h.horizon_label,
                    ic: h.ic ?? 0,
                    hasValue: h.ic !== null,
                  }));
                  return (
                    <div
                      key={stratId}
                      className="bg-gray-900 rounded-lg p-4 border border-gray-800"
                    >
                      <div className="flex items-center justify-between mb-3">
                        <span className="text-sm font-medium">{stratId}</span>
                        <span className="text-xs text-gray-400">
                          {strat.signal_count} signals
                        </span>
                      </div>
                      <ResponsiveContainer width="100%" height={180}>
                        <BarChart data={stratChartData}>
                          <CartesianGrid
                            strokeDasharray="3 3"
                            stroke="#374151"
                          />
                          <XAxis
                            dataKey="horizon"
                            tick={{ fill: "#9CA3AF", fontSize: 11 }}
                          />
                          <YAxis
                            tick={{ fill: "#9CA3AF", fontSize: 10 }}
                            domain={[-1, 1]}
                            tickFormatter={(v: number) => v.toFixed(1)}
                          />
                          <ReferenceLine
                            y={0}
                            stroke="#6B7280"
                            strokeDasharray="3 3"
                          />
                          <Bar
                            dataKey="ic"
                            fill="#8B5CF6"
                            radius={[4, 4, 0, 0]}
                          />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
