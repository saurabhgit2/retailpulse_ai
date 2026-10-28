/**
 * The forecast run response, reduced to what the page draws.
 *
 * Fixtured in `adaptRun.test.js` from a real run, so the field names here
 * came from the server rather than from what the page would find convenient.
 *
 * The one judgement in this file: the page has to report a run's failures as
 * loudly as its results. A fold where a model forecast zero still has a
 * number against it, and a reader comparing means has no way to see that one
 * of the four was degenerate unless something says so.
 */

const num = (v) => {
  const n = typeof v === 'string' ? Number(v) : v;
  return Number.isFinite(n) ? n : null;
};

/** `/forecast/latest` may return the run directly or wrapped. */
export function unwrap(payload) {
  if (!payload) return null;
  const run = payload.run ?? payload.latest ?? payload;
  return run && (run.id || run.status) ? run : null;
}

export function isFinished(run) {
  return run?.status === 'ready' || run?.status === 'failed';
}

/** What was chosen, and the claim the server makes about when. */
export function selection(run) {
  const s = run?.selection ?? {};
  return {
    model: s.selected_model ?? null,
    scoredAt: s.holdout_scored_at ?? null,
    warning: s.warning ?? null,
    // This sentence is the protocol's whole defence against the obvious
    // objection, so it is shown rather than paraphrased.
    note: s.note ?? null,
  };
}

/**
 * Every model with both its cross-validation mean and its hold-out score,
 * ranked separately, lowest error first.
 *
 * The rank pair is the point of the table. Reporting only the errors lets a
 * reader assume the orderings match, which on this data they do not.
 */
export function models(run) {
  const cv = run?.summary ?? [];
  const ho = new Map((run?.holdout ?? []).map((r) => [r.model, r]));

  const rows = cv.map((r) => ({
    model: r.model,
    cvWape: num(r.mean_wape),
    cvSd: num(r.sd_wape),
    cvWorst: num(r.worst_wape),
    foldsFailed: r.folds_failed ?? 0,
    usesExogenous: Boolean(r.uses_exogenous),
    holdoutWape: num(ho.get(r.model)?.wape),
    holdoutMae: num(ho.get(r.model)?.mae),
  }));

  rank(rows, 'cvWape', 'cvRank');
  rank(rows, 'holdoutWape', 'holdoutRank');
  for (const row of rows) {
    row.move =
      row.cvRank !== null && row.holdoutRank !== null ? row.cvRank - row.holdoutRank : null;
  }
  return rows;
}

function rank(rows, field, into) {
  const scored = rows.filter((r) => r[field] !== null).sort((a, b) => a[field] - b[field]);
  for (const row of rows) row[into] = null;
  scored.forEach((row, i) => {
    row[into] = i + 1;
  });
}

/**
 * Spearman's rank correlation between the two stages.
 *
 * Computed here rather than read from the response because the server does
 * not report it, and it is the single number that says whether selecting on
 * cross-validation tells you anything about what follows.
 */
export function rankCorrelation(rows) {
  const paired = rows.filter((r) => r.cvRank !== null && r.holdoutRank !== null);
  const n = paired.length;
  if (n < 3) return null;
  const d2 = paired.reduce((sum, r) => sum + (r.cvRank - r.holdoutRank) ** 2, 0);
  return 1 - (6 * d2) / (n * (n * n - 1));
}

const DAY = 24 * 60 * 60 * 1000;

/**
 * The hold-out window: what the chosen model predicted, against what happened.
 *
 * The response carries the values but not their dates, so the weeks are
 * rebuilt from the protocol's hold-out start at the series granularity. A
 * mismatch between the two would show as a chart that ends on the wrong week,
 * which is why `periods` is returned for the caller to check.
 */
export function holdoutForecast(run) {
  const iv = run?.intervals;
  if (!iv?.available) return null;
  const start = run?.protocol?.holdout?.test_start ?? null;
  const step = { day: 1, week: 7, month: 30 }[run?.series?.granularity ?? 'week'] ?? 7;
  const n = (iv.point ?? []).length;
  const periods = [];
  if (start) {
    const t0 = new Date(start).getTime();
    for (let i = 0; i < n; i += 1) periods.push(new Date(t0 + i * step * DAY).toISOString().slice(0, 10));
  }
  return {
    model: iv.model ?? null,
    level: num(iv.level),
    periods,
    point: (iv.point ?? []).map(num),
    lower: (iv.lower ?? []).map(num),
    upper: (iv.upper ?? []).map(num),
    actual: (iv.actual ?? []).map(num),
    method: iv.method ?? null,
    notes: iv.notes ?? [],
    sizingNote: iv.sizing_note ?? null,
    coverage: {
      observed: num(iv.coverage?.observed),
      nominal: num(iv.coverage?.nominal),
      points: iv.coverage?.points ?? null,
      verdict: iv.coverage?.verdict ?? null,
      caveat: iv.coverage?.caveat ?? null,
      meanWidth: num(iv.coverage?.mean_width),
    },
    // A flat forecast is a fact about the chosen model, not a rendering bug,
    // and a reader seeing a horizontal line deserves to be told which.
    isFlat: new Set((iv.point ?? []).map((v) => Math.round(v * 100))).size === 1,
  };
}

/** The omnibus test and what the server concludes from it. */
export function significance(run) {
  const s = run?.significance;
  const o = s?.omnibus;
  if (!o?.available) return null;
  return {
    test: o.test ?? null,
    pValue: num(o.p_value),
    alpha: num(s.alpha),
    rejects: Boolean(o.reject_null_at_05),
    blocks: o.blocks ?? null,
    bestByRank: o.best_by_mean_rank ?? null,
    interpretation: o.interpretation ?? null,
    summary: s.summary ?? null,
    caveats: o.caveats ?? [],
    grounding: o.grounding ?? null,
    correction: s.correction ?? null,
    comparisons: s.comparisons ?? null,
    significantPairs: s.significant_pairs ?? 0,
  };
}

/** The folds, as windows a reader can check for overlap. */
export function protocol(run) {
  const p = run?.protocol;
  if (!p) return null;
  return {
    style: p.style ?? null,
    horizon: p.horizon ?? null,
    observations: p.observations ?? null,
    notes: p.notes ?? [],
    folds: (p.folds ?? []).map((f) => ({
      fold: f.fold,
      trainStart: f.train_start,
      trainEnd: f.train_end,
      trainSize: f.train_size,
      testStart: f.test_start,
      testEnd: f.test_end,
    })),
    holdout: p.holdout
      ? {
          trainStart: p.holdout.train_start,
          trainEnd: p.holdout.train_end,
          trainSize: p.holdout.train_size,
          testStart: p.holdout.test_start,
          testEnd: p.holdout.test_end,
        }
      : null,
  };
}

/**
 * Everything about this run a reader should know before trusting a number.
 *
 * `degenerate` is the one the page would otherwise hide. A weighted absolute
 * percentage error of 100 with a symmetric error of exactly 200 is the
 * arithmetic signature of a forecast of zero, which is what a model anchored
 * on the last observation produces when a fold's training window ends on a
 * closure week that was filled with zero to keep the series evenly spaced.
 */
export function warnings(run) {
  const series = run?.series ?? {};
  const rows = [...(run?.cross_validation ?? []), ...(run?.holdout ?? [])];

  const degenerate = rows
    .filter((r) => num(r.smape) !== null && r.smape >= 199)
    .map((r) => ({
      model: r.model,
      where: r.is_holdout ? 'hold-out' : `fold ${r.fold}`,
      wape: num(r.wape),
      smape: num(r.smape),
    }));

  const failed = rows
    .filter((r) => r.error)
    .map((r) => ({ model: r.model, where: r.is_holdout ? 'hold-out' : `fold ${r.fold}`, error: r.error }));

  return {
    gapPeriods: series.gap_periods ?? [],
    gapsFilled: series.gaps_filled_with_zero ?? 0,
    gapNote: series.gap_note ?? null,
    incompleteDropped: series.incomplete_final_periods_dropped ?? 0,
    incompleteNote: series.incomplete_note ?? null,
    degenerate,
    failed,
    /**
     * Which closure weeks a fold boundary landed on. This is the link between
     * the zero-fill and the degenerate folds, and finding it by eye means
     * cross-referencing two tables, so it is computed.
     */
    boundariesOnGaps: (run?.protocol?.folds ?? [])
      .filter((f) => (series.gap_periods ?? []).includes(f.train_end))
      .map((f) => ({ fold: f.fold, trainEnd: f.train_end })),
  };
}

/** One call for the page. */
export function adaptRun(payload) {
  const run = unwrap(payload);
  if (!run) return null;
  const rows = models(run);
  return {
    id: run.id ?? null,
    status: run.status ?? null,
    error: run.error ?? null,
    createdAt: run.created_at ?? null,
    finishedAt: run.finished_at ?? null,
    configHash: run.config_hash ?? null,
    primaryMetric: run.primary_metric ?? 'WAPE',
    granularity: run.series?.granularity ?? null,
    valueColumn: run.series?.value_column ?? null,
    selection: selection(run),
    models: rows,
    rankCorrelation: rankCorrelation(rows),
    forecast: holdoutForecast(run),
    significance: significance(run),
    protocol: protocol(run),
    warnings: warnings(run),
  };
}
