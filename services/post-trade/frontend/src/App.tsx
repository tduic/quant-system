import { useState, useEffect } from 'react';
import type { TabId } from './types';
import { api } from './api';
import { PnLTab } from './tabs/PnLTab';
import { TCATab } from './tabs/TCATab';
import { AlphaDecayTab } from './tabs/AlphaDecayTab';
import { RiskMetricsTab } from './tabs/RiskMetricsTab';
import { DrawdownTab } from './tabs/DrawdownTab';
import { FillsTab } from './tabs/FillsTab';

const TABS: { id: TabId; label: string }[] = [
  { id: 'pnl', label: 'P&L' },
  { id: 'tca', label: 'TCA' },
  { id: 'alpha-decay', label: 'Alpha Decay' },
  { id: 'risk-metrics', label: 'Risk Metrics' },
  { id: 'drawdown', label: 'Drawdown' },
  { id: 'fills', label: 'Fills' },
];

const TAB_COMPONENTS: Record<TabId, React.FC<{ symbol?: string }>> = {
  pnl: PnLTab,
  tca: TCATab,
  'alpha-decay': AlphaDecayTab,
  'risk-metrics': RiskMetricsTab,
  drawdown: DrawdownTab,
  fills: FillsTab,
};

export default function App() {
  const [activeTab, setActiveTab] = useState<TabId>('pnl');
  const [selectedSymbol, setSelectedSymbol] = useState<string>('');
  const [symbols, setSymbols] = useState<string[]>([]);
  const ActiveComponent = TAB_COMPONENTS[activeTab];

  useEffect(() => {
    const fetchSymbols = async () => {
      try {
        const data = await api.getSymbols();
        setSymbols(data.symbols);
      } catch {
        // silently retry on next interval
      }
    };
    fetchSymbols();
    const interval = setInterval(fetchSymbols, 10_000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      <header className="border-b border-gray-800 bg-gray-950/80 backdrop-blur sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
          <h1 className="text-lg font-bold tracking-tight">
            <span className="text-blue-400">Quant</span> Post-Trade Dashboard
          </h1>
          <div className="flex items-center gap-3">
            <select
              value={selectedSymbol}
              onChange={(e) => setSelectedSymbol(e.target.value)}
              className="px-2 py-1.5 text-sm bg-gray-800 border border-gray-700 rounded-md text-gray-200 focus:outline-none focus:border-blue-500"
            >
              <option value="">All Symbols</option>
              {symbols.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <button
              onClick={api.exportExcel}
              className="px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-500 rounded-md transition-colors font-medium"
            >
              Export Excel
            </button>
          </div>
        </div>

        <nav className="max-w-7xl mx-auto px-4 flex gap-1 -mb-px">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab.id
                  ? 'border-blue-500 text-blue-400'
                  : 'border-transparent text-gray-400 hover:text-gray-200 hover:border-gray-600'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </header>

      <main className="max-w-7xl mx-auto px-4 py-6">
        <ActiveComponent symbol={selectedSymbol || undefined} />
      </main>
    </div>
  );
}
