import { useCallback, useMemo, useState } from 'react';
import { useParams } from 'react-router';

import { ChartFrame, ColumnChart, compact, exact, percent } from '../charts/index.js';
import { KpiCard } from '../components/ui/KpiCard.jsx';
import {
  BASKET_FIELDS,
  adaptBaskets,
  adaptField,
  cacheNote,
  dominantBinShare,
  edgeText,
} from '../components/baskets/adaptBaskets.js';
import { useApi } from '../hooks/useApi.js';
import { getBasketSizes } from '../services/analytics.js';

/**
 * Baskets.
 *
 * Two distributions: how many distinct items an invoice carries, and what an
 * invoice is worth. Both are strongly right-skewed, and the page is built
 * around that fact rather than in spite of it.
 *
 * Association rules are not here. The API exposes no mining endpoint, so the
 * rules from RQ3 are research output and are reported as such; this page is
 * the basket evidence the API can actually serve.
 */
export function BasketsPage() {
  const { datasetId } = useParams();

  const load = useCallback((signal) => getBasketSizes(datasetId, { signal }), [datasetId]);
  const baskets = useApi(load);
  const payload = baskets.data;

  const overview = useMemo(() => adaptBaskets(payload), [payload]);
  const fields = useMemo(
    () => BASKET_FIELDS.map((f) => adaptField(payload, f.key)).filter(Boolean),
    [payload],
  );
  const provenance = useMemo(() => cacheNote(payload), [payload]);

  const loading = baskets.loading && !payload;
  const items = fields.find((f) => f.key === 'distinct_items_per_invoice');
  const value = fields.find((f) => f.key === 'order_value');

  const figures = [
    {
      key: 'invoices',
      label: 'Invoices',
      value: overview.invoices,
      note: 'Every transaction with at least one line.',
    },
    {
      key: 'median-items',
      label: 'Median distinct items',
      value: items?.summary?.median ?? null,
      note: `Mean is ${exact(items?.summary?.mean, { decimals: 1 })}; the gap is the skew.`,
    },
    {
      key: 'p95-items',
      label: '95th percentile items',
      value: items?.percentiles?.find((p) => p.p === 95)?.value ?? null,
      note: 'One invoice in twenty is larger than this.',
    },
    {
      key: 'median-value',
      label: 'Median order value',
      value: value?.summary?.median ?? null,
      currency: '£',
      note: `Mean is ${compact(value?.summary?.mean, { currency: '£' })}.`,
    },
    {
      key: 'max-value',
      label: 'Largest single order',
      value: value?.summary?.max ?? null,
      currency: '£',
      note: 'Flagged as an outlier, not removed.',
    },
  ];

  return (
    <div>
      <header className="mb-4">
        <h1 className="text-xl font-semibold text-ink">Baskets</h1>
        <p className="mt-1 text-sm text-muted">
          What a transaction looks like on this dataset: how many distinct products it carries and
          what it is worth. Both distributions are strongly right-skewed, which is a finding about
          the customer base rather than a problem to be cleaned away.
        </p>
        {provenance ? <p className="mt-1 text-xs text-muted">{provenance}</p> : null}
      </header>

      {baskets.error ? (
        <div role="alert" className="mb-4 rounded border border-crit/30 bg-crit/5 p-3 text-sm text-ink">
          <p className="font-medium">Basket analytics could not be loaded.</p>
          <p className="mt-1 text-xs text-muted">{baskets.error.message ?? String(baskets.error)}</p>
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

      {overview.interpretation ? (
        <section className="mb-4 rounded-lg border border-rule bg-surface p-4">
          <h2 className="text-xs font-semibold tracking-wider text-muted uppercase">
            What the backend reads into this
          </h2>
          <p className="mt-2 text-sm leading-relaxed text-ink2">{overview.interpretation}</p>
          <p className="mt-2 text-xs text-muted">
            Carried through from the analytics module unchanged. It is an interpretation offered
            with its source, not a result, and the figure it rests on is on this page to be checked
            against.
          </p>
        </section>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-3">
        {fields.map((field) => (
          <FieldSection key={field.key} field={field} loading={loading} error={baskets.error} />
        ))}
      </div>
    </div>
  );
}

/**
 * One field: its histogram, and the numbers that describe its shape.
 *
 * The scale toggle is a real control rather than decoration. The linear view
 * is not a worse drawing of the same thing, it is the evidence for why the
 * log view is being shown, and a reader who wants to check that the choice
 * was warranted can do it in one click instead of taking it on trust.
 */
function FieldSection({ field, loading, error }) {
  const [scale, setScale] = useState(field.defaultScale);
  const histogram = field.histograms[scale] ?? field.histograms.linear;
  const share = dominantBinShare(histogram.bins);

  return (
    <>
      <div className="lg:col-span-2">
        <ChartFrame
          title={field.label}
          subtitle={
            scale === 'log'
              ? 'Bin widths grow geometrically, so the whole range is visible at once.'
              : 'Equal-width bins across the full range.'
          }
          loading={loading}
          error={error}
          empty={histogram.bins.every((b) => b.value === 0)}
          note={fieldNote(field, scale, histogram, share)}
          actions={
            <div className="flex overflow-hidden rounded border border-rule text-xs">
              {['linear', 'log'].map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => setScale(option)}
                  aria-pressed={scale === option}
                  className={`px-2 py-1 ${
                    scale === option ? 'bg-accent-soft font-semibold text-accent' : 'text-muted hover:text-ink'
                  }`}
                >
                  {option === 'log' ? 'Log' : 'Linear'}
                </button>
              ))}
            </div>
          }
          table={{
            caption: `${field.label} by bin`,
            columns: [
              { key: 'label', label: 'Bin' },
              { key: 'value', label: 'Invoices', numeric: true },
              { key: 'share', label: 'Share', numeric: true },
            ],
            rows: histogram.bins.map((b) => ({
              key: b.key,
              label: b.label,
              value: exact(b.value),
              share: histogram.coverage.plotted
                ? percent(b.value / histogram.coverage.plotted, { decimals: 2 })
                : '—',
            })),
          }}
        >
          <ColumnChart
            bins={histogram.bins}
            color={field.key === 'order_value' ? 'var(--series-4)' : 'var(--series-1)'}
            valueLabel="Invoices"
            height={260}
            formatBin={(b) => b.axis}
          />
        </ChartFrame>
      </div>

      <ShapeCard field={field} loading={loading} error={error} />
    </>
  );
}

/** The numbers behind the shape: spread, tails and the outlier fences. */
function ShapeCard({ field, loading, error }) {
  const s = field.summary ?? {};
  const o = field.outliers ?? {};
  const c = field.currency;
  const money = c ? { currency: c } : undefined;

  const stats = [
    ['Mean', exact(s.mean, { ...money, decimals: c ? 2 : 1 })],
    ['Median', exact(s.median, money)],
    ['Std deviation', exact(s.std_dev, { ...money, decimals: c ? 2 : 1 })],
    ['Coefficient of variation', s.coefficient_of_variation?.toFixed(2) ?? '—'],
    ['IQR', exact(s.iqr, money)],
    ['Skewness', s.skewness?.toFixed(2) ?? '—'],
    ['Excess kurtosis', s.kurtosis_excess?.toFixed(1) ?? '—'],
    ['Range', `${edgeText(s.min, field.currency)} to ${edgeText(s.max, field.currency)}`],
  ];

  const wanted = [25, 50, 75, 90, 95, 99];
  const quantiles = field.percentiles.filter((p) => wanted.includes(p.p));

  return (
    <ChartFrame
      title={`${field.short}: shape and spread`}
      subtitle="The numbers the histogram is a picture of."
      loading={loading}
      error={error}
      height={260}
      note={outlierNote(o, field)}
    >
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 py-1 text-xs">
        {stats.map(([label, text]) => (
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
            {quantiles.map((p) => (
              <th key={p.key} scope="col" className="py-1 text-right font-medium text-muted">
                {p.p}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr>
            {quantiles.map((p) => (
              <td key={p.key} className="py-1 text-right text-ink2 tabular-nums">
                {exact(p.value, field.currency ? { currency: field.currency } : undefined)}
              </td>
            ))}
          </tr>
        </tbody>
      </table>
    </ChartFrame>
  );
}

function fieldNote(field, scale, histogram, share) {
  const parts = [];
  const s = field.summary ?? {};

  if (share !== null) {
    parts.push(
      `The tallest bar holds ${percent(share)} of invoices on this scale.`,
    );
  }
  if (scale === 'linear' && field.stronglySkewed) {
    parts.push(
      `Skewness is ${s.skewness?.toFixed(
        1,
      )}, so equal-width bins spend most of the axis on a range almost nothing falls in. The log view is the readable one; this view is the reason why.`,
    );
  }
  if (scale === 'log') {
    parts.push(
      'Bin widths grow geometrically, so a bar near the left covers a narrow range and one near the right covers a wide one. Bar heights are counts and remain comparable; bar areas are not.',
    );
    if (histogram.gaps) {
      // Only an integer-valued field earns the granularity explanation. Order
      // value is continuous, so an empty bin there is simply an interval no
      // invoice fell in, and saying otherwise would be inventing a cause.
      parts.push(
        field.integer
          ? `${histogram.gaps} bins inside the range are empty. That is an artefact of the scale rather than the data: this variable takes whole-number values, and a bin narrower than one unit cannot contain an observation.`
          : `${histogram.gaps} ${
              histogram.gaps === 1 ? 'bin inside the range is' : 'bins inside the range are'
            } empty: no invoice falls in that interval.`,
      );
    }
  }
  if (histogram.coverage.missing) {
    parts.push(
      `${histogram.coverage.plotted.toLocaleString('en-NZ')} of ${histogram.coverage.total.toLocaleString(
        'en-NZ',
      )} invoices are plotted; ${histogram.coverage.missing} falls exactly on the top edge and is lost to floating-point rounding.`,
    );
  }
  return parts.join(' ') || null;
}

function outlierNote(outliers, field) {
  const upper = outliers?.tukey_upper_fence;
  const count = outliers?.tukey_count;
  const robust = outliers?.robust_z_count;
  if (upper === undefined || count === undefined) return null;
  const money = field.currency ? { currency: field.currency } : undefined;
  const parts = [
    `Tukey's rule puts the upper fence at ${exact(upper, money)} and flags ${exact(
      count,
    )} invoices above it; a robust z-score at 3.5 flags ${exact(robust)}.`,
  ];
  if (outliers.tukey_lower_fence !== undefined && outliers.tukey_lower_fence < 0) {
    parts.push(
      `The lower fence is negative, which this variable cannot be, so nothing is flagged at the bottom.`,
    );
  }
  if (outliers.note) parts.push(outliers.note);
  return parts.join(' ');
}

export default BasketsPage;
