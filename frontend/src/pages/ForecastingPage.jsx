import { useCallback, useMemo, useState } from 'react';
import { useParams } from 'react-router';

import { ChartFrame, LineChart, compact, exact } from '../charts/index.js';
import { ResearchExperiment } from '../components/forecasting/ResearchExperiment.jsx';
import {
  CONFIDENCE,
  MEASURES,
  adaptOutlook,
  errorPhrase,
} from '../components/forecasting/adaptOutlook.js';
import { Badge } from '../components/ui/Badge.jsx';
import { StatTile } from '../components/ui/StatTile.jsx';
import { useApi } from '../hooks/useApi.js';
import { getOutlook } from '../services/forecasts.js';

const signedPercent = (v) =>
  v === null || v === undefined ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(1)}%`;

/**
 * Forecasting: what the next weeks are likely to bring, and how far to trust it.
 *
 * The page answers a planning question first. It shows the coming weeks for
 * revenue or units, the method that produced them and why that method was
 * picked, how the method did over the most recent weeks, and a forecast for
 * each of the best-selling products. The research experiment that the report
 * describes is still here, one click down.
 */
export function ForecastingPage() {
  const { datasetId } = useParams();
  const [measureKey, setMeasureKey] = useState('net_revenue');
  const [showResearch, setShowResearch] = useState(false);

  const load = useCallback((signal) => getOutlook(datasetId, { signal }), [datasetId]);
  const outlook = useApi(load);
  const view = useMemo(() => adaptOutlook(outlook.data), [outlook.data]);

  if (outlook.loading && !view) {
    return (
      <p role="status" className="text-sm text-muted">
        Working out the forecast. The first time takes a few seconds; after that it is instant.
      </p>
    );
  }

  if (outlook.error) {
    return (
      <div role="alert" className="rounded-lg border border-crit/30 bg-crit/5 p-4">
        <h1 className="text-lg font-semibold text-ink">The forecast could not be produced</h1>
        <p className="mt-2 text-sm text-ink-2">
          {outlook.error.message ?? String(outlook.error)}
        </p>
        <button
          type="button"
          onClick={outlook.reload}
          className="mt-3 rounded border border-rule px-2 py-1 text-xs text-muted hover:text-ink"
        >
          Try again
        </button>
      </div>
    );
  }

  const measure = MEASURES.find((m) => m.key === measureKey) ?? MEASURES[0];
  const block = view?.measures?.[measure.key];

  return (
    <div>
      <header className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink">Forecasting</h1>
          <p className="mt-1 max-w-prose text-sm text-muted">
            The next {view?.horizon ?? 12} weeks after {view?.lastPeriod ?? 'the data ends'}, from
            whichever method has been the most accurate over recent weeks.
          </p>
        </div>
        <MeasureToggle value={measure.key} onChange={setMeasureKey} />
      </header>

      {!block?.available ? (
        <p className="rounded border border-rule bg-surface p-3 text-sm text-muted">
          {block?.reason ?? 'There is not enough weekly history to forecast this measure.'}
        </p>
      ) : (
        <MeasureSection block={block} measure={measure} methodNote={view.methodNote} />
      )}

      <ProductsSection rows={view?.products ?? []} note={view?.productNote} />

      <section className="mt-6 border-t border-rule pt-4">
        <button
          type="button"
          onClick={() => setShowResearch((v) => !v)}
          aria-expanded={showResearch}
          className="rounded border border-rule px-3 py-1.5 text-sm text-muted hover:text-ink"
        >
          {showResearch ? 'Hide' : 'Show'} the model comparison experiment (research)
        </button>
        <p className="mt-1 text-xs text-muted">
          The cross-validation experiment from the research report, unchanged.
        </p>
        {showResearch ? (
          <div className="mt-4">
            <ResearchExperiment datasetId={datasetId} />
          </div>
        ) : null}
      </section>
    </div>
  );
}

function MeasureToggle({ value, onChange }) {
  return (
    <div role="group" aria-label="Measure" className="inline-flex rounded border border-rule p-0.5">
      {MEASURES.map((m) => (
        <button
          key={m.key}
          type="button"
          aria-pressed={value === m.key}
          onClick={() => onChange(m.key)}
          className={`rounded px-3 py-1 text-sm ${
            value === m.key ? 'bg-accent text-white' : 'text-muted hover:text-ink'
          }`}
        >
          {m.label}
        </button>
      ))}
    </div>
  );
}

function MeasureSection({ block, measure, methodNote }) {
  const money = measure.currency;
  const fmt = (v) => compact(v, { currency: money });
  const conf = CONFIDENCE[block.accuracy.confidence] ?? CONFIDENCE.unknown;
  const unitWord = money ? '' : ' units';

  return (
    <>
      <section className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile label="Next 4 weeks" value={`${fmt(block.totals.next4)}${unitWord}`} />
        <StatTile
          label={`Next ${block.weeks.length} weeks`}
          value={`${fmt(block.totals.nextHorizon)}${unitWord}`}
          hint={`Last ${block.weeks.length} weeks: ${fmt(block.totals.lastHorizon)}`}
        />
        <StatTile
          label="Vs same weeks last year"
          value={signedPercent(block.totals.changeVsLastYear)}
          hint={block.totals.lastYear !== null ? `Last year: ${fmt(block.totals.lastYear)}` : null}
        />
        <StatTile
          label="Typical error"
          value={block.accuracy.wape === null ? '—' : `±${Math.round(block.accuracy.wape)}%`}
          hint={`${conf.label} confidence · ${block.accuracy.backtests} back-tests`}
        />
      </section>

      <ChartFrame
        title={`${measure.label}: the last year and the next ${block.weeks.length} weeks`}
        subtitle={`Forecast by “${block.model?.label}”. ${
          block.level ? `The band shows where ${Math.round(block.level * 100)}% of its past errors fell.` : ''
        }`}
        series={[
          { key: 'actual', label: 'Actual', color: 'var(--series-1)', mark: 'line' },
          { key: 'point', label: 'Forecast', color: 'var(--series-2)', mark: 'line', dashed: true },
          ...(block.level
            ? [{ key: 'band', label: 'Likely range', color: 'var(--series-2)', mark: 'band' }]
            : []),
        ]}
        note={closedNote(block.closedWeeks)}
        table={{
          caption: `${measure.label} forecast by week`,
          columns: [
            { key: 'week', label: 'Week beginning' },
            { key: 'point', label: 'Forecast', numeric: true },
            { key: 'range', label: 'Likely range', numeric: true },
          ],
          rows: block.weeks.map((w) => ({
            key: w.week,
            week: w.week,
            point: w.closed ? 'Likely closed' : exact(w.point, { currency: money }),
            range: w.closed ? '—' : `${fmt(w.lower)} to ${fmt(w.upper)}`,
          })),
        }}
      >
        <LineChart
          x={block.chart.x}
          series={[
            { key: 'actual', label: 'Actual', color: 'var(--series-1)', values: block.chart.actual },
            {
              key: 'point',
              label: 'Forecast',
              color: 'var(--series-2)',
              values: block.chart.point,
              dashed: true,
            },
          ]}
          band={
            block.level
              ? {
                  lower: block.chart.lower,
                  upper: block.chart.upper,
                  color: 'var(--series-2)',
                  label: 'Likely range',
                }
              : null
          }
          currency={money}
          height={300}
        />
      </ChartFrame>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <MethodCard block={block} note={methodNote} />
        <RecentCheck check={block.recentCheck} money={money} label={measure.label} />
      </div>
    </>
  );
}

function closedNote(weeks) {
  if (!weeks.length) return null;
  return `The business did not trade in the matching week${weeks.length > 1 ? 's' : ''} last year, so ${weeks.join(
    ', ',
  )} ${weeks.length > 1 ? 'are' : 'is'} assumed closed and left out of the line.`;
}

function MethodCard({ block, note }) {
  const best = block.candidates.find((c) => c.chosen);
  const worst = Math.max(...block.candidates.map((c) => c.wape ?? 0), 1);
  return (
    <section className="rounded-lg border border-rule bg-surface p-4">
      <h2 className="text-sm font-semibold text-ink">Why this method</h2>
      <p className="mt-2 text-sm text-ink-2">
        <span className="font-medium text-ink">{block.model?.label}.</span>{' '}
        {block.model?.explanation} Over the last {block.accuracy.backtests} back-tests it was{' '}
        {errorPhrase(best?.wape)}, the most accurate of the {block.candidates.length} methods
        tried.
      </p>
      <table className="chart-table mt-3 w-full text-left text-xs">
        <caption className="sr-only">Typical error of each method in back-tests</caption>
        <thead>
          <tr className="border-b border-rule text-muted">
            <th scope="col" className="py-1 pr-2 font-medium">Method</th>
            <th scope="col" className="py-1 pr-2 font-medium">Typical error</th>
          </tr>
        </thead>
        <tbody>
          {block.candidates.map((c) => (
            <tr key={c.name} className={`border-b border-rule/50 ${c.chosen ? 'font-semibold text-ink' : 'text-ink-2'}`}>
              <td className="py-1 pr-2">
                {c.label}
                {c.chosen ? <Badge tone="accent" className="ml-2">Used</Badge> : null}
                {c.flat ? <span className="ml-2 text-muted">(flat line)</span> : null}
              </td>
              <td className="py-1 pr-2">
                <div className="flex items-center gap-2">
                  <span
                    aria-hidden="true"
                    className="inline-block h-1.5 rounded"
                    style={{
                      width: `${Math.max(4, ((c.wape ?? 0) / worst) * 96)}px`,
                      background: c.chosen ? 'var(--series-2)' : 'var(--chart-axis)',
                    }}
                  />
                  <span className="tabular-nums">{c.wape === null ? '—' : `${c.wape.toFixed(1)}%`}</span>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {note ? <p className="mt-3 text-xs text-muted">{note}</p> : null}
    </section>
  );
}

function RecentCheck({ check, money, label }) {
  if (!check) return null;
  return (
    <ChartFrame
      title="How it did over the most recent weeks"
      subtitle={`Forecast made using only the data before ${check.periods[0]}, against what actually happened.`}
      series={[
        { key: 'actual', label: 'Actual', color: 'var(--series-1)', mark: 'line' },
        { key: 'forecast', label: 'Forecast', color: 'var(--series-2)', mark: 'line', dashed: true },
      ]}
      note={check.wape === null ? null : `Over these weeks it was off by ${check.wape.toFixed(1)}% in total.`}
      table={{
        caption: `${label}: recent forecast against actual`,
        columns: [
          { key: 'week', label: 'Week beginning' },
          { key: 'actual', label: 'Actual', numeric: true },
          { key: 'forecast', label: 'Forecast', numeric: true },
        ],
        rows: check.periods.map((week, i) => ({
          key: week,
          week,
          actual: check.actual[i] === null ? 'Closed' : exact(check.actual[i], { currency: money }),
          forecast: exact(check.forecast[i], { currency: money }),
        })),
      }}
    >
      <LineChart
        x={check.periods}
        series={[
          { key: 'actual', label: 'Actual', color: 'var(--series-1)', values: check.actual },
          {
            key: 'forecast',
            label: 'Forecast',
            color: 'var(--series-2)',
            values: check.forecast,
            dashed: true,
          },
        ]}
        currency={money}
        height={220}
        includeZero={false}
      />
    </ChartFrame>
  );
}

function ProductsSection({ rows, note }) {
  const [open, setOpen] = useState(null);
  if (!rows.length) return null;
  const selected = rows.find((r) => r.code === open) ?? null;

  return (
    <section className="mt-6 rounded-lg border border-rule bg-surface p-4">
      <h2 className="text-sm font-semibold text-ink">Top products: units expected</h2>
      {note ? <p className="mt-1 text-xs text-muted">{note}</p> : null}
      <div className="mt-3 overflow-x-auto">
        <table className="chart-table w-full min-w-[640px] text-left text-xs">
          <caption className="sr-only">Unit forecast for the top products</caption>
          <thead>
            <tr className="border-b border-rule text-muted">
              <th scope="col" className="py-1 pr-2 font-medium">Product</th>
              <th scope="col" className="py-1 pr-2 text-right font-medium">Last 12 wks</th>
              <th scope="col" className="py-1 pr-2 text-right font-medium">Next 4 wks</th>
              <th scope="col" className="py-1 pr-2 text-right font-medium">Next 12 wks</th>
              <th scope="col" className="py-1 pr-2 text-right font-medium">Change</th>
              <th scope="col" className="py-1 pr-2 font-medium">Confidence</th>
              <th scope="col" className="py-1 font-medium"><span className="sr-only">Chart</span></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const conf = CONFIDENCE[r.confidence] ?? CONFIDENCE.unknown;
              return (
                <tr key={r.code} className="border-b border-rule/50 text-ink-2">
                  <td className="py-1.5 pr-2">
                    <span className="text-ink">{r.description}</span>
                    <span className="ml-1 font-mono text-[11px] text-muted">{r.code}</span>
                  </td>
                  <td className="py-1.5 pr-2 text-right tabular-nums">{exact(r.lastHorizon)}</td>
                  <td className="py-1.5 pr-2 text-right tabular-nums">{exact(r.next4)}</td>
                  <td className="py-1.5 pr-2 text-right font-medium text-ink tabular-nums">
                    {exact(r.nextHorizon)}
                  </td>
                  <td className="py-1.5 pr-2 text-right tabular-nums">{signedPercent(r.changeVsRecent)}</td>
                  <td className="py-1.5 pr-2">
                    <Badge tone={conf.tone} title={errorPhrase(r.wape)}>{conf.label}</Badge>
                  </td>
                  <td className="py-1.5">
                    <button
                      type="button"
                      aria-expanded={open === r.code}
                      onClick={() => setOpen(open === r.code ? null : r.code)}
                      className="rounded border border-rule px-2 py-0.5 text-[11px] text-muted hover:text-ink"
                    >
                      {open === r.code ? 'Hide' : 'Chart'}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-muted">
        Change compares the next 12 weeks with the last 12. Confidence comes from how far off each
        product&rsquo;s forecast was in back-tests: high is within 15%, medium within 30%.
      </p>

      {selected?.view?.available ? (
        <div className="mt-4">
          <ChartFrame
            title={`${selected.description}: units, recent weeks and forecast`}
            subtitle={`Method: ${selected.model}. ${errorPhrase(selected.wape)} in back-tests.`}
            series={[
              { key: 'actual', label: 'Actual', color: 'var(--series-1)', mark: 'line' },
              { key: 'point', label: 'Forecast', color: 'var(--series-2)', mark: 'line', dashed: true },
              { key: 'band', label: 'Likely range', color: 'var(--series-2)', mark: 'band' },
            ]}
          >
            <LineChart
              x={selected.view.chart.x}
              series={[
                { key: 'actual', label: 'Actual', color: 'var(--series-1)', values: selected.view.chart.actual },
                {
                  key: 'point',
                  label: 'Forecast',
                  color: 'var(--series-2)',
                  values: selected.view.chart.point,
                  dashed: true,
                },
              ]}
              band={
                selected.view.level
                  ? {
                      lower: selected.view.chart.lower,
                      upper: selected.view.chart.upper,
                      color: 'var(--series-2)',
                      label: 'Likely range',
                    }
                  : null
              }
              height={220}
            />
          </ChartFrame>
        </div>
      ) : null}
    </section>
  );
}

export default ForecastingPage;
