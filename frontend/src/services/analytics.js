import { api } from './apiClient.js';

/**
 * The Phase 4 analytics endpoints, as an index of the backend.
 *
 * Same shape as `datasets.js`: one exported function per endpoint, no logic.
 * Pages never call `fetch` and never build a path.
 *
 * ──────────────────────────────────────────────────────────────────────────
 * If anything here 404s, this file is where to fix it, and it is a one-line
 * fix per endpoint. Check the paths against http://localhost:8000/docs; the
 * two spellings worth confirming are `series-profile` and `filter-options`.
 * ──────────────────────────────────────────────────────────────────────────
 */

const base = (datasetId) => `/datasets/${encodeURIComponent(datasetId)}`;

/** Date bounds, regions, categories and top products for the filter bar. */
export function getFilterOptions(datasetId, { signal } = {}) {
  return api.get(`${base(datasetId)}/filter-options`, { signal });
}

/** Headline figures. Any KPI without a source column comes back null. */
export function getKpis(datasetId, { query, signal } = {}) {
  return api.get(`${base(datasetId)}/analytics/kpis`, { query, signal });
}

/** Revenue and orders over time, with partial-period flags. */
export function getTrends(datasetId, { query, signal } = {}) {
  return api.get(`${base(datasetId)}/analytics/trends`, { query, signal });
}

/** Ranked products, regions or categories with Pareto shares. */
export function getBreakdowns(datasetId, { query, signal } = {}) {
  return api.get(`${base(datasetId)}/analytics/breakdowns`, { query, signal });
}

export function getSeasonality(datasetId, { query, signal } = {}) {
  return api.get(`${base(datasetId)}/analytics/seasonality`, { query, signal });
}

export function getDistributions(datasetId, { query, signal } = {}) {
  return api.get(`${base(datasetId)}/analytics/distributions`, { query, signal });
}

export function getAnomalies(datasetId, { query, signal } = {}) {
  return api.get(`${base(datasetId)}/analytics/anomalies`, { query, signal });
}

export function getRfm(datasetId, { query, signal } = {}) {
  return api.get(`${base(datasetId)}/analytics/rfm`, { query, signal });
}

export function getBasketSizes(datasetId, { query, signal } = {}) {
  return api.get(`${base(datasetId)}/analytics/baskets`, { query, signal });
}
