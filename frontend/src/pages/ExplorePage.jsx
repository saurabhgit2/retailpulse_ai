import { useCallback, useMemo } from 'react';
import { useParams } from 'react-router';

import {
  ChartFrame,
  ColumnChart,
  LineChart,
  compact,
  dateFull,
  exact,
  percent,
} from '../charts/index.js';
import {
  CALENDAR_DIMENSIONS,
  adaptCalendar,
  adaptRevenueDistribution,
  cacheNote,
  decompositionDiagnostics,
  decompositionSeries,
} from '../components/explore/adaptExplore.js';
import { shareText } from '../components/shared/histogramShape.js';
import { useApi } from '../hooks/useApi.js';
import { getDistributions, getSeasonality } from '../services/analytics.js';

/**
 * Explore.
 *
 * Three questions about shape rather than level: when does this business
 * trade, is there a season underneath the trend, and what does a single line
 * of revenue look like.
 *
 * The decomposition section is the one that matters most and shows the least.
 * A seasonal decomposition will return a seasonal component for any series
 * long enough to admit one, and say nothing about whether it means anything.
 * On two cycles of weekly data it does not, and the page says so with figures
 * rather than drawing a seasonal curve that would be believed.
 */
export function ExplorePage() {
  const { datasetId } = useParams();

  const loadSeasonality = useCallback(
    (signal) => getSeasonality(datasetId, { signal }),
    [datasetId],
  );
  const loadDistributions = useCallback(
    (signal) => getDistributions(datasetId, { signal }),
    [datasetId],
  );

  const seasonality = useApi(loadSeasonality);
  const distributions = useApi(loadDistributions);

  const calendars = useMemo(
    () =>
      CALENDAR_DIMENSIONS.map((d) => ({
        ...d,
        data: adaptCalendar(seasonality.data, d.key),
      })).filter((d) => d.data),
    [seasonality.data],
  );
  const diagnostics = useMemo(
    () => decompositionDiagnostics(seasonality.data),
    [seasonality.data],
  );
  const series = useMemo(() => decompositionSeries(seasonality.data), [seasonality.data]);
  const revenue = useMemo(
    () => adaptRevenueDistribution(distributions.data),
    [distributions.data],
  );

  const seasonalityLoading = seasonality.loading && !seasonality.data;
  const distributionsLoading = distributions.loading && !distributions.data;
  const provenance = cacheNote(seasonality.data);

  return (
    <div>
      <header className="mb-4">
        <h1 className="text-xl font-semibold text-ink">Explore</h1>
        <p className="mt-1 text-sm text-muted">
          When this business trades, whether there is a season underneath the trend, and what a
          single line of revenue looks like. Seasonal indices are relative to an average period,
          so 1.0 is ordinary trade and 1.6 is sixty per cent above it.
        </p>
        {provenance ? <p className="mt-1 text-xs text-muted">{provenance}</p> : null}
      </header>

      <div className="grid gap-4 lg:grid-cols-3">
        {calendars.map((d) => (
          <div key={d.key} className={d.key === 'day_of_week' ? '' : 'lg:col-span-2'}>
            <ChartFrame
              title={d.label}
              subtitle={`Seasonal index of ${(d.data.measure ?? 'revenue').replace(/_/g, ' ')}, against an average ${d.short}.`}
              loading={seasonalityLoading}
              error={seasonality.error}
              empty={d.data.bins.length === 0}
              note={calendarNote(d)}
              table={{
                caption: d.label,
                columns: [
                  { key: 'label', label: d.label },
                  { key: 'index', label: 'Index', numeric: true },
                  { key: 'mean', label: 'Mean', numeric: true },
                  { key: 'total', label: 'Total', numeric: true },
                  { key: 'observations', label: 'Observations', numeric: true },
                  { key: 'reliable', label: 'Reliable' },
                ],
                rows: d.data.bins.map((b) => ({
                  key: b.key,
                  label: b.label,
                  index: b.value.toFixed(3),
                  mean: exact(b.mean, { currency: '£' }),
                  total: exact(b.total, { currency: '£' }),
                  observations: exact(b.observations),
                  reliable: b.reliable ? 'yes' : 'no',
                })),
              }}
            >
              <ColumnChart
                bins={d.data.bins}
                color="var(--series-1)"
                valueLabel="Index"
                height={220}
                reference={{ value: 1, label: 'Average' }}
              />
            </ChartFrame>
          </div>
        ))}

        <div className="lg:col-span-2">
          <ChartFrame
            title="Weekly revenue and its trend"
            subtitle="Observed weekly revenue with the centred moving-average trend."
            loading={seasonalityLoading}
            error={seasonality.error}
            empty={series.x.length === 0}
            note={decompositionNote(diagnostics)}
            series={[
              { key: 'observed', label: 'Observed', color: 'var(--series-1)' },
              { key: 'trend', label: 'Trend', color: 'var(--series-3)' },
            ]}
            table={{
              caption: 'Decomposition',
              columns: [
                { key: 'week', label: 'Week beginning' },
                { key: 'observed', label: 'Observed', numeric: true },
                { key: 'trend', label: 'Trend', numeric: true },
                { key: 'seasonal', label: 'Seasonal', numeric: true },
                { key: 'remainder', label: 'Remainder', numeric: true },
              ],
              rows: series.x.map((week, i) => ({
                key: week,
                week: dateFull(week),
                observed: exact(series.observed[i], { currency: '£' }),
                trend: exact(series.trend[i], { currency: '£' }),
                seasonal: exact(series.seasonal[i], { currency: '£' }),
                remainder: exact(series.remainder[i], { currency: '£' }),
              })),
            }}
          >
            <LineChart
              x={series.x}
              series={[
                { key: 'observed', label: 'Observed', color: 'var(--series-1)', values: series.observed },
                { key: 'trend', label: 'Trend', color: 'var(--series-3)', values: series.trend },
              ]}
              currency="£"
              height={280}
            />
          </ChartFrame>
        </div>

        <ChartFrame
          title="Is the seasonal component usable?"
          subtitle="Checked against the response, not assumed."
          loading={seasonalityLoading}
          error={seasonality.error}
          empty={!diagnostics.available}
          emptyMessage="This dataset is too short for a decomposition."
          height={280}
          note={diagnostics.note}
        >
          <Verdict diagnostics={diagnostics} />
        </ChartFrame>

        <div className="lg:col-span-2">
          <ChartFrame
            title="Revenue per line"
            subtitle="Every line on every invoice, on a logarithmic scale."
            loading={distributionsLoading}
            error={distributions.error}
            empty={!revenue}
            note={revenue ? revenueNote(revenue) : null}
            table={{
              caption: 'Revenue per line',
              columns: [
                { key: 'label', label: 'Bin' },
                { key: 'value', label: 'Lines', numeric: true },
                { key: 'share', label: 'Share', numeric: true },
              ],
              rows: (revenue?.histograms.log.bins ?? []).map((b) => ({
                key: b.key,
                label: b.label,
                value: exact(b.value),
                share: shareText(b.value / (revenue?.histograms.log.coverage.plotted || 1), {
                  decimals: 2,
                }),
              })),
            }}
          >
            {revenue ? (
              <ColumnChart
                bins={revenue.histograms.log.bins}
                color="var(--series-4)"
                valueLabel="Lines"
                height={260}
                formatBin={(b) => b.axis}
              />
            ) : null}
          </ChartFrame>
        </div>

        {revenue ? <RevenueShape revenue={revenue} loading={distributionsLoading} error={distributions.error} /> : null}
      </div>
    </div>
  );
}

/**
 * The decomposition verdict.
 *
 * Deliberately not a chart. The honest output of this analysis on this
 * dataset is a short argument, and drawing a seasonal curve beside it would
 * undo the argument: a reader believes a line.
 */
function Verdict({ diagnostics }) {
  if (!diagnostics.available) return null;
  const d = diagnostics;
  const rows = [
    ['Weekly points', exact(d.points)],
    ['Period', `${exact(d.period)} weeks`],
    ['Complete cycles', d.cycles?.toFixed(1) ?? '—'],
    ['Trend points', exact(d.trendPoints)],
    ['Observations per seasonal phase', d.observationsPerPhase?.toFixed(1) ?? '—'],
    ['Seasonal strength', d.seasonalStrength === null ? 'not reported' : d.seasonalStrength.toFixed(3)],
  ];

  return (
    <div className="py-1">
      <p
        className="rounded border px-3 py-2 text-xs leading-relaxed"
        style={{
          borderColor: 'color-mix(in srgb, var(--chart-warning) 40%, transparent)',
          background: 'color-mix(in srgb, var(--chart-warning) 8%, transparent)',
        }}
      >
        <strong className="font-semibold text-ink">Not usable as a seasonal estimate.</strong>{' '}
        {d.observationsPerPhase !== null && d.observationsPerPhase <= 1.0001
          ? `The centred ${exact(d.period)}-week average consumes half a period at each end, leaving ${exact(
              d.trendPoints,
            )} trend points for ${exact(
              d.period,
            )} phases. Each seasonal phase therefore rests on a single observation, not an average of several.`
          : `Each seasonal phase rests on about ${d.observationsPerPhase?.toFixed(
              1,
            )} observations, which is too few to separate season from noise.`}
        {d.remainderDegenerate
          ? ' The residual confirms it: every remainder is the same number, so the seasonal component absorbed the whole detrended series and nothing was left over. A decomposition whose residual never varies has not separated anything.'
          : ''}
      </p>

      <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
        {rows.map(([label, text]) => (
          <div key={label} className="contents">
            <dt className="text-muted">{label}</dt>
            <dd className="text-right text-ink2 tabular-nums">{text}</dd>
          </div>
        ))}
      </dl>

      <p className="mt-3 text-xs leading-relaxed text-muted">
        The trend is still sound and is plotted. The seasonal and remainder series are in the
        table view, where they can be inspected without being presented as a result.
      </p>
    </div>
  );
}

/** Spread and tails for the revenue-per-line distribution. */
function RevenueShape({ revenue, loading, error }) {
  const s = revenue.summary ?? {};
  const o = revenue.outliers ?? {};
  const money = { currency: '£' };
  const rows = [
    ['Lines', exact(revenue.count)],
    ['Mean', exact(s.mean, { ...money, decimals: 2 })],
    ['Median', exact(s.median, { ...money, decimals: 2 })],
    ['IQR', exact(s.iqr, { ...money, decimals: 2 })],
    ['Skewness', s.skewness?.toFixed(1) ?? '—'],
    ['Excess kurtosis', compact(s.kurtosis_excess)],
    ['Range', `${exact(s.min, { ...money, decimals: 2 })} to ${compact(s.max, money)}`],
  ];

  return (
    <ChartFrame
      title="Revenue per line: shape and spread"
      subtitle="The numbers the histogram is a picture of."
      loading={loading}
      error={error}
      height={260}
      note={`Tukey's rule flags ${exact(o.tukey_count)} lines above ${exact(o.tukey_upper_fence, {
        ...money,
        decimals: 2,
      })}, which is ${percent(
        (o.tukey_count ?? 0) / (revenue.count || 1),
      )} of all lines. On a distribution this skewed the fence says more about the skew than about any individual line, which is why ${
        o.note ? o.note.charAt(0).toLowerCase() + o.note.slice(1) : 'outliers are flagged, not removed'
      }`}
    >
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 py-1 text-xs">
        {rows.map(([label, text]) => (
          <div key={label} className="contents">
            <dt className="text-muted">{label}</dt>
            <dd className="text-right text-ink2 tabular-nums">{text}</dd>
          </div>
        ))}
      </dl>

      <table className="mt-3 w-full text-xs">
        <caption className="pb-1 text-left text-muted">Percentiles</caption>
        <thead>
          <tr className="border-b border-rule">
            {revenue.percentiles.map((p) => (
              <th key={p.key} scope="col" className="py-1 text-right font-medium text-muted">
                {p.p}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr>
            {revenue.percentiles.map((p) => (
              <td key={p.key} className="py-1 text-right text-ink2 tabular-nums">
                {exact(p.value, { currency: '£', decimals: 2 })}
              </td>
            ))}
          </tr>
        </tbody>
      </table>
    </ChartFrame>
  );
}

function calendarNote({ data, short }) {
  if (!data?.bins.length) return null;
  const reliable = data.bins.filter((b) => b.reliable);
  if (!reliable.length) return null;
  const peak = reliable.reduce((a, b) => (b.value > a.value ? b : a));
  const trough = reliable.reduce((a, b) => (b.value < a.value ? b : a));

  const parts = [
    `${peak.label} runs at ${peak.value.toFixed(2)} times an average ${short} and ${trough.label} at ${trough.value.toFixed(
      2,
    )}.`,
  ];
  if (data.unreliable.length) {
    parts.push(
      `${data.unreliable
        .map((b) => `${b.label} (${exact(b.observations)} observation${b.observations === 1 ? '' : 's'})`)
        .join(' and ')} ${
        data.unreliable.length === 1 ? 'is' : 'are'
      } plotted but excluded from that comparison: the endpoint marks the index unreliable at this sample size, and it is kept on the chart because near-zero trade is itself a fact about this retailer.`,
    );
  }
  return parts.join(' ');
}

function decompositionNote(d) {
  if (!d?.available) return null;
  return `${exact(d.points)} weekly points, ${d.model} model by ${d.method}. The trend line is a centred ${exact(
    d.period,
  )}-week average, so it is undefined for the first and last ${exact(
    Math.floor((d.period ?? 0) / 2),
  )} weeks and is drawn with those gaps rather than through them.`;
}

function revenueNote(revenue) {
  const linearTop = revenue.histograms.linear.bins[0];
  const plotted = revenue.histograms.linear.coverage.plotted || 1;
  const s = revenue.summary ?? {};
  const parts = [
    `On a linear scale ${shareText(linearTop.value / plotted, { decimals: 3 })} of lines fall in the first of forty bars, which is why this is drawn logarithmically.`,
    `Skewness is ${s.skewness?.toFixed(0)} and excess kurtosis ${compact(
      s.kurtosis_excess,
    )}, both driven by a handful of very large lines against a median of ${exact(s.median, {
      currency: '£',
      decimals: 2,
    })}.`,
  ];
  if (revenue.histograms.log.coverage.missing) {
    parts.push(
      `${revenue.histograms.log.coverage.plotted.toLocaleString('en-NZ')} of ${revenue.count.toLocaleString(
        'en-NZ',
      )} lines are plotted; ${revenue.histograms.log.coverage.missing} falls exactly on the top edge and is lost to floating-point rounding.`,
    );
  }
  return parts.join(' ');
}

export default ExplorePage;
