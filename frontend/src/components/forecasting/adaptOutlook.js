/**
 * The outlook response, reduced to what the Forecasting page draws.
 *
 * Tested in `adaptOutlook.test.js` against a fixture captured from the real
 * endpoint, so the field names here come from the server. This is the only
 * file on the frontend that knows them.
 */

const num = (v) => {
  const n = typeof v === 'string' ? Number(v) : v;
  return Number.isFinite(n) ? n : null;
};

export const MEASURES = [
  { key: 'net_revenue', label: 'Revenue', currency: '£' },
  { key: 'net_units', label: 'Units', currency: null },
];

/** "High" / "Medium" / "Low", and the badge tone that goes with each. */
export const CONFIDENCE = {
  high: { label: 'High', tone: 'ok' },
  medium: { label: 'Medium', tone: 'warn' },
  low: { label: 'Low', tone: 'crit' },
  unknown: { label: 'Unknown', tone: 'neutral' },
};

/**
 * One measure (revenue or units) laid out on a single time axis: the last
 * year of actuals followed by the forecast weeks.
 *
 * The forecast line starts on the last actual week so the two lines join
 * instead of leaving a gap. A week that was closed a year ago is forecast as
 * closed; it is left out of the line rather than drawn as a plunge to zero,
 * and the table says why.
 */
export function measureView(block) {
  if (!block?.available) {
    return block ? { available: false, label: block.label, reason: block.reason ?? null } : null;
  }
  const history = block.history ?? { periods: [], values: [] };
  const forecast = block.forecast ?? { periods: [], point: [], lower: [], upper: [] };
  const h = history.periods.length;
  const f = forecast.periods.length;
  const closed = forecast.likely_closed ?? new Array(f).fill(false);

  const x = [...history.periods, ...forecast.periods];
  const actual = [...history.values.map(num), ...new Array(f).fill(null)];
  const point = new Array(h + f).fill(null);
  const lower = new Array(h + f).fill(null);
  const upper = new Array(h + f).fill(null);

  // Join the lines at the last actual week.
  const lastActual = num(history.values[h - 1]);
  if (h > 0 && lastActual !== null) {
    point[h - 1] = lastActual;
    lower[h - 1] = lastActual;
    upper[h - 1] = lastActual;
  }
  forecast.point.forEach((v, i) => {
    if (closed[i]) return;
    point[h + i] = num(v);
    lower[h + i] = num(forecast.lower[i]);
    upper[h + i] = num(forecast.upper[i]);
  });

  const accuracy = block.accuracy ?? {};
  const totals = block.totals ?? {};
  return {
    available: true,
    label: block.label,
    model: block.model ?? null,
    accuracy: {
      wape: num(accuracy.wape),
      confidence: accuracy.confidence ?? 'unknown',
      backtests: accuracy.backtests ?? 0,
      horizon: accuracy.horizon ?? f,
      step: accuracy.step ?? null,
    },
    chart: { x, actual, point, lower, upper, firstForecastIndex: h },
    level: num(forecast.level),
    weeks: forecast.periods.map((week, i) => ({
      week,
      point: num(forecast.point[i]),
      lower: num(forecast.lower[i]),
      upper: num(forecast.upper[i]),
      closed: Boolean(closed[i]),
    })),
    closedWeeks: forecast.periods.filter((_, i) => closed[i]),
    totals: {
      next4: num(totals.next_4),
      nextHorizon: num(totals.next_horizon),
      lastYear: num(totals.same_weeks_last_year),
      changeVsLastYear: num(totals.change_vs_last_year),
      lastHorizon: num(totals.last_horizon),
    },
    recentCheck: recentCheck(block.recent_check),
    candidates: (block.candidates ?? []).map((c) => ({
      name: c.name,
      label: c.label,
      wape: num(c.wape),
      backtests: c.backtests ?? 0,
      chosen: Boolean(c.chosen),
      flat: Boolean(c.flat),
    })),
  };
}

function recentCheck(check) {
  if (!check) return null;
  return {
    periods: check.periods ?? [],
    actual: (check.actual ?? []).map(num),
    forecast: (check.forecast ?? []).map(num),
    wape: num(check.wape),
  };
}

/** Top products, biggest earners first, with the numbers a reorder needs. */
export function productRows(block) {
  if (!block?.available) return [];
  return (block.rows ?? []).map((r) => ({
    code: r.product_code,
    description: r.description ?? r.product_code,
    model: r.model?.label ?? r.model?.name ?? null,
    seasonal: Boolean(r.model?.seasonal),
    wape: num(r.accuracy?.wape),
    confidence: r.accuracy?.confidence ?? 'unknown',
    lastHorizon: num(r.last_horizon_units),
    next4: num(r.next_4_units),
    nextHorizon: num(r.next_horizon_units),
    changeVsRecent: num(r.change_vs_recent),
    changeVsLastYear: num(r.change_vs_last_year),
    view: measureView({
      available: true,
      label: r.description ?? r.product_code,
      history: r.history,
      forecast: r.forecast,
      accuracy: r.accuracy,
      model: r.model,
    }),
  }));
}

/**
 * The plain-English reading of a typical error, e.g. "usually within 9%".
 * WAPE is the total miss as a share of the total, so it reads naturally as
 * "how far off, on average".
 */
export function errorPhrase(wape) {
  if (wape === null || wape === undefined) return 'accuracy unknown';
  return `usually within ${Math.max(1, Math.round(wape))}%`;
}

/** One call for the page. */
export function adaptOutlook(payload) {
  if (!payload) return null;
  const measures = {};
  for (const m of MEASURES) measures[m.key] = measureView(payload.measures?.[m.key]);
  return {
    available: Boolean(payload.available),
    horizon: payload.horizon ?? 12,
    lastPeriod: payload.series?.last_period ?? null,
    firstPeriod: payload.series?.first_period ?? null,
    closedWeeks: payload.series?.closed_weeks ?? [],
    measures,
    products: productRows(payload.products),
    productNote: payload.products?.note ?? null,
    productLimit: payload.products?.limit ?? null,
    methodNote: payload.method_note ?? null,
    cached: Boolean(payload._cache?.hit),
  };
}
