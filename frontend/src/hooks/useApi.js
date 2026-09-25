import { useCallback, useEffect, useState } from 'react';

/**
 * Load data when a component appears, and again whenever `fetcher` changes.
 *
 * Usage:
 *   const load = useCallback((signal) => getDataset(id, { signal }), [id]);
 *   const { data, error, loading, reload } = useApi(load);
 *
 * Why `fetcher` must be wrapped in useCallback: a function written inside a
 * component is a *new* function on every render. If we used it directly as an
 * effect dependency, the effect would re-run (and re-fetch) on every render.
 * useCallback returns the same function until its own dependencies (here `id`)
 * change.
 *
 * Why the AbortController: if the component disappears, or `id` changes before
 * the response arrives, the old request is cancelled so a slow, out-of-date
 * response can never overwrite newer data. The cleanup function also makes
 * React StrictMode's double-run in development harmless.
 */
export function useApi(fetcher, { enabled = true } = {}) {
  const [state, setState] = useState({ data: null, error: null, loading: enabled });
  const [reloadCount, setReloadCount] = useState(0);

  useEffect(() => {
    if (!enabled) return undefined;
    const controller = new AbortController();
    setState((previous) => ({ ...previous, loading: true, error: null }));

    fetcher(controller.signal)
      .then((data) => setState({ data, error: null, loading: false }))
      .catch((error) => {
        if (error?.name === 'AbortError') return; // we cancelled it ourselves
        setState({ data: null, error, loading: false });
      });

    return () => controller.abort();
  }, [fetcher, enabled, reloadCount]);

  const reload = useCallback(() => setReloadCount((n) => n + 1), []);
  return { ...state, reload };
}
