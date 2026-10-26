import { api } from './apiClient.js';

/**
 * The Phase 4 analytics endpoints, as an index of the backend.
 *
 * Paths and parameter names taken from the server's own OpenAPI document,
 * not from the design notes. Two things the schema corrected:
 *
 * - there is no `breakdowns` endpoint. Products, regions and categories are
 *   three separate endpoints with their own parameters, which is the better
 *   design anyway: `categories` answers 409 when the dataset has no category
 *   column, and a single endpoint behind a `dimension` parameter could not.
 * - the filters are plural and repeatable (`regions`, `categories`,
 *   `product_codes`), not single values.
 *
 * Every analytics endpoint takes the same filter block, so it is declared
 * once below and spread into each call.
 */

const base = (datasetId) => `/datasets/${encodeURIComponent(datasetId)}`;

/**
 * Filters common to every analytics endpoint.
 *
 * `customer_type` and `include_returns` are passed through untouched when
 * the caller sets them; leaving them out lets the server apply its own
 * documented defaults ("all" and true) rather than this file restating them
 * and drifting if they change.
 */
export const FILTER_KEYS = [
  'date_from',
  'date_to',
  'regions',
  'categories',
  'product_codes',
  'customer_type',
  'include_returns',
];

/** Date bounds, regions, top products and categories for the filter bar. */
export function getFilterOptions(datasetId, { signal } = {}) {
  return api.get(`${base(datasetId)}/filter-options`, { signal });
}

/** Headline figures plus the comparable previous period. */
export function getKpis(datasetId, { query, signal } = {}) {
  return api.get(`${base(datasetId)}/analytics/kpis`, { query, signal });
}

/**
 * Revenue and orders over time.
 * `granularity` is one of day, week, month, year; `ma_window` sets the
 * moving-average span, 1 to 52.
 */
export function getTrends(datasetId, { query, signal } = {}) {
  return api.get(`${base(datasetId)}/analytics/trends`, { query, signal });
}

/**
 * Product performance, ranked.
 * `sort` is gross_revenue, net_revenue, units or orders; `order` is desc or
 * asc; `limit` is 1 to 200.
 */
export function getProducts(datasetId, { query, signal } = {}) {
  return api.get(`${base(datasetId)}/analytics/products`, { query, signal });
}

export function getRegions(datasetId, { query, signal } = {}) {
  return api.get(`${base(datasetId)}/analytics/regions`, { query, signal });
}

/** Answers 409 when the dataset carries no category column. */
export function getCategories(datasetId, { query, signal } = {}) {
  return api.get(`${base(datasetId)}/analytics/categories`, { query, signal });
}

/** Customer revenue concentration. */
export function getCustomers(datasetId, { query, signal } = {}) {
  return api.get(`${base(datasetId)}/analytics/customers`, { query, signal });
}

export function getRfm(datasetId, { query, signal } = {}) {
  return api.get(`${base(datasetId)}/analytics/rfm`, { query, signal });
}

export function getBasketSizes(datasetId, { query, signal } = {}) {
  return api.get(`${base(datasetId)}/analytics/baskets`, { query, signal });
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

export function getSeriesProfile(datasetId, { query, signal } = {}) {
  return api.get(`${base(datasetId)}/analytics/series-profile`, { query, signal });
}

export function getFeatures(datasetId, { query, signal } = {}) {
  return api.get(`${base(datasetId)}/analytics/features`, { query, signal });
}

export function getRelationships(datasetId, { query, signal } = {}) {
  return api.get(`${base(datasetId)}/analytics/relationships`, { query, signal });
}

export function getStatistics(datasetId, { query, signal } = {}) {
  return api.get(`${base(datasetId)}/analytics/statistics`, { query, signal });
}
