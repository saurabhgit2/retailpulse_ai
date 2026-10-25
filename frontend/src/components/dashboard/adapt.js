/**
 * The one place the page assumes anything about the analytics response shape.
 *
 * Why this exists rather than reading `data.series.revenue` inside the chart:
 * the page was written against the contract in the backend guide, not against
 * a running server. If a field is spelled differently, the fix is one line
 * here instead of a hunt through four components, and `shapeProblem()` says
 * what was missing rather than rendering an empty chart that looks like a
 * dataset with no sales.
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
 * Headline figures.
 *
 * A null value is rendered as "not available" with its reason, never as
 * zero. The backend withholds a KPI whose source column is absent and
 * withholds growth when the two comparison windows are not the same length;
 * both of those are claims, and showing 0 or 0% would be a different claim.
 */
export function adaptKpis(payload) {
  const k = pick(payload, ['kpis', 'values', 'data'], payload) ?? {};
  const growth = pick(payload, ['growth', 'comparison'], {}) ?? {};
  const note = pick(payload, ['growth_note', 'comparison_note', 'note'], null);

  const definitions = [
    { key: 'revenue', label: 'Net revenue', names: ['revenue', 'net_revenue', 'total_revenue'], currency: '£' },
    { key: 'orders', label: 'Orders', names: ['orders', 'order_count', 'invoices'] },
    { key: 'customers', label: 'Customers', names: ['customers', 'customer_count', 'unique_customers'] },
    { key: 'aov', label: 'Average order value', names: ['aov', 'average_order_value'], currency: '£' },
    { key: 'units', label: 'Units sold', names: ['units', 'quantity', 'total_quantity'] },
  ];

  return definitions.map((d) => ({
    key: d.key,
    label: d.label,
    value: num(pick(k, d.names)),
    growth: num(pick(growth, d.names)),
    currency: d.currency ?? null,
    note,
  }));
}

/**
 * A time series.
 *
 * Accepts either a list of row objects or parallel arrays, because both
 * shapes are reasonable and the guide does not say which the endpoint
 * returns. Partial periods are carried through so the last point can be
 * drawn as what it is: an incomplete week, not a collapse in trade.
 */
export function adaptTrend(payload) {
  const rows = pick(payload, ['points', 'series', 'rows', 'data'], []);
  if (Array.isArray(rows) && rows.length && typeof rows[0] === 'object') {
    return {
      x: rows.map((r) => pick(r, ['period', 'week_start', 'date', 'occurred_at', 'bucket'])),
      revenue: rows.map((r) => num(pick(r, ['revenue', 'net_revenue', 'value']))),
      orders: rows.map((r) => num(pick(r, ['orders', 'order_count']))),
      partial: rows.map((r) => Boolean(pick(r, ['is_partial', 'partial'], false))),
    };
  }
  const x = pick(payload, ['periods', 'index', 'labels'], []) ?? [];
  return {
    x,
    revenue: (pick(payload, ['revenue'], []) ?? []).map(num),
    orders: (pick(payload, ['orders'], []) ?? []).map(num),
    partial: pick(payload, ['is_partial', 'partial'], x.map(() => false)) ?? [],
  };
}

/** A ranked breakdown: products, regions or categories. */
export function adaptBreakdown(payload, { limit = 10 } = {}) {
  const rows = pick(payload, ['items', 'rows', 'breakdown', 'data'], []) ?? [];
  return rows.slice(0, limit).map((r, i) => ({
    key: String(pick(r, ['key', 'code', 'product_code', 'id'], i)),
    label: String(pick(r, ['label', 'name', 'description', 'product_name', 'region', 'category'], '—')),
    value: num(pick(r, ['value', 'revenue', 'net_revenue', 'total'])) ?? 0,
    share: num(pick(r, ['share', 'pareto_share', 'cumulative_share'])),
  }));
}

/**
 * Concentration: the Gini coefficient and the Pareto point.
 * Returned as null when the endpoint does not carry them, so the tile says
 * "not reported" rather than inventing a 0.
 */
export function adaptConcentration(payload) {
  const source = pick(payload, ['concentration', 'pareto'], payload) ?? {};
  return {
    gini: num(pick(source, ['gini', 'gini_coefficient'])),
    topShare: num(pick(source, ['top_20_share', 'top20_share', 'pareto_share'])),
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
