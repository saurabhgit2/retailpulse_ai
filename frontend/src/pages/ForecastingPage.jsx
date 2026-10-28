import { useCallback, useMemo, useState } from 'react';
import { useParams } from 'react-router';

import {
  ChartFrame,
  LineChart,
  SlopeChart,
  compact,
  exact,
  percent,
} from '../charts/index.js';
import { adaptRun, isFinished } from '../components/forecasting/adaptRun.js';
import { useApi } from '../hooks/useApi.js';
import { usePolling } from '../hooks/usePolling.js';
import { getLatest, getRun, startRun } from '../services/forecasts.js';

const wape = (v) => (v === null || v === undefined ? '—' : `${v.toFixed(2)}%`);

/**
 * The forecasting experiment.
 *
 * The page shows a completed run rather than inviting one: a run takes about
 * two minutes, and the figures in the report come from runs already recorded.
 * Starting one is available and is not the default path.
 *
 * What it is built to make visible, in order: which model was selected and on
 * what evidence, what that model actually predicted against what happened,
 * and whether the ranking that chose it survived contact with the hold-out.
 * That last one is the finding, so it gets a chart rather than a table.
 */
export function ForecastingPage() {
  const { datasetId } = useParams();
  const [startedId, setStartedId] = useState(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState(null);

  const loadLatest = useCallback(
    (signal) => getLatest(datasetId, { signal }),
    [datasetId],
  );
  const latest = useApi(loadLatest);

  // While a run we started is in flight, poll it. usePolling chains timeouts
  // rather than using an interval, so a slow response cannot stack up behind
  // itself, which is the same machinery the upload wizard uses.
  const poll = useCallback(
    () => getRun(datasetId, startedId),
    [datasetId, startedId],
  );
  const polled = usePolling(startedId ? poll : null, isFinished, 4000);

  const run = useMemo(
    () => adaptRun(polled.data) ?? adaptRun(latest.data),
    [polled.data, latest.data],
  );

  async function onStart() {
    setStarting(true);
    setStartError(null);
    try {
      const accepted = await startRun(datasetId);
      setStartedId(accepted?.id ?? null);
    } catch (error) {
      setStartError(error);
    } finally {
      setStarting(false);
    }
  }

  const waiting = Boolean(startedId) && !isFinished(polled.data);

  if (latest.loading && !run) {
    return <p className="text-sm text-muted">Loading the most recent experiment…</p>;
  }

  if (!run) {
    return (
      <Empty onStart={onStart} starting={starting || waiting} error={startError ?? latest.error} />
    );
  }

  if (run.status === 'failed') {
    return (
      <div role="alert" className="rounded-lg border border-crit/30 bg-crit/5 p-4">
        <h1 className="text-lg font-semibold text-ink">The experiment failed</h1>
        <p className="mt-2 text-sm text-ink2">{run.error ?? 'No reason was recorded.'}</p>
      </div>
    );
  }

  const slope = run.models
    .filter((m) => m.cvRank !== null && m.holdoutRank !== null)
    .map((m) => ({
      key: m.model,
      label: m.model.replace(/_/g, ' '),
      leftRank: m.cvRank,
      rightRank: m.holdoutRank,
      leftValue: m.cvWape,
      rightValue: m.holdoutWape,
    }));

  const best = run.models.reduce(
    (a, b) => (b.holdoutWape !== null && (a === null || b.holdoutWape < a.holdoutWape) ? b : a),
    null,
  );

  return (
    <div>
      <header className="mb-4">
        <h1 className="text-xl font-semibold text-ink">Forecasting</h1>
        <p className="mt-1 text-sm text-muted">
          Eight approaches compared on {run.granularity}ly {String(run.valueColumn).replace(/_/g, ' ')},
          selected on rolling-origin cross-validation and then scored once on a hold-out period
          the selection never saw.
        </p>
      </header>

      {waiting ? (
        <p role="status" className="mb-4 rounded border border-rule bg-surface p-3 text-sm text-muted">
          A new experiment is running. This takes about two minutes; the results below are from the
          previous run until it finishes.
        </p>
      ) : null}

      <section className="mb-4 grid gap-3 sm:grid-cols-3">
        <Figure label="Selected on cross-validation" value={run.selection.model?.replace(/_/g, ' ')} />
        <Figure label="Best on the hold-out" value={best?.model.replace(/_/g, ' ')} sub={wape(best?.holdoutWape)} />
        <Figure
          label="Rank agreement between the two"
          value={run.rankCorrelation === null ? '—' : run.rankCorrelation.toFixed(2)}
          sub="Spearman, −1 to 1"
        />
      </section>

      {run.selection.note ? (
        <p className="mb-4 text-xs text-muted">{run.selection.note}</p>
      ) : null}

      {run.forecast ? (
        <ChartFrame
          title={`What ${run.forecast.model?.replace(/_/g, ' ')} predicted, against what happened`}
          subtitle={`The hold-out period, scored once. Band is the ${percent(run.forecast.level, {
            decimals: 0,
          })} prediction interval.`}
          series={[
            { key: 'actual', label: 'Actual', color: 'var(--series-1)', mark: 'line' },
            { key: 'point', label: 'Forecast', color: 'var(--series-2)', mark: 'line', dashed: true },
            {
              key: 'band',
              label: `${percent(run.forecast.level, { decimals: 0 })} interval`,
              color: 'var(--series-2)',
              mark: 'band',
            },
          ]}
          note={forecastNote(run.forecast)}
          table={{
            caption: 'Forecast against actual over the hold-out period',
            columns: [
              { key: 'week', label: 'Week beginning' },
              { key: 'actual', label: 'Actual', numeric: true },
              { key: 'point', label: 'Forecast', numeric: true },
              { key: 'interval', label: 'Interval', numeric: true },
              { key: 'inside', label: 'Covered' },
            ],
            rows: run.forecast.periods.map((week, i) => ({
              key: week,
              week,
              actual: exact(run.forecast.actual[i], { currency: '£' }),
              point: exact(run.forecast.point[i], { currency: '£' }),
              interval: `${compact(run.forecast.lower[i], { currency: '£' })} to ${compact(
                run.forecast.upper[i],
                { currency: '£' },
              )}`,
              inside:
                run.forecast.actual[i] >= run.forecast.lower[i] &&
                run.forecast.actual[i] <= run.forecast.upper[i]
                  ? 'yes'
                  : 'no',
            })),
          }}
        >
          <LineChart
            x={run.forecast.periods}
            series={[
              {
                key: 'actual',
                label: 'Actual',
                color: 'var(--series-1)',
                values: run.forecast.actual,
              },
              {
                key: 'point',
                label: 'Forecast',
                color: 'var(--series-2)',
                values: run.forecast.point,
                dashed: true,
              },
            ]}
            band={{
              lower: run.forecast.lower,
              upper: run.forecast.upper,
              color: 'var(--series-2)',
              label: `${percent(run.forecast.level, { decimals: 0 })} interval`,
            }}
            currency="£"
            height={280}
            includeZero={false}
          />
        </ChartFrame>
      ) : null}

      <div className="mt-4">
        <ChartFrame
          title="How the ranking changed between the two stages"
          subtitle="Each line is one approach, from where cross-validation placed it to where the hold-out did."
          note={rankNote(run)}
          table={{
            caption: 'Model results',
            columns: [
              { key: 'model', label: 'Model' },
              { key: 'cv', label: 'Cross-validation', numeric: true },
              { key: 'cvRank', label: 'Rank', numeric: true },
              { key: 'ho', label: 'Hold-out', numeric: true },
              { key: 'hoRank', label: 'Rank', numeric: true },
              { key: 'worst', label: 'Worst fold', numeric: true },
            ],
            rows: run.models.map((m) => ({
              key: m.model,
              model: `${m.model.replace(/_/g, ' ')}${m.usesExogenous ? ' (sees other series)' : ''}`,
              cv: wape(m.cvWape),
              cvRank: m.cvRank ?? '—',
              ho: wape(m.holdoutWape),
              hoRank: m.holdoutRank ?? '—',
              worst: wape(m.cvWorst),
            })),
          }}
        >
          <SlopeChart
            rows={slope}
            leftLabel="Cross-validation"
            rightLabel="Locked hold-out"
            emphasis={[run.selection.model, best?.model].filter(Boolean)}
            format={(v) => (v === null ? '—' : v.toFixed(1))}
          />
        </ChartFrame>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        {run.significance ? <Significance s={run.significance} /> : null}
        {run.protocol ? <Protocol p={run.protocol} /> : null}
      </div>

      <Warnings w={run.warnings} />

      <footer className="mt-4 text-xs text-muted">
        <p>
          Run {run.id?.slice(0, 8)} · configuration digest {run.configHash?.slice(0, 12)} ·
          primary metric {run.primaryMetric}.
        </p>
        <button
          type="button"
          onClick={onStart}
          disabled={starting || waiting}
          className="mt-2 rounded border border-rule px-2 py-1 text-xs text-muted hover:text-ink disabled:opacity-50"
        >
          {starting || waiting ? 'Running…' : 'Run the experiment again'}
        </button>
        {startError ? (
          <p role="alert" className="mt-2 text-crit">
            {startError.message ?? String(startError)}
          </p>
        ) : null}
      </footer>
    </div>
  );
}

function Figure({ label, value, sub }) {
  return (
    <div className="rounded-lg border border-rule bg-surface p-3">
      <p className="text-xs text-muted">{label}</p>
      <p className="mt-1 text-lg font-semibold text-ink">{value ?? '—'}</p>
      {sub ? <p className="text-xs text-muted">{sub}</p> : null}
    </div>
  );
}

function Significance({ s }) {
  return (
    <section className="rounded-lg border border-rule bg-surface p-4">
      <h2 className="text-sm font-semibold text-ink">Is the difference real?</h2>
      <p className="mt-2 text-sm text-ink2">{s.summary}</p>
      <dl className="mt-3 grid grid-cols-2 gap-2 text-xs">
        <div>
          <dt className="text-muted">{s.test}</dt>
          <dd className="font-semibold text-ink tabular-nums">p = {s.pValue?.toFixed(3)}</dd>
        </div>
        <div>
          <dt className="text-muted">Pairs surviving {s.correction}</dt>
          <dd className="font-semibold text-ink tabular-nums">
            {s.significantPairs} of {s.comparisons}
          </dd>
        </div>
      </dl>
      {s.caveats.map((c) => (
        <p key={c} className="mt-2 text-xs text-muted">
          {c}
        </p>
      ))}
      {s.grounding ? <p className="mt-2 text-xs text-muted">{s.grounding}</p> : null}
    </section>
  );
}

function Protocol({ p }) {
  return (
    <section className="rounded-lg border border-rule bg-surface p-4">
      <h2 className="text-sm font-semibold text-ink">The protocol</h2>
      <p className="mt-1 text-xs text-muted">
        {p.folds.length} {p.style} folds over {p.observations} periods, horizon {p.horizon}. Every
        window trains on what precedes it.
      </p>
      <table className="chart-table mt-3 w-full text-left text-xs">
        <thead>
          <tr className="border-b border-rule text-muted">
            <th scope="col" className="py-1 pr-2 font-medium">Fold</th>
            <th scope="col" className="py-1 pr-2 font-medium">Trains to</th>
            <th scope="col" className="py-1 pr-2 text-right font-medium">Size</th>
            <th scope="col" className="py-1 font-medium">Tests</th>
          </tr>
        </thead>
        <tbody>
          {p.folds.map((f) => (
            <tr key={f.fold} className="border-b border-rule/50">
              <td className="py-1 pr-2 text-ink2">{f.fold}</td>
              <td className="py-1 pr-2 text-ink2">{f.trainEnd}</td>
              <td className="py-1 pr-2 text-right text-ink2">{f.trainSize}</td>
              <td className="py-1 text-ink2">
                {f.testStart} to {f.testEnd}
              </td>
            </tr>
          ))}
          {p.holdout ? (
            <tr className="font-semibold">
              <td className="py-1 pr-2 text-ink">hold-out</td>
              <td className="py-1 pr-2 text-ink">{p.holdout.trainEnd}</td>
              <td className="py-1 pr-2 text-right text-ink">{p.holdout.trainSize}</td>
              <td className="py-1 text-ink">
                {p.holdout.testStart} to {p.holdout.testEnd}
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
      {p.notes.map((n) => (
        <p key={n} className="mt-2 text-xs text-muted">
          {n}
        </p>
      ))}
    </section>
  );
}

/**
 * The things a reader should know before trusting a number above.
 *
 * A page that reported only the means would hide the fact that four of the
 * thirty-two fold results were a forecast of zero, which is the single most
 * misleading thing this run could do quietly.
 */
function Warnings({ w }) {
  const anything =
    w.degenerate.length || w.failed.length || w.gapsFilled || w.incompleteDropped;
  if (!anything) return null;

  return (
    <section className="mt-4 rounded-lg border border-rule bg-surface p-4">
      <h2 className="text-sm font-semibold text-ink">What to know about this run</h2>

      {w.gapsFilled ? (
        <p className="mt-2 text-xs text-ink2">
          {w.gapsFilled} period{w.gapsFilled === 1 ? '' : 's'} had no trade at all (
          {w.gapPeriods.join(', ')}) and {w.gapsFilled === 1 ? 'was' : 'were'} filled with zero so
          the series stays evenly spaced, which every model here assumes. {w.gapNote}
        </p>
      ) : null}

      {w.boundariesOnGaps.length ? (
        <p className="mt-2 text-xs text-ink2">
          {w.boundariesOnGaps
            .map((b) => `Fold ${b.fold} trains up to ${b.trainEnd}`)
            .join('; ')}
          , which is one of those filled weeks. A model that anchors on its last training
          observation therefore forecasts zero across the whole horizon, and its error for that
          fold is not a measure of the model.
        </p>
      ) : null}

      {w.degenerate.length ? (
        <>
          <p className="mt-3 text-xs font-medium text-ink">
            {w.degenerate.length} model-fold results were a forecast of zero
          </p>
          <ul className="mt-1 space-y-0.5 text-xs text-ink2">
            {w.degenerate.map((d) => (
              <li key={`${d.model}-${d.where}`} className="tabular-nums">
                {d.model.replace(/_/g, ' ')} · {d.where} · {wape(d.wape)}
              </li>
            ))}
          </ul>
          <p className="mt-1 text-xs text-muted">
            These inflate the cross-validation means above and are the reason some approaches look
            far worse in cross-validation than on the hold-out.
          </p>
        </>
      ) : null}

      {w.incompleteDropped ? (
        <p className="mt-2 text-xs text-ink2">{w.incompleteNote}</p>
      ) : null}

      {w.failed.length ? (
        <ul className="mt-2 space-y-0.5 text-xs text-crit">
          {w.failed.map((f) => (
            <li key={`${f.model}-${f.where}`}>
              {f.model} failed on {f.where}: {f.error}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function Empty({ onStart, starting, error }) {
  return (
    <div>
      <h1 className="text-xl font-semibold text-ink">Forecasting</h1>
      <p className="mt-2 max-w-prose text-sm text-muted">
        No forecasting experiment has been run on this dataset yet. One compares eight approaches
        across rolling-origin folds, then scores the selected approach once on a hold-out period it
        never saw. It takes about two minutes.
      </p>
      <button
        type="button"
        onClick={onStart}
        disabled={starting}
        className="mt-4 rounded bg-accent px-3 py-2 text-sm font-medium text-white disabled:opacity-60"
      >
        {starting ? 'Running the experiment…' : 'Run the experiment'}
      </button>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-crit">
          {error.message ?? String(error)}
        </p>
      ) : null}
    </div>
  );
}

function forecastNote(f) {
  const parts = [];
  if (f.coverage.observed !== null && f.coverage.nominal !== null) {
    parts.push(
      `The interval covered ${percent(f.coverage.observed)} of the ${f.coverage.points} hold-out weeks against a nominal ${percent(f.coverage.nominal, { decimals: 0 })}: ${f.coverage.verdict}.`,
    );
  }
  if (f.isFlat) {
    parts.push(
      'The forecast is a flat line because the selected approach projects its last average forward unchanged. That is the model, not a rendering fault.',
    );
  }
  if (f.sizingNote) parts.push(f.sizingNote);
  if (f.coverage.caveat) parts.push(f.coverage.caveat);
  return parts.join(' ');
}

function rankNote(run) {
  const rho = run.rankCorrelation;
  if (rho === null) return null;
  const moved = run.models.filter((m) => m.move !== null && Math.abs(m.move) >= 3).length;
  return [
    `Spearman rank correlation between the two stages: ${rho.toFixed(2)}.`,
    Math.abs(rho) < 0.3
      ? 'The cross-validation ordering carries almost no information about the hold-out ordering, so the approach selected by it is close to arbitrary.'
      : 'The two orderings broadly agree.',
    moved ? `${moved} approaches moved three or more places.` : '',
  ]
    .filter(Boolean)
    .join(' ');
}

export default ForecastingPage;
