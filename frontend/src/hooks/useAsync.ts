import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../lib/api";

export type AsyncState<T> = {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
};

/**
 * Minimal replacement for React Query — enough for this app's needs without
 * pulling in another dependency. Tracks the three states the UI actually
 * has to show honestly: loading, failed (with the real message), and loaded.
 */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fn()
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        // A 404 on a not-yet-generated resource (no report yet, no detection
        // yet) is a normal empty state, not an error worth alarming about —
        // callers distinguish via `data === null && !error`.
        if (e instanceof ApiError && e.status === 404) {
          setData(null);
        } else {
          setError(e instanceof Error ? e.message : "Something went wrong.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  return { data, loading, error, reload };
}
