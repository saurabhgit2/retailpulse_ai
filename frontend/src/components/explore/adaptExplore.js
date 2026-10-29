/**
 * The seasonality and distribution responses, turned into what Explore draws.
 *
 * The histogram half of this page reuses `../shared/histogramShape.js`,
 * because `/analytics/distributions` returns the same block as each field of
 * `/analytics/baskets`. What is new here is the calendar profile and the
 * decomposition.
 *
 * The decomposition needs a judgement rather than a transformation, and it is
 * made here so the page cannot quietly stop making it. `statsmodels` will
 * return a seasonal component for any series long enough to admit one, and it
 * says nothing about whether that component means anything. On two cycles of
 * weekly data it does not, and `decompositionDiagnostics` works out how badly
 * from the response itself rather than taking the endpoint's word for it.
 */

import { distributionShape } from '../shared/histogramShape.js';

const num = (value) => (typeof value === 'number' && Number.isFinite(value) ? value : null);

/** The calendar profiles the endpoint reports, in the order shown. */
export const CALENDAR_DIMENSIONS = [
  { key: 'day_of_week', label: 'Day of week', short: 'day' },
  { key: 'month', label: 'Month of year', short: 'month' },
  { key: 'hour', label: 'Hour of day', short: 'hour' },
];

/**
 * An hour bucket as a clock time.
 *
 * The endpoint labels them "6.0", "7.0" and so on, which is the float that
 * came out of the grouping rather than a time anyone reads. Months and days
 * already arrive named, so only hours are rewritten.
 */
export function bucketLabel(dimension, bucket, fallback) {
  if (dimension !== 'hour') return fallback ?? String(bucket);
  const hour = num(bucket);
  if (hour === null) return fallback ?? '—';
  return `${String(Math.trunc(hour)).padStart(2, '0')}:00`;
}

/**
 * One calendar profile.
 *
 * `value` is the seasonal index: 1.0 is an average period, so the chart gets
 * a reference line there and the reader needs no legend to know which way is
 * up.
 *
 * Buckets the endpoint marks unreliable are kept rather than dropped. A
 * Saturday built from seven observations is still a fact about this
 * retailer — they barely trade on Saturdays — and removing it would hide
 * that. It is named in the note and carries its observation count in the
 * table, which is where a reader can weigh it.
 */
export function adaptCalendar(payload, dimension) {
  const rows = payload?.calendar?.[dimension];
  if (!Array.isArray(rows)) return null;

  const bins = rows.map((row, i) => ({
    key: `${dimension}-${row.bucket ?? i}`,
    bucket: num(row.bucket),
    label: bucketLabel(dimension, row.bucket, row.label),
    value: num(row.index) ?? 0,
    mean: num(row.mean),
    total: num(row.total),
    observations: num(row.observations),
    reliable: row.reliable !== false,
  }));

  return {
    dimension,
    measure: payload?.calendar?.value ?? null,
    bins,
    unreliable: bins.filter((b) => !b.reliable),
    observations: bins.reduce((sum, b) => sum + (b.observations ?? 0), 0),
  };
}

/** The decomposition's series, as parallel arrays for the chart. */
export function decompositionSeries(payload) {
  const d = payload?.decomposition ?? {};
  const pick = (name) => (Array.isArray(d[name]) ? d[name].map(num) : []);
  return {
    x: Array.isArray(d.index) ? d.index : [],
    observed: pick('observed'),
    trend: pick('trend'),
    seasonal: pick('seasonal'),
    deseasonalised: pick('deseasonalised'),
    remainder: pick('remainder'),
  };
}

/**
 * What the decomposition is actually worth.
 *
 * Three figures, all computed from the response:
 *
 * `observationsPerPhase` — the centred moving average consumes half a period
 * at each end, so a series of 104 weekly points with a period of 52 yields 52
 * trend points, one per seasonal phase. The endpoint's note says each phase
 * rests on "about 2 observations"; the arithmetic says one.
 *
 * `remainderDegenerate` — if every residual is the same number, the seasonal
 * component absorbed the whole detrended series and nothing was left over.
 * A decomposition whose residual never varies has not separated anything, and
 * this is the clearest single statement of that.
 *
 * The comparison is made against the scale of the data rather than against a
 * fixed epsilon, because "the same number" in floating point over values near
 * half a million is not the same tolerance as over values near one.
 */
export function decompositionDiagnostics(payload) {
  const d = payload?.decomposition;
  if (!d || d.available === false) {
    return { available: false };
  }

  const series = decompositionSeries(payload);
  const trendPoints = series.trend.filter((v) => v !== null).length;
  const residuals = series.remainder.filter((v) => v !== null);
  const observed = series.observed.filter((v) => v !== null);

  const spread = residuals.length ? Math.max(...residuals) - Math.min(...residuals) : null;
  const range = observed.length ? Math.max(...observed) - Math.min(...observed) : 0;
  const tolerance = Math.max(1e-6, range * 1e-9);
  const period = num(d.period);

  return {
    available: true,
    period,
    model: d.model ?? null,
    method: d.method ?? null,
    cycles: num(d.cycles),
    weakEstimate: Boolean(d.weak_seasonal_estimate),
    note: d.seasonal_estimate_note ?? null,
    seasonalStrength: num(d.seasonal_strength),
    points: series.x.length,
    trendPoints,
    observationsPerPhase: period ? trendPoints / period : null,
    remainderSpread: spread,
    remainderDegenerate: residuals.length > 1 && spread !== null && spread <= tolerance,
  };
}

/** The per-line revenue distribution, reusing the shared histogram shape. */
export function adaptRevenueDistribution(payload) {
  if (!payload) return null;
  return distributionShape(payload, { currency: '£', integer: false });
}

export { cacheNote } from '../shared/provenance.js';
