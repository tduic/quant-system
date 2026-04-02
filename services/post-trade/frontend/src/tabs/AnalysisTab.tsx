import { useState, useEffect, useCallback } from "react";
import { api } from "../api";
import { Card } from "../components/Card";

import type {
  AnalysisType,
  AnalysisJobSummary,
  AnalysisJobResult,
  DataSource,
  BacktestRun,
} from "../types";

interface AnalysisOption {
  type: AnalysisType;
  label: string;
  description: string;
}

const ANALYSES: AnalysisOption[] = [
  {
    type: "sensitivity",
    label: "Param Sensitivity",
    description:
      "Grid/random search over strategy parameters to find optimal Sharpe",
  },
  {
    type: "walk_forward",
    label: "Walk-Forward",
    description:
      "Rolling train/test splits to detect overfitting and measure OOS performance",
  },
  {
    type: "monte_carlo",
    label: "Monte Carlo",
    description:
      "Bootstrap simulation for Sharpe/drawdown confidence intervals",
  },
  {
    type: "cost_sweep",
    label: "Cost Sweep",
    description: "Sweep fee rates and slippage to find breakeven thresholds",
  },
  {
    type: "validate",
    label: "Full Validation",
    description:
      "Combined walk-forward + Monte Carlo + cost sweep with graded report",
  },
  {
    type: "run_all",
    label: "Run All",
    description:
      "Run every analysis (sensitivity, walk-forward, Monte Carlo, cost sweep, validation) in one job",
  },
];

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    pending: "bg-yellow-900 text-yellow-300",
    running: "bg-blue-900 text-blue-300",
    completed: "bg-emerald-900 text-emerald-300",
    failed: "bg-red-900 text-red-300",
  };
  return (
    <span
      className={`px-2 py-0.5 rounded text-xs font-medium ${colors[status] ?? "bg-gray-700 text-gray-300"}`}
    >
      {status}
    </span>
  );
}

function ProgressBar({ progress }: { progress: number }) {
  return (
    <div className="w-full bg-gray-800 rounded-full h-1.5 mt-1">
      <div
        className="bg-blue-500 h-1.5 rounded-full transition-all duration-300"
        style={{ width: `${progress}%` }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Result renderers per analysis type
// ---------------------------------------------------------------------------

function SensitivityResult({ result }: { result: Record<string, unknown> }) {
  const impacts =
    (result.param_impacts as Array<Record<string, unknown>>) ?? [];
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <Card
          title="Best Sharpe"
          value={(result.best_sharpe as number)?.toFixed(4) ?? "—"}
          positive={(result.best_sharpe as number) > 0}
        />
        <Card
          title="Evaluations"
          value={(result.num_evaluations as number) ?? 0}
        />
        <Card
          title="Search Method"
          value={(result.search_method as string) ?? "—"}
        />
      </div>
      <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
        <h4 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
          Best Parameters
        </h4>
        <pre className="text-sm text-gray-200 font-mono">
          {JSON.stringify(result.best_params, null, 2)}
        </pre>
      </div>
      {impacts.length > 0 && (
        <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
          <h4 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
            Parameter Impacts
          </h4>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-400 text-xs uppercase">
                <th className="text-left py-1">Param</th>
                <th className="text-right py-1">Sharpe Range</th>
                <th className="text-right py-1">Correlation</th>
                <th className="text-right py-1">Best</th>
                <th className="text-right py-1">Worst</th>
              </tr>
            </thead>
            <tbody>
              {impacts.map((imp) => (
                <tr
                  key={imp.name as string}
                  className="border-t border-gray-800"
                >
                  <td className="py-1.5 text-gray-200 font-mono">
                    {imp.name as string}
                  </td>
                  <td className="py-1.5 text-right text-gray-300">
                    {(imp.sharpe_range as number)?.toFixed(4)}
                  </td>
                  <td className="py-1.5 text-right text-gray-300">
                    {(imp.correlation as number)?.toFixed(3)}
                  </td>
                  <td className="py-1.5 text-right text-emerald-400">
                    {String(imp.best_value)}
                  </td>
                  <td className="py-1.5 text-right text-red-400">
                    {String(imp.worst_value)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function WalkForwardResult({ result }: { result: Record<string, unknown> }) {
  const folds = (result.folds as Array<Record<string, unknown>>) ?? [];
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Card
          title="Mean OOS Sharpe"
          value={(result.mean_test_sharpe as number)?.toFixed(4) ?? "—"}
          positive={(result.mean_test_sharpe as number) > 0}
        />
        <Card
          title="Std OOS Sharpe"
          value={(result.std_test_sharpe as number)?.toFixed(4) ?? "—"}
        />
        <Card
          title="Overfitting Ratio"
          value={`${(result.overfitting_ratio as number)?.toFixed(2)}x`}
          positive={(result.overfitting_ratio as number) < 2}
        />
        <Card
          title="Degradation"
          value={`${(result.degradation_pct as number)?.toFixed(1)}%`}
          positive={(result.degradation_pct as number) < 30}
        />
      </div>
      {folds.length > 0 && (
        <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
          <h4 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
            Fold Results
          </h4>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-400 text-xs uppercase">
                <th className="text-left py-1">Fold</th>
                <th className="text-right py-1">Train Sharpe</th>
                <th className="text-right py-1">Test Sharpe</th>
                <th className="text-left py-1 pl-4">Best Params</th>
              </tr>
            </thead>
            <tbody>
              {folds.map((f) => (
                <tr key={f.fold as number} className="border-t border-gray-800">
                  <td className="py-1.5 text-gray-200">{f.fold as number}</td>
                  <td className="py-1.5 text-right text-gray-300">
                    {(f.train_sharpe as number)?.toFixed(4)}
                  </td>
                  <td className="py-1.5 text-right text-gray-300">
                    {(f.test_sharpe as number)?.toFixed(4)}
                  </td>
                  <td className="py-1.5 pl-4 text-gray-400 font-mono text-xs">
                    {JSON.stringify(f.best_params)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function MonteCarloResult({ result }: { result: Record<string, unknown> }) {
  const cis =
    (result.confidence_intervals as Array<Record<string, number>>) ?? [];
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Card
          title="Observed Sharpe"
          value={(result.observed_sharpe as number)?.toFixed(4) ?? "—"}
          positive={(result.observed_sharpe as number) > 0}
        />
        <Card
          title="Simulated Sharpe"
          value={`${(result.sharpe_mean as number)?.toFixed(4)} ± ${(result.sharpe_std as number)?.toFixed(4)}`}
        />
        <Card
          title="P(Sharpe > 0)"
          value={`${((result.prob_positive_sharpe as number) * 100)?.toFixed(1)}%`}
          positive={(result.prob_positive_sharpe as number) > 0.5}
        />
        <Card
          title="P(Sharpe > 1)"
          value={`${((result.prob_sharpe_above_1 as number) * 100)?.toFixed(1)}%`}
          positive={(result.prob_sharpe_above_1 as number) > 0.3}
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Card
          title="Observed Return"
          value={`${((result.observed_return as number) * 100)?.toFixed(4)}%`}
          positive={(result.observed_return as number) > 0}
        />
        <Card
          title="Observed Max DD"
          value={`${((result.observed_max_drawdown as number) * 100)?.toFixed(4)}%`}
          positive={false}
        />
      </div>
      {cis.length > 0 && (
        <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
          <h4 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
            Sharpe Confidence Intervals
          </h4>
          <div className="flex gap-4">
            {cis.map((ci) => (
              <div key={ci.level} className="text-center">
                <div className="text-xs text-gray-400">
                  {(ci.level * 100).toFixed(0)}%
                </div>
                <div className="text-sm text-gray-200 font-mono">
                  {ci.value?.toFixed(4)}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function CostSweepResult({ result }: { result: Record<string, unknown> }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <Card title="Scenarios" value={(result.num_scenarios as number) ?? 0} />
        <Card
          title="Best Sharpe"
          value={(result.best_sharpe as number)?.toFixed(4) ?? "—"}
          positive={(result.best_sharpe as number) > 0}
          subtitle={`Fee ${((result.best_fee_rate as number) * 100)?.toFixed(2)}% / ${(result.best_slippage_bps as number)?.toFixed(1)} bps`}
        />
        <Card
          title="Worst Sharpe"
          value={(result.worst_sharpe as number)?.toFixed(4) ?? "—"}
          positive={(result.worst_sharpe as number) > 0}
          subtitle={`Fee ${((result.worst_fee_rate as number) * 100)?.toFixed(2)}% / ${(result.worst_slippage_bps as number)?.toFixed(1)} bps`}
        />
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Card
          title="Breakeven Fee"
          value={`${((result.breakeven_fee as number) * 100)?.toFixed(2)}%`}
        />
        <Card
          title="Breakeven Slippage"
          value={`${(result.breakeven_slippage_bps as number)?.toFixed(1)} bps`}
        />
        <Card
          title="dSharpe / dFee"
          value={(result.sensitivity_to_fees as number)?.toFixed(2) ?? "—"}
        />
        <Card
          title="dSharpe / dSlip"
          value={(result.sensitivity_to_slippage as number)?.toFixed(4) ?? "—"}
        />
      </div>
    </div>
  );
}

function ValidateResult({ result }: { result: Record<string, unknown> }) {
  const flags = (result.flags as Array<Record<string, string>>) ?? [];
  const gradeColors: Record<string, string> = {
    STRONG: "text-emerald-400",
    MODERATE: "text-yellow-400",
    WEAK: "text-orange-400",
    FAIL: "text-red-400",
  };
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
          <div className="text-xs text-gray-400 uppercase tracking-wide mb-1">
            Grade
          </div>
          <div
            className={`text-2xl font-bold ${gradeColors[result.grade as string] ?? "text-white"}`}
          >
            {result.grade as string}
          </div>
        </div>
        <Card
          title="OOS Sharpe"
          value={(result.mean_oos_sharpe as number)?.toFixed(4) ?? "—"}
          positive={(result.mean_oos_sharpe as number) > 0}
        />
        <Card
          title="Overfitting Ratio"
          value={`${(result.overfitting_ratio as number)?.toFixed(2)}x`}
          positive={(result.overfitting_ratio as number) < 2}
        />
      </div>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <Card
          title="P(Sharpe > 0)"
          value={`${((result.prob_positive_sharpe as number) * 100)?.toFixed(1)}%`}
          positive={(result.prob_positive_sharpe as number) > 0.5}
        />
        <Card
          title="Max Profitable Fee"
          value={`${((result.max_profitable_fee as number) * 100)?.toFixed(2)}%`}
        />
        <Card
          title="Max Profitable Slip"
          value={`${(result.max_profitable_slippage_bps as number)?.toFixed(1)} bps`}
        />
      </div>
      {result.summary ? (
        <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
          <p className="text-sm text-gray-300">{String(result.summary)}</p>
        </div>
      ) : null}
      {flags.length > 0 && (
        <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
          <h4 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
            Validation Flags
          </h4>
          <div className="space-y-1">
            {flags.map((f, i) => {
              const icon =
                f.severity === "critical"
                  ? "!!"
                  : f.severity === "warning"
                    ? "!"
                    : " ";
              const color =
                f.severity === "critical"
                  ? "text-red-400"
                  : f.severity === "warning"
                    ? "text-yellow-400"
                    : "text-gray-400";
              return (
                <div key={i} className={`text-sm font-mono ${color}`}>
                  <span className="inline-block w-6 text-center">{icon}</span>
                  <span className="text-gray-500">[{f.category}]</span>{" "}
                  {f.message}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function RunAllResult({ result }: { result: Record<string, unknown> }) {
  const sections: { key: string; label: string; type: string }[] = [
    { key: "sensitivity", label: "Param Sensitivity", type: "sensitivity" },
    { key: "walk_forward", label: "Walk-Forward", type: "walk_forward" },
    { key: "monte_carlo", label: "Monte Carlo", type: "monte_carlo" },
    { key: "cost_sweep", label: "Cost Sweep", type: "cost_sweep" },
    { key: "validate", label: "Full Validation", type: "validate" },
  ];
  return (
    <div className="space-y-6">
      {sections.map((s) => {
        const data = result[s.key] as Record<string, unknown> | undefined;
        if (!data) return null;
        return (
          <div key={s.key}>
            <h4 className="text-xs text-gray-400 uppercase tracking-wide mb-3 border-b border-gray-800 pb-1">
              {s.label}
            </h4>
            <ResultDisplay analysisType={s.type} result={data} />
          </div>
        );
      })}
    </div>
  );
}

function ResultDisplay({
  analysisType,
  result,
}: {
  analysisType: string;
  result: Record<string, unknown>;
}) {
  switch (analysisType) {
    case "sensitivity":
      return <SensitivityResult result={result} />;
    case "walk_forward":
      return <WalkForwardResult result={result} />;
    case "monte_carlo":
      return <MonteCarloResult result={result} />;
    case "cost_sweep":
      return <CostSweepResult result={result} />;
    case "validate":
      return <ValidateResult result={result} />;
    case "run_all":
      return <RunAllResult result={result} />;
    default:
      return (
        <pre className="text-sm text-gray-300 font-mono">
          {JSON.stringify(result, null, 2)}
        </pre>
      );
  }
}

// ---------------------------------------------------------------------------
// Main Analysis Tab
// ---------------------------------------------------------------------------

export function AnalysisTab({ symbol: _symbol }: { symbol?: string }) {
  const [jobs, setJobs] = useState<AnalysisJobSummary[]>([]);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [viewingJobId, setViewingJobId] = useState<string | null>(null);
  const [activeResult, setActiveResult] = useState<AnalysisJobResult | null>(
    null,
  );
  const [submitting, setSubmitting] = useState(false);
  const [strategy, setStrategy] = useState("mean_reversion");
  const [numTrades, setNumTrades] = useState(1000);
  const [dataSource, setDataSource] = useState<DataSource>("generated");
  const [backtests, setBacktests] = useState<BacktestRun[]>([]);
  const [selectedBacktest, setSelectedBacktest] = useState<string>("");

  // Poll job list
  const refreshJobs = useCallback(async () => {
    try {
      const data = await api.listJobs(20);
      setJobs(data.jobs);
    } catch {
      /* silent */
    }
  }, []);

  useEffect(() => {
    refreshJobs();
    const id = setInterval(refreshJobs, 3000);
    return () => clearInterval(id);
  }, [refreshJobs]);

  // Fetch available historical backtest runs
  useEffect(() => {
    if (dataSource !== "historical") return;
    api
      .listBacktests()
      .then((data) => setBacktests(data.backtests))
      .catch(() => setBacktests([]));
  }, [dataSource]);

  // Poll active job status
  useEffect(() => {
    if (!activeJobId) return;

    const poll = async () => {
      try {
        const status = await api.getJobStatus(activeJobId);
        // Update in jobs list
        setJobs((prev) =>
          prev.map((j) =>
            j.job_id === activeJobId
              ? { ...j, status: status.status, progress: status.progress }
              : j,
          ),
        );
        if (status.status === "completed") {
          const res = await api.getJobResult(activeJobId);
          setActiveResult(res);
          setViewingJobId(activeJobId);
          setActiveJobId(null);
        } else if (status.status === "failed") {
          setActiveJobId(null);
          refreshJobs();
        }
      } catch {
        /* silent */
      }
    };

    poll();
    const id = setInterval(poll, 1500);
    return () => clearInterval(id);
  }, [activeJobId, refreshJobs]);

  const handleSubmit = async (analysisType: AnalysisType) => {
    setSubmitting(true);
    setActiveResult(null);
    setViewingJobId(null);
    try {
      const params: Record<string, unknown> = {
        strategy,
        symbol: "BTCUSD",
        data_source: dataSource,
      };
      if (dataSource === "historical") {
        params.backtest_id = selectedBacktest;
      } else {
        params.num_trades = numTrades;
      }
      const res = await api.submitAnalysis(analysisType, params);
      setActiveJobId(res.job_id);
      refreshJobs();
    } catch (e) {
      console.error("Failed to submit:", e);
    } finally {
      setSubmitting(false);
    }
  };

  const handleViewResult = async (jobId: string) => {
    try {
      const res = await api.getJobResult(jobId);
      setActiveResult(res);
      setViewingJobId(jobId);
    } catch {
      /* silent */
    }
  };

  return (
    <div className="space-y-6">
      {/* Config bar */}
      <div className="flex flex-wrap items-center gap-4 bg-gray-900 rounded-lg p-4 border border-gray-800">
        <div>
          <label className="text-xs text-gray-400 block mb-1">
            Data Source
          </label>
          <div className="flex rounded-md overflow-hidden border border-gray-700">
            <button
              onClick={() => setDataSource("generated")}
              className={`px-3 py-1.5 text-sm transition-colors ${
                dataSource === "generated"
                  ? "bg-blue-600 text-white"
                  : "bg-gray-800 text-gray-400 hover:text-gray-200"
              }`}
            >
              Generated
            </button>
            <button
              onClick={() => setDataSource("historical")}
              className={`px-3 py-1.5 text-sm transition-colors ${
                dataSource === "historical"
                  ? "bg-blue-600 text-white"
                  : "bg-gray-800 text-gray-400 hover:text-gray-200"
              }`}
            >
              Historical
            </button>
          </div>
        </div>
        <div>
          <label className="text-xs text-gray-400 block mb-1">Strategy</label>
          <select
            value={strategy}
            onChange={(e) => setStrategy(e.target.value)}
            className="px-2 py-1.5 text-sm bg-gray-800 border border-gray-700 rounded-md text-gray-200 focus:outline-none focus:border-blue-500"
          >
            <option value="mean_reversion">Mean Reversion</option>
            <option value="pairs_trading">Pairs Trading</option>
          </select>
        </div>
        {dataSource === "generated" ? (
          <div>
            <label className="text-xs text-gray-400 block mb-1">Trades</label>
            <input
              type="number"
              value={numTrades}
              onChange={(e) => setNumTrades(Number(e.target.value))}
              min={100}
              max={10000}
              step={100}
              className="w-24 px-2 py-1.5 text-sm bg-gray-800 border border-gray-700 rounded-md text-gray-200 focus:outline-none focus:border-blue-500"
            />
          </div>
        ) : (
          <div className="flex-1 min-w-[200px]">
            <label className="text-xs text-gray-400 block mb-1">
              Backtest Run
            </label>
            {backtests.length > 0 ? (
              <select
                value={selectedBacktest}
                onChange={(e) => setSelectedBacktest(e.target.value)}
                className="w-full px-2 py-1.5 text-sm bg-gray-800 border border-gray-700 rounded-md text-gray-200 focus:outline-none focus:border-blue-500"
              >
                <option value="">Select a backtest run...</option>
                {backtests.map((bt) => (
                  <option key={bt.backtest_id} value={bt.backtest_id}>
                    {bt.backtest_id} — {bt.symbol} ({bt.trades_replayed} trades)
                    {bt.has_trades ? "" : " [no trade data]"}
                  </option>
                ))}
              </select>
            ) : (
              <div className="text-sm text-gray-500 py-1.5">
                No historical backtests found
              </div>
            )}
          </div>
        )}
      </div>

      {/* Analysis buttons */}
      <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-6 gap-3">
        {ANALYSES.map((a) => (
          <button
            key={a.type}
            onClick={() => handleSubmit(a.type)}
            disabled={
              submitting ||
              !!activeJobId ||
              (dataSource === "historical" && !selectedBacktest)
            }
            className="bg-gray-900 hover:bg-gray-800 border border-gray-700 hover:border-blue-600 rounded-lg p-4 text-left transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <div className="text-sm font-semibold text-blue-400 mb-1">
              {a.label}
            </div>
            <div className="text-xs text-gray-400">{a.description}</div>
          </button>
        ))}
      </div>

      {/* Active job progress */}
      {activeJobId && (
        <div className="bg-gray-900 rounded-lg p-4 border border-blue-800">
          <div className="flex items-center gap-3">
            <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
            <span className="text-sm text-gray-200">Running analysis...</span>
            <StatusBadge status="running" />
          </div>
          <ProgressBar
            progress={jobs.find((j) => j.job_id === activeJobId)?.progress ?? 0}
          />
        </div>
      )}

      {/* Result display */}
      {activeResult?.result && (
        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wide">
            Results —{" "}
            {ANALYSES.find((a) => a.type === activeResult.analysis_type)
              ?.label ?? activeResult.analysis_type}
          </h3>
          <ResultDisplay
            analysisType={activeResult.analysis_type}
            result={activeResult.result as Record<string, unknown>}
          />
        </div>
      )}

      {/* Job history */}
      {jobs.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
            Recent Jobs
          </h3>
          <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-400 text-xs uppercase bg-gray-950">
                  <th className="text-left py-2 px-3">Type</th>
                  <th className="text-left py-2 px-3">Status</th>
                  <th className="text-left py-2 px-3">Progress</th>
                  <th className="text-left py-2 px-3">Action</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((j) => {
                  const isViewing = viewingJobId === j.job_id;
                  return (
                    <tr
                      key={j.job_id}
                      className={`border-t border-gray-800 cursor-pointer transition-colors ${isViewing ? "bg-blue-900/30 border-l-2 border-l-blue-500" : "hover:bg-gray-800/50"}`}
                      onClick={() =>
                        j.status === "completed" && handleViewResult(j.job_id)
                      }
                    >
                      <td className="py-2 px-3 text-gray-200">
                        {ANALYSES.find((a) => a.type === j.analysis_type)
                          ?.label ?? j.analysis_type}
                      </td>
                      <td className="py-2 px-3">
                        <StatusBadge status={j.status} />
                      </td>
                      <td className="py-2 px-3 w-32">
                        <ProgressBar progress={j.progress} />
                      </td>
                      <td className="py-2 px-3">
                        {j.status === "completed" && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleViewResult(j.job_id);
                            }}
                            className={`text-xs px-2 py-0.5 rounded ${isViewing ? "bg-blue-600 text-white" : "text-blue-400 hover:text-blue-300 hover:bg-gray-700"}`}
                          >
                            {isViewing ? "Viewing" : "View"}
                          </button>
                        )}
                        {j.status === "failed" && (
                          <span
                            className="text-xs text-red-400"
                            title={j.error ?? ""}
                          >
                            Failed
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
