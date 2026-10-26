import { useCallback, useMemo } from 'react';
import { useParams } from 'react-router-dom';

import { BarChart, ChartFrame, LineChart, compact, exact, percent } from '../charts/index.js';
import { FilterBar } from '../components/layout/FilterBar.jsx';
import { KpiCard } from '../components/ui/KpiCard.jsx';
import {
  adaptConcentration,
  adaptFilterOptions,
  adaptKpis,
  adaptRanked,
  adaptRates,
  adaptTrend,
  shapeProblem,
} from '../components/dashboard/adapt.js';
import { boundsOf } from '../hooks/filterState.js';
import { useApi } from '../hooks/useApi.js';
import { useFilters } from '../hooks/useFilters.js';
import { getFilterOptions, getKpis, getProducts, getTrends } from '../services/analytics.js';

/**
 * The dashboard.
 *
 * Three questions in the order a category manager asks them: how did we do,
 * how is it moving, and where does it come from. Everything answers to the
 * single filter row at the top, so the figures always agree with each other.
 */
export function DashboardPage() {
  const { datasetId } = useParams();

  const loadOptions = useCallback(
    (signal) => getFilterOptions(datasetId, { signal }),
    [datasetId],
  );
  const { data: optionsRaw } = useApi(loadOptions);
  const options = useMemo(() => adaptFilterOptions(optionsRaw), [optionsRaw]);
  const bounds = useMemo(() => boundsOf(optionsRaw), [optionsRaw]);

  const { filters, update, reset, query } = useFilters(bounds);

  // The query object is rebuilt on every render, so depending on it directly
  // would re-fetch forever. Serialising gives a value that changes only when
  // the filters actually change.
  const queryKey = useMemo(() => JSON.stringify(query), [query]);

  const loadKpis = useCallback(
    (signal) => getKpis(datasetId, { query, signal }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [datasetId, queryKey],
  );
  const loadTrends = useCallback(
    (signal) => getTrends(datasetId, { query: { ...query, granularity: 'week' }, signal }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [datasetId, queryKey],
  );
  const loadProducts = useCallback(
    (signal) =>
      getProducts(datasetId, {
        query: { ...query, sort: 'net_revenue', order: 'desc', limit: 10 },
        signal,
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [datasetId, queryKey],
  );

  const kpis = useApi(loadKpis);
  const trends = useApi(loadTrends);
  const products = useApi(loadProducts);

  const figures = useMemo(() => adaptKpis(kpis.data), [kpis.data]);
  const rates = useMemo(() => adaptRates(kpis.data), [kpis.data]);
  const trend = useMemo(() => adaptTrend(trends.data), [trends.data]);
  const topProducts = useMemo(() => adaptRanked(products.data), [products.data]);
  const concentration = useMemo(() => adaptConcentration(products.data), [products.data]);

  const trendProblem = trends.data
    ? shapeProblem(trends.data, ['points', 'series', 'rows', 'data', 'periods'])
    : null;
  const productProblem = products.data
    ? shapeProblem(products.data, ['items', 'products', 'rows', 'data'])
    : null;

  return (
    <div>
      <header className="mb-4">
        <h1 className="text-xl font-semibold text-ink">Dashboard</h1>
        <p className="mt-1 text-sm text-muted">
          Headline performance for the selected period. Every figure on this page is computed by
          the same analytics modules the research scripts import, so the dashboard and the report
          cannot disagree.
        </p>
      </header>

      <FilterBar
        filters={filters}
        update={update}
        reset={reset}
        bounds={bounds}
        options={options}
        disabled={kpis.loading && !kpis.data}
      />

      <section
        aria-label="Headline figures"
        className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5"
      >
        {figures.map((f) => (
          <KpiCard
            key={f.key}
            label={f.label}
            value={f.value}
            growth={f.growth}
            currency={f.currency}
            note={f.note}
            unavailableReason={
              f.value === null && !kpis.loading
                ? 'This dataset has no column this figure can be computed from.'
                : null
            }
          />
        ))}
      </section>

      {rates.returnRate !== null || rates.guestShare !== null ? (
        <p className="mb-4 text-xs text-muted">
          {rates.returnRate !== null
            ? `Returns account for ${percent(rates.returnRate)} of gross revenue${
                rates.returnsValue !== null
                  ? ` (${exact(rates.returnsValue, { currency: '£' })})`
                  : ''
              }. `
            : ''}
          {rates.guestShare !== null
            ? `${percent(rates.guestShare)} of revenue comes from orders with no customer identifier, which the pipeline keeps as guest sales rather than discarding.`
            : ''}
        </p>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <ChartFrame
            title="Net revenue by week"
            subtitle="Weeks start on Monday, matching the database's own week boundary."
            loading={trends.loading && !trends.data}
            refreshing={trends.loading && Boolean(trends.data)}
            error={trends.error}
            empty={!trendProblem && trend.x.length === 0}
            note={noteForTrend(trend, trendProblem)}
            table={{
              caption: 'Net revenue by week',
              columns: [
                { key: 'week', label: 'Week beginning' },
                { key: 'revenue', label: 'Net revenue', numeric: true },
                { key: 'orders', label: 'Orders', numeric: true },
              ],
              rows: trend.x.map((week, i) => ({
                key: week,
                week: `${week}${trend.partial[i] ? ' (partial)' : ''}`,
                revenue: exact(trend.revenue[i], { currency: '£' }),
                orders: exact(trend.orders[i]),
              })),
            }}
            series={
              trend.movingAverage.some((v) => Number.isFinite(v))
                ? [
                    { key: 'revenue', label: 'Net revenue', color: 'var(--series-1)' },
                    {
                      key: 'ma',
                      label: 'Moving average',
                      color: 'var(--series-2)',
                      dashed: true,
                    },
                  ]
                : []
            }
          >
            <LineChart
              x={trend.x}
              series={[
                {
                  key: 'revenue',
                  label: 'Net revenue',
                  color: 'var(--series-1)',
                  // A partial final week is a shorter week, not a fall in
                  // trade. It is dropped from the line and named in the note,
                  // because plotting it invites exactly the wrong reading.
                  values: trend.revenue.map((v, i) => (trend.partial[i] ? null : v)),
                },
                ...(trend.movingAverage.some((v) => Number.isFinite(v))
                  ? [
                      {
                        key: 'ma',
                        label: 'Moving average',
                        color: 'var(--series-2)',
                        values: trend.movingAverage,
                        dashed: true,
                      },
                    ]
                  : []),
              ]}
              currency="£"
              height={280}
            />
          </ChartFrame>
        </div>

        <ChartFrame
          title="Revenue concentration"
          subtitle="How much of the total a few products account for."
          loading={products.loading && !products.data}
          error={products.error}
          empty={concentration.gini === null && concentration.topShare === null}
          emptyMessage="This endpoint did not return concentration figures."
          height={180}
          note="A Gini coefficient of 0 would mean every product sells equally; 1 would mean one product is the entire business. Concentration is a reason to check supplier risk, not a fault in itself."
        >
          <dl className="space-y-4 py-4">
            <div>
              <dt className="text-xs text-muted">Gini coefficient</dt>
              <dd className="text-3xl font-semibold text-ink">
                {concentration.gini === null ? '—' : concentration.gini.toFixed(3)}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Share from the top 20% of products</dt>
              <dd className="text-xl font-semibold text-ink">
                {concentration.topShare === null ? '—' : percent(concentration.topShare)}
              </dd>
            </div>
          </dl>
        </ChartFrame>

        <div className="lg:col-span-3">
          <ChartFrame
            title="Top products by net revenue"
            subtitle="The ten largest contributors in the selected period."
            loading={products.loading && !products.data}
            refreshing={products.loading && Boolean(products.data)}
            error={products.error}
            empty={!productProblem && topProducts.length === 0}
            note={
              productProblem ??
              'Product names are the canonical name chosen by the cleaning pipeline, which takes the most frequent description per stock code; variant spellings are counted together.'
            }
            table={{
              caption: 'Top products by net revenue',
              columns: [
                { key: 'label', label: 'Product' },
                { key: 'value', label: 'Net revenue', numeric: true },
                { key: 'share', label: 'Share of total', numeric: true },
              ],
              rows: topProducts.map((r) => ({
                key: r.key,
                label: r.label,
                value: exact(r.value, { currency: '£' }),
                share: r.share === null ? '—' : percent(r.share),
              })),
            }}
          >
            <BarChart rows={topProducts} currency="£" valueLabel="Net revenue" />
          </ChartFrame>
        </div>
      </div>
    </div>
  );
}

/** The note under the trend chart, including anything withheld. */
function noteForTrend(trend, problem) {
  if (problem) return problem;
  const partial = trend.partial.filter(Boolean).length;
  const total = trend.revenue.filter((v) => Number.isFinite(v)).length;
  const parts = [`${total} complete weeks plotted.`];
  if (partial) {
    parts.push(
      `${partial} partial ${partial === 1 ? 'week is' : 'weeks are'} excluded from the line and listed in the table view; a week cut short by the end of the data is a shorter week, not a drop in trade.`,
    );
  }
  const values = trend.revenue.filter((v) => Number.isFinite(v));
  if (values.length > 1) {
    parts.push(
      `Range ${compact(Math.min(...values), { currency: '£' })} to ${compact(Math.max(...values), { currency: '£' })}.`,
    );
  }
  return parts.join(' ');
}

export default DashboardPage;
