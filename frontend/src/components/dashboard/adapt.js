/**
 * The one place the page assumes anything about the analytics response shape.
 *
 * The KPI and filter-options shapes below are now taken from the server's
 * OpenAPI schema rather than guessed. Trends and products are declared there
 * only as free-form objects, so those two still try a short list of
 * candidate field names, and `shapeProblem()` reports what actually arrived
 * instead of rendering an empty chart that looks like a dataset with no
 * sales.
 */

/** First present, non-null value among several candidate field names. */
export function pick(object, names, fallback = null) {
  if (!object) return fallback;
  for (const name of names) {
    const value = object[name];
    if (value !== undefined && value !== null) return value;
  }
  return fallback;
}

const num = (v) => {
  const n = typeof v === 'string' ? Number(v) : v;
  return Number.isFinite(n) ? n : null;
};

/**
 * Headline figures, from the documented KpiResponse:
 *
 *   { values: KpiValues, previous, growth: {field: number|null}|null,
 *     comparison: { comparable: boolean, note: string|null } }
 *
 * A null value renders as "not available" with its reason, never as zero.
 * The server withholds a KPI whose source column is absent and withholds
 * growth when the two windows are not comparable; both of those are claims,
 * and 0 or 0% would be a different claim.
 */
export function adaptKpis(payload) {
  const values = payload?.values ?? {};
  const growth = payload?.growth ?? {};
  const comparison = payload?.comparison ?? null;
  // The reason comparison was refused lives on the comparison object, not at
  // the top level, and it is what the card shows in place of a figure.
  const note = comparison && comparison.comparable === false ? comparison.note : null;

  const definitions = [
    { key: 'net_revenue', label: 'Net revenue', currency: '£' },
    { key: 'orders', label: 'Orders' },
    { key: 'active_customers', label: 'Active customers' },
    { key: 'average_order_value', label: 'Average order value', currency: '£' },
    { key: 'units', label: 'Units sold' },
  ];

  return definitions.map((d) => ({
    key: d.key,
    label: d.label,
    value: num(values[d.key]),
    growth: num(growth?.[d.key]),
    currency: d.currency ?? null,
    note,
  }));
}

/**
 * Secondary figures that only make sense as rates, kept apart from the
 * headline row so a percentage never sits in a column of money.
 */
export function adaptRates(payload) {
  const values = payload?.values ?? {};
  return {
    returnRate: num(values.return_rate),
    guestShare: num(values.guest_revenue_share),
    returnsValue: num(values.returns_value),
    grossRevenue: num(values.gross_revenue),
    lines: num(values.lines),
  };
}

/**
 * A time series.
 *
 * Accepts either a list of row objects or parallel arrays, because the
 * schema declares this response as a free-form object and does not say
 * which. Partial periods are carried through so the last point can be drawn
 * as what it is: an incomplete week, not a collapse in trade.
 */
export function adaptTrend(payload) {
  const rows = pick(payload, ['points', 'series', 'rows', 'data'], []);
  if (Array.isArray(rows) && rows.length && typeof rows[0] === 'object') {
    return {
      x: rows.map((r) => pick(r, ['period', 'period_start', 'week_start', 'date', 'bucket'])),
      revenue: rows.map((r) => num(pick(r, ['net_revenue', 'revenue', 'gross_revenue', 'value']))),
      orders: rows.map((r) => num(pick(r, ['orders', 'order_count']))),
      movingAverage: rows.map((r) => num(pick(r, ['moving_average', 'ma']))),
      partial: rows.map((r) => Boolean(pick(r, ['is_partial', 'partial'], false))),
    };
  }
  const x = pick(payload, ['periods', 'index', 'labels'], []) ?? [];
  return {
    x,
    revenue: (pick(payload, ['net_revenue', 'revenue'], []) ?? []).map(num),
    orders: (pick(payload, ['orders'], []) ?? []).map(num),
    movingAverage: (pick(payload, ['moving_average', 'ma'], []) ?? []).map(num),
    partial: pick(payload, ['is_partial', 'partial'], x.map(() => false)) ?? [],
  };
}

/** A ranked list: products, regions, categories or customers. */
export function adaptRanked(payload, { limit = 10 } = {}) {
  const rows = pick(payload, ['items', 'products', 'regions', 'categories', 'customers', 'rows', 'data'], []) ?? [];
  return rows.slice(0, limit).map((r, i) => ({
    key: String(pick(r, ['product_code', 'code', 'key', 'region', 'category', 'customer_id', 'id'], i)),
    label: String(
      pick(r, ['description', 'product_name', 'name', 'label', 'region', 'category'], '—'),
    ),
    value: num(pick(r, ['net_revenue', 'gross_revenue', 'revenue', 'value', 'units', 'orders'])) ?? 0,
    share: num(pick(r, ['share', 'revenue_share', 'pareto_share', 'cumulative_share'])),
  }));
}

/**
 * Concentration, from what the ranked endpoint actually returns.
 *
 * There is no Gini coefficient in this response, and the obvious
 * substitutes are not available either: the top-20%-of-products share
 * cannot be computed from ten rows out of several thousand. What the
 * response does carry is exact — `entities` (how many there are in total),
 * `total` (the sum across all of them) and a `cumulative_share` on each row
 * — so the tile reports the share the returned rows account for and says
 * how many rows that is. A smaller claim, fully supported, beats a bigger
 * one that needs the whole distribution.
 */
export function adaptConcentration(payload) {
  const rows = pick(payload, ['items', 'rows', 'data'], []) ?? [];
  const last = rows.length ? rows[rows.length - 1] : null;
  const shown = rows.length;
  const topShare = num(pick(last ?? {}, ['cumulative_share']));
  return {
    shown,
    entities: num(pick(payload, ['entities'])),
    total: num(pick(payload, ['total'])),
    topShare,
    // The sort the server actually applied, which is not always the one that
    // was asked for, and names what `total` and the shares are shares *of*.
    measure: pick(payload, ['sort']),
  };
}

/** Region names and categories for the filter bar, from FilterOptions. */
export function adaptFilterOptions(payload) {
  const regions = (payload?.regions ?? []).map((r) =>
    typeof r === 'string' ? r : String(pick(r, ['region', 'name', 'label', 'value'], '')),
  );
  return {
    regions: regions.filter(Boolean),
    categories: (payload?.categories ?? []).filter(Boolean),
    customerTypes: payload?.customer_types ?? [],
    rows: payload?.rows ?? null,
  };
}

/**
 * Whether a payload looks like the thing the page expected.
 * Used to show a specific message instead of an empty chart.
 */
export function shapeProblem(payload, expected) {
  if (payload === null || payload === undefined) return 'No response body.';
  const found = Array.isArray(payload) ? [] : Object.keys(payload);
  if (expected.some((name) => found.includes(name))) return null;
  return `The response did not carry any of ${expected.join(', ')}. Received: ${
    found.length ? found.join(', ') : 'an array'
  }.`;
}
