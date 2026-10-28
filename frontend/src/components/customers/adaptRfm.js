/**
 * The RFM response, turned into what the Customers page draws.
 *
 * Everything here is a pure function of the payload. That is the same rule the
 * backend's analytics modules follow, and it buys the same two things: the
 * page can be read without tracing a fetch, and every transformation on this
 * page is testable against a fixture without a browser or a server.
 *
 * One judgement is encoded throughout. The endpoint reports several figures
 * as `null` when it cannot compute them, and a customer whose returns exceed
 * their purchases has a genuinely negative value. Neither is a zero, and
 * neither is rounded away here: a null stays a null and reaches the page as
 * "not reported", and negative monetary customers get their own bucket rather
 * than being dropped to make the histogram tidy.
 */

const num = (value) => (typeof value === 'number' && Number.isFinite(value) ? value : null);

/**
 * Bands for the monetary histogram.
 *
 * Fixed, unequal bands rather than equal-width bins because monetary value in
 * this dataset has a skewness of 26.9: equal bins put 99% of customers in the
 * first bar and draw nine empty ones. The widths roughly double, which is a
 * log scale expressed as labels a reader can price rather than as an axis
 * they have to decode.
 *
 * The first band is "£0 or less", not "£0-100". 27 customers have a negative
 * net value, and a bucket that mixes them in with small spenders hides the
 * one fact about them that matters.
 */
export const MONETARY_BANDS = [
  { key: 'le0', label: '£0 or less', upper: 0 },
  { key: 'lt100', label: '£0–100', upper: 100 },
  { key: 'lt250', label: '£100–250', upper: 250 },
  { key: 'lt500', label: '£250–500', upper: 500 },
  { key: 'lt1k', label: '£500–1k', upper: 1_000 },
  { key: 'lt2k5', label: '£1k–2.5k', upper: 2_500 },
  { key: 'lt5k', label: '£2.5k–5k', upper: 5_000 },
  { key: 'lt10k', label: '£5k–10k', upper: 10_000 },
  { key: 'lt25k', label: '£10k–25k', upper: 25_000 },
  { key: 'ge25k', label: '£25k+', upper: Infinity },
];

/**
 * Bands for the recency histogram.
 *
 * Measured from the end of the data, not from today, which is the endpoint's
 * own caveat and is repeated on the page. The boundaries are the ones a
 * retailer already thinks in: a month, a quarter, half a year, a year, two.
 */
export const RECENCY_BANDS = [
  { key: 'd30', label: '0–30d', upper: 30 },
  { key: 'd60', label: '31–60d', upper: 60 },
  { key: 'd90', label: '61–90d', upper: 90 },
  { key: 'd180', label: '91–180d', upper: 180 },
  { key: 'd365', label: '181–365d', upper: 365 },
  { key: 'y15', label: '1–1.5y', upper: 547 },
  { key: 'y2', label: '1.5–2y', upper: 730 },
  { key: 'y2plus', label: '2y+', upper: Infinity },
];

/** Headline figures, coverage and concentration. */
export function adaptOverview(payload) {
  const d = payload ?? {};
  const coverage = d.coverage ?? {};
  const concentration = d.concentration ?? {};
  const dist = d.distributions ?? {};

  return {
    available: d.available !== false,
    asOf: d.as_of ?? null,
    customers: num(d.customers),
    recencyUnit: d.recency_unit ?? 'days',

    identifiedRevenue: num(coverage.identified_revenue),
    guestRevenue: num(coverage.guest_revenue),
    guestLines: num(coverage.guest_lines),
    guestShare: num(coverage.guest_revenue_share),

    negativeCustomers: num(d.negative_monetary_customers),
    minimumMonetary: num(d.minimum_monetary),

    medianMonetary: num(dist.monetary?.median),
    medianFrequency: num(dist.frequency?.median),
    medianRecency: num(dist.recency_days?.median),

    concentration: {
      // Reported over `entities`, which is not the same as `customers`: the
      // endpoint computes concentration over customers with a positive value.
      // The page states both numbers rather than letting the difference pass.
      gini: num(concentration.gini ?? d.monetary_gini),
      entities: num(concentration.entities),
      topShare: num(concentration.top_share),
      topFraction: num(concentration.top_fraction),
      topCount: num(concentration.top_count),
    },

    distributions: dist,
    definitions: {
      monetary: d.monetary_definition ?? null,
      frequency: d.frequency_definition ?? null,
    },
  };
}

/** A segment key as a label: `potential_loyalist` becomes "Potential loyalist". */
export function segmentLabel(key) {
  const words = String(key ?? '').replace(/_/g, ' ').trim();
  if (!words) return '—';
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** The six segments, largest share of revenue first. */
export function adaptSegments(payload) {
  const rows = Array.isArray(payload?.segments) ? payload.segments : [];
  return rows
    .map((s) => ({
      key: String(s.segment),
      label: segmentLabel(s.segment),
      description: s.description ?? '',
      customers: num(s.customers) ?? 0,
      customerShare: num(s.customer_share),
      monetary: num(s.monetary) ?? 0,
      monetaryShare: num(s.monetary_share),
      medianMonetary: num(s.median_monetary),
      medianFrequency: num(s.median_frequency),
      medianRecency: num(s.median_recency_days),
    }))
    .sort((a, b) => b.monetary - a.monetary);
}

/**
 * Segments ranked by headcount against segments ranked by revenue.
 *
 * This is the one comparison on the page that has to be a picture. The claim
 * is that the two orderings disagree: the largest group of customers is the
 * smallest share of the money. Two bar charts would make the reader hold one
 * ordering in their head while reading the other, which is precisely the work
 * a slope chart does for them.
 */
export function segmentSlope(segments) {
  const byCustomers = [...segments].sort((a, b) => b.customers - a.customers);
  const byRevenue = [...segments].sort((a, b) => b.monetary - a.monetary);
  const leftRank = new Map(byCustomers.map((s, i) => [s.key, i + 1]));
  const rightRank = new Map(byRevenue.map((s, i) => [s.key, i + 1]));

  return byCustomers.map((s) => ({
    key: s.key,
    label: s.label,
    leftRank: leftRank.get(s.key),
    rightRank: rightRank.get(s.key),
    leftValue: s.customerShare,
    rightValue: s.monetaryShare,
  }));
}

/**
 * Count values into bands.
 *
 * `upper` is inclusive, so a customer sitting exactly on a boundary falls in
 * the lower band and is counted once. Values that are not finite are not
 * counted at all: a missing figure is not a zero, and silently binning it as
 * one would move customers into the first bar who do not belong there.
 */
export function bandCounts(values, bands) {
  const counts = bands.map(() => 0);
  let skipped = 0;
  for (const raw of values) {
    const value = num(raw);
    if (value === null) {
      skipped += 1;
      continue;
    }
    const index = bands.findIndex((b) => value <= b.upper);
    counts[index === -1 ? bands.length - 1 : index] += 1;
  }
  return {
    bins: bands.map((b, i) => ({ key: b.key, label: b.label, value: counts[i] })),
    skipped,
  };
}

/** The monetary histogram. */
export function monetaryBands(payload) {
  const table = Array.isArray(payload?.table) ? payload.table : [];
  return bandCounts(table.map((r) => r.monetary), MONETARY_BANDS);
}

/** The recency histogram. */
export function recencyBands(payload) {
  const table = Array.isArray(payload?.table) ? payload.table : [];
  return bandCounts(table.map((r) => r.recency_days), RECENCY_BANDS);
}

/**
 * The two ends of the recency distribution.
 *
 * Summary statistics describe this one badly. The median is 93 days and the
 * skewness is 0.90, which together suggest a single, mildly lopsided hump;
 * the histogram is nothing of the sort. There is a large group who bought in
 * the last month and a second group who have not bought for over a year, with
 * a trough between them. Those two shares say more about the customer base
 * than any moment of the distribution does, so the page quotes them.
 *
 * Derived from the bands rather than from raw days so the figures on the page
 * always agree with the bars above them.
 */
export function recencySplit(bins) {
  const total = bins.reduce((sum, b) => sum + b.value, 0);
  if (!total) return { recentShare: null, dormantShare: null, recent: 0, dormant: 0, total: 0 };
  const sumOf = (keys) =>
    bins.filter((b) => keys.includes(b.key)).reduce((sum, b) => sum + b.value, 0);
  const recent = sumOf(['d30']);
  const dormant = sumOf(['y15', 'y2', 'y2plus']);
  return {
    recent,
    dormant,
    total,
    recentShare: recent / total,
    dormantShare: dormant / total,
  };
}

/**
 * The largest customers by net value.
 *
 * `share` is of identified revenue, not of all revenue, because that is the
 * denominator these customers were ranked within. Guest sales have no
 * customer to attribute them to, so including them in the denominator would
 * understate every share on the chart by the guest share.
 */
export function topCustomers(payload, limit = 10) {
  const table = Array.isArray(payload?.table) ? payload.table : [];
  const total = num(payload?.coverage?.identified_revenue);
  return [...table]
    .sort((a, b) => (num(b.monetary) ?? 0) - (num(a.monetary) ?? 0))
    .slice(0, limit)
    .map((r) => ({
      key: String(r.customer),
      label: `Customer ${r.customer}`,
      value: num(r.monetary) ?? 0,
      share: total ? (num(r.monetary) ?? 0) / total : null,
      segment: segmentLabel(r.segment),
      frequency: num(r.frequency),
      recency: num(r.recency_days),
      averageOrderValue: num(r.average_order_value),
    }));
}

/** The endpoint's own caveats and notes, carried through unchanged. */
export function methodNotes(payload) {
  return {
    caveats: Array.isArray(payload?.caveats) ? payload.caveats : [],
    clustering: Array.isArray(payload?.clustering_notes) ? payload.clustering_notes : [],
  };
}

/**
 * Where this response came from.
 *
 * Shown on the page because a cached result and a freshly computed one are
 * not the same claim: a cache hit is as old as `computed_at`, and on a
 * dataset that can be re-ingested that is worth being able to see.
 */
export function cacheNote(payload) {
  const cache = payload?._cache;
  if (!cache) return null;
  const ms = num(cache.computed_ms);
  const when = cache.computed_at ? new Date(cache.computed_at) : null;
  const stamp = when && !Number.isNaN(when.getTime())
    ? new Intl.DateTimeFormat('en-NZ', {
        day: 'numeric',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
        timeZone: 'UTC',
      }).format(when)
    : null;
  if (!cache.hit) return ms ? `Computed for this request in ${(ms / 1000).toFixed(1)}s.` : null;
  return `Served from cache${stamp ? `, computed ${stamp} UTC` : ''}${
    ms ? ` in ${(ms / 1000).toFixed(1)}s` : ''
  }.`;
}
