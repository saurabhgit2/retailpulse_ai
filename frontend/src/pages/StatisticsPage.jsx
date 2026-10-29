import { useCallback, useMemo } from 'react';
import { useParams } from 'react-router';

import { BarChart, ChartFrame, ColumnChart, compact, exact, percent } from '../charts/index.js';
import {
  adaptComparison,
  adaptDescriptive,
  adaptFeatures,
  adaptNormality,
  adaptStationarity,
  binRange,
  cacheNote,
  rankDisagreements,
} from '../components/statistics/adaptStatistics.js';
import { useApi } from '../hooks/useApi.js';
import { getFeatures, getStatistics } from '../services/analytics.js';

/**
 * Statistics and features.
 *
 * Two endpoints that are unusually careful about their own limits, and the
 * page is built to keep that care rather than flatten it into numbers.
 *
 * The group comparison is the section worth lingering on. The test reports a
 * significant difference between quarters; the effect size reports it as
 * negligible; the four medians sit within a few pounds of one another. All
 * three are true at once, and the page shows them together rather than
 * leading with whichever is most quotable.
 */
export function StatisticsPage() {
  const { datasetId } = useParams();

  const loadStatistics = useCallback(
    (signal) => getStatistics(datasetId, { signal }),
    [datasetId],
  );
  const loadFeatures = useCallback((signal) => getFeatures(datasetId, { signal }), [datasetId]);

  const statistics = useApi(loadStatistics);
  const featuresApi = useApi(loadFeatures);

  const descriptive = useMemo(() => adaptDescriptive(statistics.data), [statistics.data]);
  const normality = useMemo(() => adaptNormality(statistics.data), [statistics.data]);
  const comparison = useMemo(() => adaptComparison(statistics.data), [statistics.data]);
  const stationarity = useMemo(() => adaptStationarity(statistics.data), [statistics.data]);
  const features = useMemo(() => adaptFeatures(featuresApi.data), [featuresApi.data]);
  const disagreements = useMemo(
    () => (features.available ? rankDisagreements(features.features, { minGap: 2 }) : []),
    [features],
  );

  const statsLoading = statistics.loading && !statistics.data;
  const featuresLoading = featuresApi.loading && !featuresApi.data;
  const currency = descriptive.value === 'order_value' ? '£' : null;
  const money = currency ? { currency } : undefined;

  return (
    <div>
      <header className="mb-4">
        <h1 className="text-xl font-semibold text-ink">Statistics &amp; features</h1>
        <p className="mt-1 text-sm text-muted">
          The shape of {fieldText(descriptive.value)}, how it differs across{' '}
          {fieldText(descriptive.group)}, and which variables carry information about demand.
          Both endpoints report their own caveats, and those are reproduced here rather than
          summarised away.
        </p>
        {cacheNote(statistics.data) ? (
          <p className="mt-1 text-xs text-muted">{cacheNote(statistics.data)}</p>
        ) : null}
      </header>

      <div className="grid gap-4 lg:grid-cols-3">
        <ChartFrame
          title={`${fieldLabelText(descriptive.value)}: descriptive statistics`}
          subtitle={`All ${exact(descriptive.n)} observations.`}
          loading={statsLoading}
          error={statistics.error}
          height={300}
          note={
            normality.available
              ? null
              : normality.reason ?? 'The endpoint did not report a shape verdict.'
          }
        >
          <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 py-1 text-xs">
            {[
              ['Observations', exact(descriptive.n)],
              ['Mean', exact(descriptive.mean, { ...money, decimals: 2 })],
              ['Median', exact(descriptive.median, { ...money, decimals: 2 })],
              ['Mean ÷ median', descriptive.meanOverMedian?.toFixed(2) ?? '—'],
              ['Std deviation', exact(descriptive.stdDev, { ...money, decimals: 2 })],
              ['Coefficient of variation', descriptive.coefficientOfVariation?.toFixed(2) ?? '—'],
              ['Q1', exact(descriptive.q1, { ...money, decimals: 2 })],
              ['Q3', exact(descriptive.q3, { ...money, decimals: 2 })],
              ['IQR', exact(descriptive.iqr, { ...money, decimals: 2 })],
              ['Skewness', descriptive.skewness?.toFixed(1) ?? '—'],
              ['Excess kurtosis', compact(descriptive.kurtosisExcess)],
              [
                'Range',
                `${exact(descriptive.min, { ...money, decimals: 2 })} to ${compact(
                  descriptive.max,
                  money,
                )}`,
              ],
            ].map(([label, text]) => (
              <div key={label} className="contents">
                <dt className="text-muted">{label}</dt>
                <dd className="text-right text-ink2 tabular-nums">{text}</dd>
              </div>
            ))}
          </dl>
        </ChartFrame>

        <div className="lg:col-span-2">
          <ChartFrame
            title={`Median ${fieldText(descriptive.value)} by ${fieldText(descriptive.group)}`}
            subtitle="The quantity a rank-based test actually compares."
            loading={statsLoading}
            error={statistics.error}
            empty={!comparison || comparison.groups.length === 0}
            note={comparisonNote(comparison, currency)}
            table={{
              caption: 'Group comparison',
              columns: [
                { key: 'label', label: 'Group' },
                { key: 'n', label: 'n', numeric: true },
                { key: 'median', label: 'Median', numeric: true },
                { key: 'mean', label: 'Mean', numeric: true },
                { key: 'q1', label: 'Q1', numeric: true },
                { key: 'q3', label: 'Q3', numeric: true },
                { key: 'skewness', label: 'Skewness', numeric: true },
              ],
              rows: (comparison?.groups ?? []).map((g) => ({
                key: g.key,
                label: g.label,
                n: exact(g.n),
                median: exact(g.median, { ...money, decimals: 2 }),
                mean: exact(g.mean, { ...money, decimals: 2 }),
                q1: exact(g.q1, { ...money, decimals: 2 }),
                q3: exact(g.q3, { ...money, decimals: 2 }),
                skewness: g.skewness?.toFixed(1) ?? '—',
              })),
            }}
          >
            <ColumnChart
              bins={comparison?.groups ?? []}
              color="var(--series-1)"
              currency={currency}
              valueLabel="Median"
              height={240}
              reference={
                descriptive.median === null
                  ? null
                  : { value: descriptive.median, label: 'Overall median' }
              }
            />
          </ChartFrame>
        </div>

        <div className="lg:col-span-2">
          <TestPanel
            test={comparison?.test}
            comparison={comparison}
            currency={currency}
            loading={statsLoading}
            error={statistics.error}
          />
        </div>

        <ChartFrame
          title="Shape and stationarity"
          subtitle="What the endpoint will and will not assert."
          loading={statsLoading}
          error={statistics.error}
          height={240}
        >
          <div className="space-y-3 py-1 text-xs leading-relaxed">
            {normality.available ? (
              <div>
                <p className="text-muted">Shape verdict</p>
                <p className="mt-0.5 text-base font-semibold text-ink">{normality.verdict}</p>
                {normality.note ? <p className="mt-1 text-muted">{normality.note}</p> : null}
              </div>
            ) : null}
            <div>
              <p className="text-muted">Stationarity</p>
              <p className="mt-0.5 text-sm font-medium text-ink2">
                {stationarity.available ? 'Reported' : 'Not reported'}
              </p>
              {stationarity.reason ? (
                <p className="mt-1 text-muted">{stationarity.reason}</p>
              ) : null}
            </div>
          </div>
        </ChartFrame>

        <div className="lg:col-span-2">
          <ChartFrame
            title="Feature relevance by mutual information"
            subtitle={featuresSubtitle(features)}
            loading={featuresLoading}
            error={featuresApi.error}
            empty={!features.available || features.features.length === 0}
            note={featuresNote(features)}
            table={{
              caption: 'Feature relevance',
              columns: [
                { key: 'label', label: 'Feature' },
                { key: 'knn', label: 'MI (kNN)', numeric: true },
                { key: 'binned', label: 'MI (binned, 5)', numeric: true },
                { key: 'bins', label: 'Across 3/5/10 bins', numeric: true },
                { key: 'rankKnn', label: 'Rank (kNN)', numeric: true },
                { key: 'rankBinned', label: 'Rank (binned)', numeric: true },
              ],
              rows: (features.features ?? []).map((f) => {
                const range = binRange(f);
                return {
                  key: f.key,
                  label: f.label,
                  knn: f.miKnn?.toFixed(3) ?? '—',
                  binned: f.miBinned?.toFixed(3) ?? '—',
                  bins: range ? `${range.low.toFixed(3)} to ${range.high.toFixed(3)}` : '—',
                  rankKnn: exact(f.rankKnn),
                  rankBinned: exact(f.rankBinned),
                };
              }),
            }}
          >
            <BarChart
              rows={features.features ?? []}
              valueLabel="Mutual information"
              maxBarThickness={16}
            />
          </ChartFrame>
        </div>

        <EstimatorPanel
          features={features}
          disagreements={disagreements}
          loading={featuresLoading}
          error={featuresApi.error}
        />

        {features.available && features.limitations.length ? (
          <section className="lg:col-span-3 rounded-lg border border-rule bg-surface p-4">
            <h2 className="text-sm font-semibold text-ink">What these measures cannot tell you</h2>
            <p className="mt-1 text-xs text-muted">
              Reported by the analytics module and reproduced unchanged.
            </p>
            <ul className="mt-3 list-disc space-y-1 pl-4 text-xs leading-relaxed text-muted">
              {features.limitations.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>
    </div>
  );
}

/**
 * The significance test, led by whichever of p-value and effect size is the
 * honest headline.
 *
 * On this dataset the test is significant and the effect is negligible, which
 * is a statement about having 39,529 observations rather than about the
 * quarters. The endpoint says exactly that in `interpretation_note`, and the
 * panel puts it first.
 */
function TestPanel({ test, comparison, currency, loading, error }) {
  return (
    <ChartFrame
      title="Is that difference real, and does it matter?"
      subtitle="Two different questions, answered separately."
      loading={loading}
      error={error}
      empty={!test}
      emptyMessage="This endpoint did not report a significance test."
      height={240}
      note={test?.note}
    >
      {test ? (
        <div className="py-1">
          {test.headline === 'effect' ? (
            <p
              className="rounded border px-3 py-2 text-xs leading-relaxed"
              style={{
                borderColor: 'color-mix(in srgb, var(--chart-warning) 40%, transparent)',
                background: 'color-mix(in srgb, var(--chart-warning) 8%, transparent)',
              }}
            >
              <strong className="font-semibold text-ink">
                Statistically significant, practically negligible.
              </strong>{' '}
              {test.interpretationNote}
              {comparison?.medianSpread !== null && comparison?.medianSpread !== undefined
                ? ` The widest gap between any two group medians is ${exact(
                    comparison.medianSpread,
                    currency ? { currency, decimals: 2 } : { decimals: 2 },
                  )}.`
                : ''}
            </p>
          ) : null}

          <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
            {[
              ['Test', test.name],
              ['Statistic', test.statistic?.toFixed(2) ?? '—'],
              ['Degrees of freedom', exact(test.degreesOfFreedom)],
              ['p-value', formatP(test.pValue)],
              ['Significant at α = ' + (test.alpha ?? 0.05), test.significant ? 'yes' : 'no'],
              [
                test.effect.name ? `Effect size (${test.effect.name})` : 'Effect size',
                test.effect.value === null
                  ? '—'
                  : `${test.effect.value.toFixed(5)}${
                      test.effect.magnitude ? ` · ${test.effect.magnitude}` : ''
                    }`,
              ],
            ].map(([label, text]) => (
              <div key={label} className="contents">
                <dt className="text-muted">{label}</dt>
                <dd className="text-right text-ink2 tabular-nums">{text}</dd>
              </div>
            ))}
          </dl>

          {test.tests || test.assumes ? (
            <p className="mt-3 text-xs leading-relaxed text-muted">
              {test.tests ? `Tests ${test.tests}.` : ''}{' '}
              {test.assumes ? `Assumes ${test.assumes}.` : ''}
            </p>
          ) : null}
        </div>
      ) : null}
    </ChartFrame>
  );
}

/** Where the two mutual-information estimators disagree, and by how much. */
function EstimatorPanel({ features, disagreements, loading, error }) {
  const a = features.rankAgreement ?? {};
  return (
    <ChartFrame
      title="Do the two estimators agree?"
      subtitle="A k-nearest-neighbour estimate against a binned one."
      loading={loading}
      error={error}
      empty={!features.available || !a.available}
      emptyMessage="Rank agreement was not reported."
      height={240}
      note={a.note}
    >
      <div className="py-1">
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
          <div className="contents">
            <dt className="text-muted">Spearman</dt>
            <dd className="text-right text-ink2 tabular-nums">{a.spearman?.toFixed(3) ?? '—'}</dd>
          </div>
          <div className="contents">
            <dt className="text-muted">Kendall</dt>
            <dd className="text-right text-ink2 tabular-nums">{a.kendall?.toFixed(3) ?? '—'}</dd>
          </div>
        </dl>

        {disagreements.length ? (
          <>
            <h3 className="mt-3 text-xs font-semibold text-ink">
              Where they disagree by two places or more
            </h3>
            <ul className="mt-1.5 space-y-1 text-xs text-muted">
              {disagreements.slice(0, 5).map((f) => (
                <li key={f.key} className="flex justify-between gap-2">
                  <span className="text-ink2">{f.label}</span>
                  <span className="tabular-nums">
                    {exact(f.rankKnn)} vs {exact(f.rankBinned)}
                  </span>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="mt-3 text-xs text-muted">
            No feature moves by more than one place between the two estimators.
          </p>
        )}

        <p className="mt-3 text-xs leading-relaxed text-muted">
          {features.modelImportance === null
            ? 'Model-based importance is not reported here; it is produced by the forecasting engine.'
            : 'Model-based importance is reported alongside.'}
        </p>
      </div>
    </ChartFrame>
  );
}

function fieldText(name) {
  return String(name ?? 'the measure').replace(/_/g, ' ');
}

function fieldLabelText(name) {
  const t = fieldText(name);
  return t.charAt(0).toUpperCase() + t.slice(1);
}

/** A p-value small enough to lose its digits is shown as a bound, not as 0. */
function formatP(p) {
  if (p === null || p === undefined) return '—';
  if (p < 0.001) return '< 0.001';
  return p.toFixed(4);
}

function comparisonNote(comparison, currency) {
  if (!comparison?.groups.length) return null;
  const money = currency ? { currency, decimals: 2 } : { decimals: 2 };
  const parts = [];
  if (comparison.medianSpread !== null) {
    parts.push(
      `The four group medians span ${exact(
        comparison.medianSpread,
        money,
      )} between the lowest and the highest.`,
    );
  }
  parts.push(
    'Medians rather than means, because the distribution is strongly right-skewed and a rank-based test compares medians.',
  );
  if (comparison.excludedSmallGroups.length) {
    parts.push(
      `${comparison.excludedSmallGroups.length} group(s) were excluded for having too few observations.`,
    );
  }
  return parts.join(' ');
}

function featuresSubtitle(features) {
  if (!features.available) return null;
  const parts = [`Target: ${fieldText(features.target)}`];
  if (features.topProductsAnalysed) {
    parts.push(`top ${exact(features.topProductsAnalysed)} products`);
  }
  if (features.rowsUsed) parts.push(`${exact(features.rowsUsed)} rows`);
  return `${parts.join(' · ')}.`;
}

function featuresNote(features) {
  if (!features.available) return null;
  const parts = [];
  if (features.targetSubstituted) {
    // The reader asked for one target and the endpoint answered about
    // another. Printing only what came back would hide the substitution.
    parts.push(
      `${fieldLabelText(features.targetRequested)} was requested; the endpoint reports against ${fieldText(
        features.target,
      )}.`,
    );
  }
  if (features.sampled) {
    parts.push(
      `Computed on a sample of ${exact(features.rowsUsed)} of ${exact(
        features.rowsAvailable,
      )} rows.`,
    );
  } else if (features.rowsUsed !== null) {
    parts.push(`Computed on all ${exact(features.rowsUsed)} rows, not a sample.`);
  }
  parts.push(
    'Mutual information is shown in nats and has no upper bound, so the bars are comparable with each other but not with a correlation coefficient.',
  );
  return parts.join(' ');
}

export default StatisticsPage;
