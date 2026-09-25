import { useCallback, useEffect, useRef, useState } from 'react';
import { POLL_INTERVAL_MS } from '../utils/constants';

/**
 * Call `fetcher` repeatedly until `isDone(result)` returns true.
 * Used to watch background jobs (dataset processing, forecast runs), which
 * return 202 Accepted and then change status on the server.
 *
 * It chains setTimeout calls instead of using setInterval: the next request is
 * only scheduled after the previous one has finished, so slow responses can
 * never pile up.
 */
export function usePolling(fetcher, { isDone, intervalMs = POLL_INTERVAL_MS, enabled = true }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [attempt, setAttempt] = useState(0);

  // Keep the latest isDone in a ref so callers can pass an inline function
  // without restarting the polling loop on every render.
  const isDoneRef = useRef(isDone);
  useEffect(() => {
    isDoneRef.current = isDone;
  }, [isDone]);

  useEffect(() => {
    if (!enabled) return undefined;
    const controller = new AbortController();
    let timer = null;
    let stopped = false;

    async function tick() {
      try {
        const result = await fetcher(controller.signal);
        if (stopped) return;
        setData(result);
        if (!isDoneRef.current(result)) timer = setTimeout(tick, intervalMs);
      } catch (err) {
        if (stopped || err?.name === 'AbortError') return;
        setError(err); // stop polling; the caller can offer "Try again"
      }
    }

    setError(null);
    tick();

    // Cleanup runs on unmount or when inputs change: stop everything.
    return () => {
      stopped = true;
      controller.abort();
      clearTimeout(timer);
    };
  }, [fetcher, intervalMs, enabled, attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return { data, error, retry };
}
