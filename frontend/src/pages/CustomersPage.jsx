import { useCallback, useMemo } from 'react';
import { useParams } from 'react-router';

import {
  BarChart,
  ChartFrame,
  ColumnChart,
  SlopeChart,
  compact,
  exact,
  percent,
} from '../charts/index.js';
import { KpiCard } from '../components/ui/KpiCard.jsx';
import {
  adaptOverview,
  adaptSegments,
  cacheNote,
  methodNotes,
  monetaryBands,
  recencyBands,
  recencySplit,
  segmentSlope,
  topCustomers,
} from '../components/customers/adaptRfm.js';
import { useApi } from '../hooks/useApi.js';
import { getRfm } from '../services/analytics.js';

/**
 * Customers.
 *
 * The page answers one question in three steps: who are the customers, how
 * unevenly is the money spread across them, and what is the shape of the
 * distribution underneath that. Every figure comes from a single call to
 * `/analytics/rfm`, so nothing on this page can disagree with anything else
 * on it.
 *
 * Two deliberate omissions.
 *
 * There is no filter bar. RFM is defined against the end of the dataset, and
 * a date filter would silently change what "recent" means while leaving the
 * segment labels in place. Scoping that properly is a backend question, not a
 * widget, so the page states its scope instead of offering a control that
 * would quietly lie.
 *
 * And the segments here are score bands, not clusters. The endpoint says so
 * in its own caveats and those are printed at the foot of the page rather
 * than paraphrased, because the k-means segmentation is a separate piece of
 * work with its own stability analysis.
 */
export function CustomersPage() {
  const { datasetId } = useParams();

  const load = useCallback((signal) => getRfm(datasetId, { signal }), [datasetId]);
  const rfm = useApi(load);
  const payload = rfm.data;

  const overview = useMemo(() => adaptOverview(payload), [payload]);
  const segments = useMemo(() => adaptSegments(payload), [payload]);
  const slope = useMemo(() => segmentSlope(segments), [segments]);
  const monetary = useMemo(() => monetaryBands(payload), [payload]);
  const recency = useMemo(() => recencyBands(payload), [payload]);
  const top = useMemo(() => topCustomers(payload, 10), [payload]);
  const notes = useMemo(() => methodNotes(payload), [payload]);
  const provenance = useMemo(() => cacheNote(payload), [payload]);

  const loading = rfm.loading && !payload;
  const dist = overview.distributions ?? {};

  const figures = [
    {
      key: 'customers',
      label: 'Identified customers',
      value: overview.customers,
      note: 'Customers with an identifier on at least one line.',
    },
    {
      key: 'revenue',
      label: 'Revenue attributed',
      value: overview.identifiedRevenue,
      currency: '£',
      note: 'Net revenue that can be traced to a customer.',
    },
    {
      key: 'median-value',
      label: 'Median customer value',
      value: overview.medianMonetary,
      currency: '£',
      note: `Mean is ${compact(dist.monetary?.mean, { currency: '£' })}; the gap is the skew.`,
    },
    {
      key: 'median-orders',
      label: 'Median orders per customer',
      value: overview.medianFrequency,
      note: `90th percentile is ${exact(dist.frequency?.p90)} orders.`,
    },
    {
      key: 'negative',
      label: 'Customers worth less than nothing',
      value: overview.negativeCustomers,
      note: `Returns exceed purchases; the lowest is ${compact(overview.minimumMonetary, {
        currency: '£',
      })}.`,
    },
  ];

  return (
    <div>
      <header className="mb-4">
        <h1 className="text-xl font-semibold text-ink">Customers</h1>
        <p className="mt-1 text-sm text-muted">
          Recency, frequency and monetary value for every identified customer, computed over the
          whole dataset as at {overview.asOf ?? 'the end of the data'}. Recency is measured from
          the end of the data, not from today.
        </p>
        {provenance ? <p className="mt-1 text-xs text-muted">{provenance}</p> : null}
      </header>

      {rfm.error ? (
        <div role="alert" className="mb-4 rounded border border-crit/30 bg-crit/5 p-3 text-sm text-ink">
          <p className="font-medium">Customer analytics could not be loaded.</p>
          <p className="mt-1 text-xs text-muted">{rfm.error.message ?? String(rfm.error)}</p>
        </div>
      ) : null}

      <section aria-label="Headline figures" className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {figures.map((f) => (
          <KpiCard
            key={f.key}
            label={f.label}
            value={f.value}
            currency={f.currency}
            note={f.note}
            unavailableReason={
              f.value === null && !loading ? 'This endpoint did not report the figure.' : null
            }
          />
        ))}
      </section>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <ChartFrame
            title="Where the customers are against where the money is"
            subtitle="Each segment ranked twice: by how many customers it holds, and by how much revenue it carries."
            loading={loading}
            refreshing={rfm.loading && Boolean(payload)}
            error={rfm.error}
            empty={slope.length === 0}
            note={slopeNote(segments)}
            table={{
              caption: 'Segment profile',
              columns: [
                { key: 'label', label: 'Segment' },
                { key: 'customers', label: 'Customers', numeric: true },
                { key: 'customerShare', label: '% of customers', numeric: true },
                { key: 'monetary', label: 'Net revenue', numeric: true },
                { key: 'monetaryShare', label: '% of revenue', numeric: true },
                { key: 'medianMonetary', label: 'Median value', numeric: true },
                { key: 'medianFrequency', label: 'Median orders', numeric: true },
                { key: 'medianRecency', label: 'Median recency', numeric: true },
              ],
              rows: segments.map((s) => ({
                key: s.key,
                label: s.label,
                customers: exact(s.customers),
                customerShare: percent(s.customerShare),
                monetary: exact(s.monetary, { currency: '£' }),
                monetaryShare: percent(s.monetaryShare),
                medianMonetary: exact(s.medianMonetary, { currency: '£' }),
                medianFrequency: exact(s.medianFrequency),
                medianRecency: `${exact(s.medianRecency)} d`,
              })),
            }}
          >
            <SlopeChart
              rows={slope}
              leftLabel="Share of customers"
              rightLabel="Share of revenue"
              emphasis={['champions', 'hibernating']}
              format={(v) => percent(v)}
            />
          </ChartFrame>
        </div>

        <ChartFrame
          title="Concentration"
          subtitle="How unevenly spend is distributed across customers."
          loading={loading}
          error={rfm.error}
          empty={overview.concentration.gini === null}
          emptyMessage="This endpoint did not return concentration figures."
          height={180}
          note={concentrationNote(overview)}
        >
          <dl className="space-y-4 py-2">
            <div>
              <dt className="text-xs text-muted">Gini coefficient</dt>
              <dd className="text-3xl font-semibold text-ink">
                {overview.concentration.gini === null
                  ? '—'
                  : overview.concentration.gini.toFixed(3)}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted">
                Share of revenue from the top{' '}
                {percent(overview.concentration.topFraction, { decimals: 0 })} of customers
              </dt>
              <dd className="text-xl font-semibold text-ink">
                {percent(overview.concentration.topShare)}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Revenue with no customer attached</dt>
              <dd className="text-xl font-semibold text-ink">{percent(overview.guestShare)}</dd>
            </div>
          </dl>
        </ChartFrame>

        <div className="lg:col-span-2">
          <ChartFrame
            title="Customers by net value"
            subtitle="Bands widen as value rises, because the distribution does."
            loading={loading}
            error={rfm.error}
            empty={monetary.bins.every((b) => b.value === 0)}
            note={monetaryNote(dist.monetary, monetary)}
            table={{
              caption: 'Customers by net value',
              columns: [
                { key: 'label', label: 'Net value' },
                { key: 'value', label: 'Customers', numeric: true },
                { key: 'share', label: 'Share', numeric: true },
              ],
              rows: withShares(monetary.bins),
            }}
          >
            <ColumnChart bins={monetary.bins} valueLabel="Customers" height={240} />
          </ChartFrame>
        </div>

        <ChartFrame
          title="Coverage"
          subtitle="What RFM can and cannot see."
          loading={loading}
          error={rfm.error}
          height={240}
          note="Guest sales are excluded from every figure on this page. They are not missing data to be imputed: there is no customer to attribute them to, so they are reported separately rather than guessed at."
        >
          <dl className="space-y-4 py-2">
            <div>
              <dt className="text-xs text-muted">Guest revenue</dt>
              <dd className="text-2xl font-semibold text-ink">
                {compact(overview.guestRevenue, { currency: '£' })}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Guest lines</dt>
              <dd className="text-xl font-semibold text-ink">{compact(overview.guestLines)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Customers scored</dt>
              <dd className="text-xl font-semibold text-ink">{compact(overview.customers)}</dd>
            </div>
          </dl>
        </ChartFrame>

        <div className="lg:col-span-3">
          <ChartFrame
            title="Customers by recency"
            subtitle="Days since each customer last bought, measured from the end of the data."
            loading={loading}
            error={rfm.error}
            empty={recency.bins.every((b) => b.value === 0)}
            note={recencyNote(dist.recency_days, recency.bins)}
            table={{
              caption: 'Customers by recency',
              columns: [
                { key: 'label', label: 'Last purchase' },
                { key: 'value', label: 'Customers', numeric: true },
                { key: 'share', label: 'Share', numeric: true },
              ],
              rows: withShares(recency.bins),
            }}
          >
            <ColumnChart
              bins={recency.bins}
              color="var(--series-3)"
              valueLabel="Customers"
              height={240}
            />
          </ChartFrame>
        </div>

        <div className="lg:col-span-3">
          <ChartFrame
            title="Largest customers by net value"
            subtitle="The ten customers carrying the most revenue, after returns."
            loading={loading}
            error={rfm.error}
            empty={top.length === 0}
            note={topNote(top, overview)}
            table={{
              caption: 'Largest customers by net value',
              columns: [
                { key: 'label', label: 'Customer' },
                { key: 'segment', label: 'Segment' },
                { key: 'value', label: 'Net value', numeric: true },
                { key: 'share', label: 'Share of attributed revenue', numeric: true },
                { key: 'frequency', label: 'Orders', numeric: true },
                { key: 'recency', label: 'Recency', numeric: true },
                { key: 'aov', label: 'Average order', numeric: true },
              ],
              rows: top.map((r) => ({
                key: r.key,
                label: r.label,
                segment: r.segment,
                value: exact(r.value, { currency: '£' }),
                share: percent(r.share, { decimals: 2 }),
                frequency: exact(r.frequency),
                recency: `${exact(r.recency)} d`,
                aov: exact(r.averageOrderValue, { currency: '£' }),
              })),
            }}
          >
            <BarChart rows={top} currency="£" valueLabel="Net value" />
          </ChartFrame>
        </div>
      </div>

      <MethodNotes notes={notes} overview={overview} />
    </div>
  );
}

/**
 * The endpoint's caveats, printed rather than paraphrased.
 *
 * These are the limits of the method, and they belong on the page that shows
 * the method's output. Burying them in a report the reader of this page is
 * not holding would be the wrong place for them.
 */
function MethodNotes({ notes, overview }) {
  if (!notes.caveats.length && !notes.clustering.length) return null;
  return (
    <section className="mt-4 rounded-lg border border-rule bg-surface p-4">
      <h2 className="text-sm font-semibold text-ink">How these figures are defined</h2>

      <dl className="mt-3 grid gap-3 text-xs sm:grid-cols-2">
        <div>
          <dt className="text-muted">Monetary</dt>
          <dd className="text-ink2">{overview.definitions.monetary ?? '—'}</dd>
        </div>
        <div>
          <dt className="text-muted">Frequency</dt>
          <dd className="text-ink2">{overview.definitions.frequency ?? '—'}</dd>
        </div>
      </dl>

      {notes.caveats.length ? (
        <ul className="mt-3 list-disc space-y-1 pl-4 text-xs leading-relaxed text-muted">
          {notes.caveats.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      ) : null}

      {notes.clustering.length ? (
        <>
          <h3 className="mt-4 text-xs font-semibold text-ink">Notes carried forward to clustering</h3>
          <ul className="mt-2 list-disc space-y-1 pl-4 text-xs leading-relaxed text-muted">
            {notes.clustering.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </>
      ) : null}
    </section>
  );
}

/** Bin rows with their share of the total, for a table view. */
function withShares(bins) {
  const total = bins.reduce((sum, b) => sum + b.value, 0);
  return bins.map((b) => ({
    key: b.key,
    label: b.label,
    value: exact(b.value),
    share: total ? percent(b.value / total) : '—',
  }));
}

function slopeNote(segments) {
  if (!segments.length) return null;
  const byCustomers = [...segments].sort((a, b) => b.customers - a.customers);
  const biggest = byCustomers[0];
  const richest = segments[0];
  if (!biggest || !richest) return null;
  return `${biggest.label} is the largest group at ${percent(
    biggest.customerShare,
  )} of customers but carries ${percent(
    biggest.monetaryShare,
  )} of revenue, while ${richest.label.toLowerCase()} is ${percent(
    richest.customerShare,
  )} of customers and ${percent(
    richest.monetaryShare,
  )} of revenue. The labels are conventional shorthand for score bands, not a clustering result.`;
}

function concentrationNote(overview) {
  const c = overview.concentration;
  if (c.gini === null) return null;
  const excluded =
    c.entities !== null && overview.customers !== null ? overview.customers - c.entities : null;
  const parts = [
    'A Gini coefficient of 0 would mean every customer spends the same; 1 would mean one customer is the entire business.',
  ];
  if (c.topCount !== null && c.entities !== null) {
    parts.push(
      `${exact(c.topCount)} of ${exact(c.entities)} customers account for ${percent(c.topShare)}.`,
    );
  }
  if (excluded) {
    parts.push(
      `Computed over customers with a positive net value, so ${excluded} are excluded: a share of the total is not defined for a customer whose returns exceed their purchases.`,
    );
  }
  return parts.join(' ');
}

function monetaryNote(stats, banded) {
  const parts = [];
  if (stats) {
    parts.push(
      `Median ${compact(stats.median, { currency: '£' })} against a mean of ${compact(stats.mean, {
        currency: '£',
      })}, with a skewness of ${stats.skewness?.toFixed(1)}.`,
      `The 90th percentile is ${compact(stats.p90, { currency: '£' })} and the largest single customer is ${compact(
        stats.max,
        { currency: '£' },
      )}.`,
    );
  }
  if (banded?.skipped) {
    parts.push(`${banded.skipped} customers had no computable value and are not plotted.`);
  }
  return parts.join(' ') || null;
}

function recencyNote(stats, bins) {
  const split = recencySplit(bins ?? []);
  const parts = [];
  if (split.recentShare !== null) {
    // The summary statistics describe this distribution badly, so the note
    // quotes the two ends the bars actually show rather than the median,
    // which falls in the trough between them.
    parts.push(
      `${percent(split.recentShare)} of customers bought within 30 days of the end of the data, while ${percent(
        split.dormantShare,
      )} had not bought for more than a year. The two groups are the shape of this chart; the median sits in the dip between them.`,
    );
  }
  if (stats) {
    parts.push(
      `Median ${exact(stats.median)} days, 90th percentile ${exact(stats.p90, { decimals: 0 })} days.`,
      `Skewness is ${stats.skewness?.toFixed(
        2,
      )}, so unlike value and frequency, recency is close to symmetric and does not need a transform before clustering.`,
    );
  }
  return parts.join(' ') || null;
}

function topNote(top, overview) {
  if (!top.length) return null;
  const combined = top.reduce((sum, r) => sum + r.value, 0);
  const total = overview.identifiedRevenue;
  const largest = top[0];
  return `The ten largest customers hold ${
    total ? percent(combined / total) : '—'
  } of attributed revenue between them, and the largest alone holds ${percent(
    largest.share,
  )}. Concentration at this level is a supplier-style risk worth naming, not a fault in itself.`;
}

export default CustomersPage;
