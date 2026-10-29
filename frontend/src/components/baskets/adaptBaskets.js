/**
 * The basket-size response, turned into what the Baskets page draws.
 *
 * This endpoint is unusual among the analytics endpoints in that it has
 * already done the binning: each field arrives with a linear histogram, a log
 * histogram, percentiles, a summary and Tukey fences. So there is no
 * arithmetic here, only presentation decisions, and the functions below are
 * where those decisions are written down rather than buried in JSX.
 *
 * The decisions that matter:
 *
 * - which histogram to show first, which is a question about the data and is
 *   answered from the data (`strongly_skewed`), not by preference;
 * - how to label a bin, given edges that carry floating-point noise;
 * - and how to report the bins a histogram loses, instead of quietly
 *   drawing 39,528 of 39,529 invoices and calling it the distribution.
 */

const num = (value) => (typeof value === 'number' && Number.isFinite(value) ? value : null);

/** Fields the endpoint reports a distribution for, in the order shown. */
export const BASKET_FIELDS = [
  {
    key: 'distinct_items_per_invoice',
    label: 'Distinct items per invoice',
    short: 'Distinct items',
    currency: null,
    unit: 'items',
    // Whole-number valued. This is what licenses the explanation the page
    // gives for empty bins on a log axis, and it is false for order value,
    // so it is recorded per field rather than assumed for both.
    integer: true,
  },
  {
    key: 'order_value',
    label: 'Order value',
    short: 'Order value',
    currency: '£',
    unit: 'value',
    integer: false,
  },
];

/** Top-level figures and the endpoint's own interpretation. */
export function adaptBaskets(payload) {
  const d = payload ?? {};
  return {
    available: d.available !== false,
    invoices: num(d.invoices),
    interpretation: typeof d.interpretation === 'string' ? d.interpretation : null,
  };
}

/**
 * An edge, as text.
 *
 * Precision falls as magnitude rises, because an axis tick reading "1,107.00"
 * is three characters of noise, and one reading "0" where the value is 0.19
 * is wrong. Two significant decimals below ten, one below a hundred, none
 * above.
 */
export function edgeText(value, currency = null) {
  const v = num(value);
  if (v === null) return '—';
  const abs = Math.abs(v);
  const decimals = abs >= 100 ? 0 : abs >= 10 ? 1 : 2;
  return `${currency ?? ''}${v.toLocaleString('en-NZ', {
    maximumFractionDigits: decimals,
  })}`;
}

/**
 * A histogram, as chart bins.
 *
 * `label` is the interval, which is what a tooltip and a table row should
 * say. `axis` is the lower edge alone, because a histogram axis is a number
 * line: printing both edges on every tick repeats the next tick's value.
 */
export function histogramBins(histogram, { currency = null } = {}) {
  const edges = Array.isArray(histogram?.edges) ? histogram.edges : [];
  const counts = Array.isArray(histogram?.counts) ? histogram.counts : [];
  const bins = counts.map((count, i) => {
    const lo = num(edges[i]);
    const hi = num(edges[i + 1]);
    return {
      key: `b${i}`,
      lo,
      hi,
      value: num(count) ?? 0,
      axis: edgeText(lo, currency),
      label: `${edgeText(lo, currency)} to ${edgeText(hi, currency)}`,
    };
  });
  return {
    bins,
    logScale: Boolean(histogram?.log_scale),
    excludedNonPositive: num(histogram?.excluded_non_positive) ?? 0,
  };
}

/**
 * Empty bins that sit *inside* the distribution.
 *
 * A run of zeros past the last populated bin is an empty tail, which is
 * ordinary. A zero between two populated bins is not, and on a log axis over
 * an integer variable it is an artefact: bins narrower than one whole item
 * cannot contain an observation, so they come back empty no matter what the
 * data does. Naming the count lets the page say so rather than leaving a
 * reader to invent a reason for the gaps.
 */
export function interiorGaps(bins) {
  let last = -1;
  bins.forEach((b, i) => {
    if (b.value > 0) last = i;
  });
  if (last < 0) return 0;
  return bins.filter((b, i) => i < last && b.value === 0).length;
}

/**
 * How many observations a histogram actually accounts for.
 *
 * Not a formality. The order-value log histogram here plots 39,528 of 39,529
 * invoices: the largest value sits exactly on the top edge, and in floating
 * point it lands a hair outside it. One missing invoice changes nothing, but
 * a histogram that silently drops observations is the kind of thing that
 * should be visible, so the page reports it when it happens.
 */
export function histogramCoverage(bins, count) {
  const plotted = bins.reduce((sum, b) => sum + b.value, 0);
  const total = num(count);
  return { plotted, total, missing: total === null ? null : total - plotted };
}

/** Percentiles as ordered rows. The response keys them by string. */
export function percentileRows(percentiles) {
  if (!percentiles || typeof percentiles !== 'object') return [];
  return Object.entries(percentiles)
    .map(([key, value]) => ({ key, p: Number(key), value: num(value) }))
    .filter((row) => Number.isFinite(row.p))
    .sort((a, b) => a.p - b.p);
}

/**
 * One field's distribution, with both histograms prepared.
 *
 * `defaultScale` is taken from the endpoint's own `strongly_skewed` flag
 * rather than chosen here. On this dataset the linear histogram of order
 * value puts 99.1% of invoices in its first bar, which is not a picture of a
 * distribution, it is a picture of a scale being wrong. But that is a fact
 * about this data, and a page that hard-codes "always log" would be making
 * the same mistake in the opposite direction on a dataset that is not skewed.
 */
export function adaptField(payload, fieldKey) {
  const meta = BASKET_FIELDS.find((f) => f.key === fieldKey) ?? {
    key: fieldKey,
    label: fieldKey,
    short: fieldKey,
    currency: null,
  };
  const d = payload?.[fieldKey];
  if (!d) return null;

  const linear = histogramBins(d.histogram, { currency: meta.currency });
  const log = histogramBins(d.histogram_log, { currency: meta.currency });
  const count = num(d.count);

  return {
    ...meta,
    count,
    summary: d.summary ?? {},
    percentiles: percentileRows(d.percentiles),
    outliers: d.outliers ?? {},
    stronglySkewed: Boolean(d.summary?.strongly_skewed),
    defaultScale: d.summary?.strongly_skewed ? 'log' : 'linear',
    histograms: {
      linear: { ...linear, gaps: interiorGaps(linear.bins), coverage: histogramCoverage(linear.bins, count) },
      log: { ...log, gaps: interiorGaps(log.bins), coverage: histogramCoverage(log.bins, count) },
    },
  };
}

/**
 * The share of observations the tallest bar holds.
 *
 * This is the number that justifies a log axis, and quoting it is more
 * honest than asserting that the linear view is unreadable: it lets the
 * reader check the claim against the chart in front of them.
 */
export function dominantBinShare(bins) {
  const total = bins.reduce((sum, b) => sum + b.value, 0);
  if (!total) return null;
  return Math.max(...bins.map((b) => b.value)) / total;
}

/** Where this response came from, and what it cost. */
export function cacheNote(payload) {
  const cache = payload?._cache;
  if (!cache) return null;
  const ms = num(cache.computed_ms);
  const seconds = ms === null ? null : (ms / 1000).toFixed(1);
  if (cache.hit) {
    return seconds
      ? `Served from cache, originally computed in ${seconds}s.`
      : 'Served from cache.';
  }
  return seconds ? `Computed for this request in ${seconds}s.` : null;
}
