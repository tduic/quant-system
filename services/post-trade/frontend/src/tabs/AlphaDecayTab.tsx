import { api } from '../api';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { usePolling } from '../hooks/usePolling';

export function AlphaDecayTab() {
  const { data, loading, error } = usePolling(api.getAlphaDecay, 10000);

  if (loading) return <LoadingSpinner />;
  if (error) return <div className="text-red-400 p-4">Error: {error}</div>;
  if (!data) return null;

  return (
    <div className="flex items-center justify-center py-16">
      <div className="text-center max-w-md">
        <div className="text-4xl mb-4">📊</div>
        <h3 className="text-lg font-semibold text-gray-200 mb-2">Alpha Decay Analysis</h3>
        <p className="text-gray-400 text-sm leading-relaxed">
          {data.description}
        </p>
        <div className="mt-4 inline-block px-3 py-1 bg-gray-800 rounded-full text-xs text-gray-400">
          Status: {data.status}
        </div>
      </div>
    </div>
  );
}
