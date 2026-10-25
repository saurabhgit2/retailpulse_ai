import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';

import { EMPTY, fromSearchParams, toQuery, toSearchParams } from './filterState.js';

/**
 * Filters that live in the URL.
 *
 * Same reasoning as the dataset id in the path (frontend guide §7): the
 * address bar is the single source of truth, so reload, the back button and
 * a link pasted to a supervisor all reproduce the same view. Holding this in
 * `useState` would make the back button leave the charts where they were and
 * quietly break every shared link.
 *
 * `replace: true` on a change keeps the browser history usable — dragging a
 * date would otherwise push twenty entries and the back button would take
 * twenty presses to leave the page.
 */
export function useFilters(bounds) {
  const [params, setParams] = useSearchParams();

  const filters = useMemo(() => fromSearchParams(params), [params]);

  const update = useCallback(
    (patch) => {
      setParams(
        (current) => {
          const next = { ...fromSearchParams(current), ...patch };
          // Choosing an explicit date means the reader wants that range, not
          // the preset they had before.
          if (('from' in patch || 'to' in patch) && !('preset' in patch)) {
            next.preset = 'custom';
          }
          // Leaving a custom range behind should not keep its dates in the URL.
          if (patch.preset && patch.preset !== 'custom') {
            next.from = '';
            next.to = '';
          }
          return toSearchParams(next);
        },
        { replace: true },
      );
    },
    [setParams],
  );

  const reset = useCallback(() => setParams({}, { replace: true }), [setParams]);

  const query = useMemo(() => toQuery(filters, bounds), [filters, bounds]);

  const isDefault = useMemo(
    () => Object.keys(toSearchParams(filters)).length === 0,
    [filters],
  );

  return { filters, update, reset, query, isDefault, defaults: EMPTY };
}
