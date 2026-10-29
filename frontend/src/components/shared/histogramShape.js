/**
 * Presentation helpers for any endpoint that returns a binned distribution.
 *
 * Several analytics endpoints return the same block: a linear histogram, a
 * log histogram, percentiles, a summary and Tukey fences. `/analytics/baskets`
 * returns two of them and `/analytics/distributions` returns one, so these
 * functions live here rather than in either page's own adapter.
 *
 * There is no arithmetic here. The server did the binning; this decides how
 * a bin is labelled, and reports what a histogram loses.
 */

const num = (value) => (typeof value === 'number' && Number.isFinite(value) ? value : null);

/**
 * An edge, as text.
 *
 * Precision falls as magnitude rises, because an axis tick reading "1,107.00"
 * is three characters of noise, and one reading "0" where the value is 0.19
 * is wrong. Two decimals below ten, one below a hundred, none above.
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
 * an integer variable it is an artefact: bins narrower than one whole unit
 * cannot contain an observation, so they come back empty no matter what the
 * data does. Naming the count lets a page say so rather than leaving a reader
 * to invent a reason for the gaps.
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
 * Not a formality. A log histogram whose top edge equals the maximum loses
 * that observation to floating point. One row changes nothing, but a
 * histogram that silently drops observations should still say so.
 */
export function histogramCoverage(bins, count) {
  const plotted = bins.reduce((sum, b) => sum + b.value, 0);
  const total = num(count);
  return { plotted, total, missing: total === null ? null : total - plotted };
}

/** Percentiles as ordered rows. The responses key them by string. */
export function percentileRows(percentiles) {
  if (!percentiles || typeof percentiles !== 'object') return [];
  return Object.entries(percentiles)
    .map(([key, value]) => ({ key, p: Number(key), value: num(value) }))
    .filter((row) => Number.isFinite(row.p))
    .sort((a, b) => a.p - b.p);
}

/**
 * The share of observations the tallest bar holds.
 *
 * This is the number that justifies a log axis, and quoting it is more honest
 * than asserting that the linear view is unreadable: it lets a reader check
 * the claim against the chart in front of them.
 */
export function dominantBinShare(bins) {
  const total = bins.reduce((sum, b) => sum + b.value, 0);
  if (!total) return null;
  return Math.max(...bins.map((b) => b.value)) / total;
}

/**
 * A share, as a percentage that does not round itself into a lie.
 *
 * The revenue-per-line histogram puts 1,003,412 of 1,003,430 observations in
 * its first bar. At one decimal that reads "100.0%", which says every
 * observation is in one bar when eighteen are not. Where a share is short of
 * the whole but would print as the whole, the precision grows until the
 * difference survives.
 */
export function shareText(share, { decimals = 1 } = {}) {
  const value = num(share);
  if (value === null) return '—';
  let places = decimals;
  let text = (value * 100).toFixed(places);
  while (value < 1 && Number(text) >= 100 && places < 6) {
    places += 1;
    text = (value * 100).toFixed(places);
  }
  return `${text}%`;
}

/**
 * One distribution block, with both histograms prepared and the scale chosen.
 *
 * `defaultScale` comes from the endpoint's own `strongly_skewed` flag rather
 * than from preference. Hard-coding "always log" would be the same mistake in
 * the opposite direction on a dataset that is not skewed.
 */
export function distributionShape(block, { currency = null, integer = false } = {}) {
  if (!block) return null;
  const linear = histogramBins(block.histogram, { currency });
  const log = histogramBins(block.histogram_log, { currency });
  const count = num(block.count);

  return {
    field: block.field ?? null,
    count,
    currency,
    integer,
    summary: block.summary ?? {},
    percentiles: percentileRows(block.percentiles),
    outliers: block.outliers ?? {},
    stronglySkewed: Boolean(block.summary?.strongly_skewed),
    defaultScale: block.summary?.strongly_skewed ? 'log' : 'linear',
    histograms: {
      linear: {
        ...linear,
        gaps: interiorGaps(linear.bins),
        coverage: histogramCoverage(linear.bins, count),
      },
      log: {
        ...log,
        gaps: interiorGaps(log.bins),
        coverage: histogramCoverage(log.bins, count),
      },
    },
  };
}
