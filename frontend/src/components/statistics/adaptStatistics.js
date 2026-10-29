/**
 * The statistics and feature-relevance responses, turned into what the
 * Statistics page draws.
 *
 * Both endpoints are unusually careful about their own limits — one declines
 * to run a normality test and says why, the other reports mutual information
 * under three bin counts and lists five caveats — and most of the work here
 * is making sure none of that care is lost on the way to the screen.
 *
 * The rule throughout: where the endpoint reports a caveat, a substitution or
 * a refusal, it reaches the page as text rather than being dropped because it
 * would not fit a chart.
 */

import { distributionShape } from '../shared/histogramShape.js';

const num = (value) => (typeof value === 'number' && Number.isFinite(value) ? value : null);

/** A snake_case field name as a label: `avg_unit_price` to "Avg unit price". */
export function fieldLabel(name) {
  const words = String(name ?? '').replace(/_/g, ' ').trim();
  if (!words) return '—';
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** The headline descriptive block, with the variable and grouping it describes. */
export function adaptDescriptive(payload) {
  const d = payload ?? {};
  const s = d.descriptive ?? {};
  return {
    value: d.value ?? null,
    group: d.group ?? null,
    n: num(s.n),
    mean: num(s.mean),
    median: num(s.median),
    stdDev: num(s.std_dev),
    coefficientOfVariation: num(s.coefficient_of_variation),
    min: num(s.min),
    max: num(s.max),
    q1: num(s.q1),
    q3: num(s.q3),
    iqr: num(s.iqr),
    skewness: num(s.skewness),
    kurtosisExcess: num(s.kurtosis_excess),
    meanOverMedian: num(s.mean_over_median),
  };
}

/**
 * The shape verdict.
 *
 * The endpoint deliberately does not run a normality hypothesis test, and
 * explains that at this sample size such a test rejects for deviations too
 * small to matter. That refusal is a methodological position, not a missing
 * feature, so the page prints the reason rather than an empty slot.
 */
export function adaptNormality(payload) {
  const n = payload?.normality;
  if (!n || n.available === false) {
    return { available: false, reason: n?.reason ?? null };
  }
  return {
    available: true,
    n: num(n.n),
    verdict: n.verdict ?? null,
    skewness: num(n.skewness),
    kurtosisExcess: num(n.kurtosis_excess),
    meanOverMedian: num(n.mean_over_median),
    note: n.note ?? null,
  };
}

/**
 * The group comparison, and the test applied to it.
 *
 * `bins` plots the median of each group, because the median is what a
 * significance test on ranks is actually comparing, and because on this
 * dataset the four medians are within seven pounds of each other while the
 * test reports a significant difference. Putting a flat chart beside a
 * significant p-value is the whole point of the section.
 */
export function adaptComparison(payload) {
  const c = payload?.comparison;
  if (!c || !Array.isArray(c.groups)) return null;

  const groups = c.groups.map((g, i) => ({
    key: String(g.group ?? i),
    label: String(g.group ?? i),
    value: num(g.median) ?? 0,
    n: num(g.n),
    mean: num(g.mean),
    median: num(g.median),
    stdDev: num(g.std_dev),
    q1: num(g.q1),
    q3: num(g.q3),
    iqr: num(g.iqr),
    skewness: num(g.skewness),
    min: num(g.min),
    max: num(g.max),
  }));

  const medians = groups.map((g) => g.median).filter((v) => v !== null);

  return {
    label: c.label ?? null,
    groups,
    excludedSmallGroups: Array.isArray(c.excluded_small_groups) ? c.excluded_small_groups : [],
    // The spread between the group medians, which is the quantity the reader
    // should weigh the p-value against.
    medianSpread: medians.length > 1 ? Math.max(...medians) - Math.min(...medians) : null,
    test: adaptTest(c.test),
  };
}

/**
 * A significance test with its effect size.
 *
 * `headline` decides which of the two the page leads with. A significant
 * result whose effect size is negligible is a statement about sample size,
 * not about the groups, and the endpoint says so itself in
 * `interpretation_note`. Leading with the p-value there would invert the
 * finding.
 */
export function adaptTest(test) {
  if (!test) return null;
  const effect = test.effect_size ?? {};
  const magnitude = effect.magnitude ?? null;
  const significant = Boolean(test.significant);
  const negligible = magnitude === 'negligible';

  return {
    name: test.name ?? null,
    statistic: num(test.statistic),
    pValue: num(test.p_value),
    degreesOfFreedom: num(test.degrees_of_freedom),
    significant,
    alpha: num(test.alpha),
    tests: test.tests ?? null,
    assumes: test.assumes ?? null,
    note: test.note ?? null,
    interpretationNote: test.interpretation_note ?? null,
    largeSampleWarning: Boolean(test.large_sample_warning),
    effect: {
      name: effect.name ?? null,
      value: num(effect.value),
      magnitude,
    },
    headline: significant && negligible ? 'effect' : 'significance',
  };
}

/** Stationarity, which this endpoint may legitimately not carry. */
export function adaptStationarity(payload) {
  const s = payload?.stationarity;
  if (!s || s.available === false) {
    return { available: false, reason: s?.reason ?? null };
  }
  return { available: true, ...s };
}

/**
 * Feature relevance by mutual information.
 *
 * Two estimators are reported, a k-nearest-neighbour one and a binned one,
 * and the page shows both ranks rather than picking a winner: where they
 * disagree, that disagreement is itself the information, which is what the
 * endpoint's own `rank_agreement.note` says.
 *
 * `targetSubstituted` matters. The response carries `target_requested` and
 * `target` separately, and on this dataset they differ — weekly_quantity was
 * asked for and units came back. A page that printed only the target it got
 * would hide a substitution the reader did not make.
 */
export function adaptFeatures(payload) {
  const d = payload ?? {};
  if (d.available === false) return { available: false };

  const rows = Array.isArray(d.features) ? d.features : [];
  const features = rows.map((f, i) => ({
    key: String(f.feature ?? i),
    label: fieldLabel(f.feature),
    value: num(f.mi_knn) ?? 0,
    miKnn: num(f.mi_knn),
    miBinned: num(f.mi_binned),
    miByBins: f.mi_by_bins ?? {},
    binSensitivity: num(f.bin_sensitivity),
    rankKnn: num(f.rank_knn),
    rankBinned: num(f.rank_binned),
  }));

  const agreement = d.rank_agreement ?? {};

  return {
    available: true,
    target: d.target ?? null,
    targetRequested: d.target_requested ?? null,
    targetSubstituted: Boolean(
      d.target_requested && d.target && d.target_requested !== d.target,
    ),
    rowsUsed: num(d.rows_used),
    rowsAvailable: num(d.rows_available),
    sampled: Boolean(d.sampled),
    topProductsAnalysed: num(d.top_products_analysed),
    features,
    categorical: Array.isArray(d.categorical) ? d.categorical : [],
    rankAgreement: {
      available: agreement.available !== false,
      spearman: num(agreement.spearman),
      kendall: num(agreement.kendall),
      note: agreement.note ?? null,
    },
    // Null is not zero. The endpoint says model-based importance arrives with
    // the forecasting engine, and the page reports that rather than an empty
    // chart.
    modelImportance: d.model_importance ?? null,
    limitations: Array.isArray(d.limitations) ? d.limitations : [],
  };
}

/**
 * Features the two estimators rank differently.
 *
 * Sorted by the size of the disagreement, because that is the order in which
 * they are worth looking at. A gap of one place is noise in an ordering of
 * seventeen; a gap of six is the estimators seeing different things.
 */
export function rankDisagreements(features, { minGap = 2 } = {}) {
  return features
    .map((f) => ({
      ...f,
      gap:
        f.rankKnn === null || f.rankBinned === null
          ? null
          : Math.abs(f.rankKnn - f.rankBinned),
    }))
    .filter((f) => f.gap !== null && f.gap >= minGap)
    .sort((a, b) => b.gap - a.gap);
}

/**
 * How much the binned estimate moves with the bin count.
 *
 * The endpoint reports three bin counts precisely because the answer depends
 * on the choice, and the spread between them is the honest summary of that
 * dependence.
 */
export function binRange(feature) {
  const values = Object.values(feature?.miByBins ?? {}).map(num).filter((v) => v !== null);
  if (!values.length) return null;
  return { low: Math.min(...values), high: Math.max(...values), spread: Math.max(...values) - Math.min(...values) };
}

/** The per-line distribution block, when this endpoint carries one. */
export function adaptStatisticsDistribution(payload, { currency = null } = {}) {
  return distributionShape(payload?.distribution, { currency });
}

export { cacheNote } from '../shared/provenance.js';
