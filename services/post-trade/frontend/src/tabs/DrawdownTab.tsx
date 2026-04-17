import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  AreaChart,
  Area,
} from "recharts";
import { api } from "../api";
import { Card } from "../components/Card";
import { LoadingSpinner } from "../components/LoadingSpinner";
import { usePolling } from "../hooks/usePolling";

function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function DrawdownTab({ symbol: _symbol }: { symbol?: string }) {
  const { data, loading, error } = usePolling(api.getDrawdown, 5000);

  if (loading) return <LoadingSpinner />;
  if (error) return <div className="text-red-400 p-4">Error: {error}</div>;
  if (!data) return null;

  const equityData = data.equity_curve.map((pt) => ({
    time: formatTime(pt.timestamp),
    equity: pt.equity,
  }));

  const drawdownData = data.drawdown_curve.map((pt) => ({
    time: formatTime(pt.timestamp),
    drawdown: pt.drawdown_pct,
  }));

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        <Card
          title="Current Drawdown"
          value={`${data.current_drawdown_pct.toFixed(2)}%`}
          positive={data.current_drawdown_pct === 0}
        />
        <Card
          title="Peak Equity"
          value={`$${data.peak_equity.toLocaleString()}`}
        />
        <Card
          title="Equity Points"
          value={data.equity_curve.length}
          subtitle="data points tracked"
        />
      </div>

      {equityData.length > 1 && (
        <div>
          <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
            Equity Curve
          </h3>
          <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={equityData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                <XAxis
                  dataKey="time"
                  tick={{ fill: "#9CA3AF", fontSize: 11 }}
                />
                <YAxis tick={{ fill: "#9CA3AF", fontSize: 11 }} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#1F2937",
                    border: "1px solid #374151",
                    borderRadius: "8px",
                  }}
                  labelStyle={{ color: "#9CA3AF" }}
                  itemStyle={{ color: "#34D399" }}
                />
                <Line
                  type="monotone"
                  dataKey="equity"
                  stroke="#34D399"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {drawdownData.length > 1 && (
        <div>
          <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
            Drawdown Curve
          </h3>
          <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
            <ResponsiveContainer width="100%" height={250}>
              <AreaChart data={drawdownData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                <XAxis
                  dataKey="time"
                  tick={{ fill: "#9CA3AF", fontSize: 11 }}
                />
                <YAxis tick={{ fill: "#9CA3AF", fontSize: 11 }} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#1F2937",
                    border: "1px solid #374151",
                    borderRadius: "8px",
                  }}
                  labelStyle={{ color: "#9CA3AF" }}
                  itemStyle={{ color: "#F87171" }}
                />
                <Area
                  type="monotone"
                  dataKey="drawdown"
                  stroke="#F87171"
                  fill="#F87171"
                  fillOpacity={0.15}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </div>
  );
}
