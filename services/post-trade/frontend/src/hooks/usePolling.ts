import { useState, useEffect, useCallback } from 'react';

interface UsePollingResult<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  refresh: () => void;
}

export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs: number = 5000,
): UsePollingResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(() => {
    fetcher()
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [fetcher]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, intervalMs);
    return () => clearInterval(id);
  }, [refresh, intervalMs]);

  return { data, error, loading, refresh };
}
