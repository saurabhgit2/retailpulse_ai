import { useMemo, useState } from 'react';

import { axisFormatter, compact, exact, thinLabels } from './axisFormat.js';
import { barPath } from './path.js';
import { bandScale, linearScale, niceDomain, niceTicks } from './scale.js';
import { useChartSize } from './useChartSize.js';

const MARGIN = { top: 16, right: 8, bottom: 34, left: 46 };

/**
 * Vertical bars, for a distribution.
 *
 * The horizontal `BarChart` is for ranked categories with long names. This is
 * for the other case: ordered buckets along an axis, where the shape of the
 * distribution is the thing being read and reversing it onto its side makes
 * a skew hard to see.
 *
 * One series, so one colour for every bar. Shading each bar by its own height
 * would spend the only free channel restating the height.
 */
export function ColumnChart({
  bins,
  color = 'var(--series-1)',
  height = 200,
  currency = null,
  valueLabel = 'Count',
  reference = null,
  formatBin = (b) => b.label,
  maxBarThickness = 34,
}) {
  const { ref, width, ready } = useChartSize(height);
  const [active, setActive] = useState(null);

  const plotWidth = Math.max(0, width - MARGIN.left - MARGIN.right);
  const plotHeight = Math.max(0, height - MARGIN.top - MARGIN.bottom);

  const yTicks = useMemo(() => {
    const values = bins.map((b) => Number(b.value)).filter(Number.isFinite);
    // Counts start at zero. A truncated baseline on a distribution turns a
    // mild skew into a cliff.
    const [lo, hi] = niceDomain(0, values.length ? Math.max(...values) : 1, {
      count: 4,
      includeZero: true,
    });
    return { domain: [lo, hi], ticks: niceTicks(lo, hi, 4) };
  }, [bins]);

  const y = useMemo(
    () => linearScale({ domain: yTicks.domain, range: [plotHeight, 0] }),
    [yTicks.domain, plotHeight],
  );
  const x = useMemo(
    () =>
      bandScale({
        domain: bins.map((b, i) => b.key ?? i),
        range: [0, plotWidth],
        paddingInner: 0.25,
        maxBandwidth: maxBarThickness,
      }),
    [bins, plotWidth, maxBarThickness],
  );

  const formatY = useMemo(() => axisFormatter(yTicks.ticks, { currency }), [yTicks.ticks, currency]);

  // Label every bin only when the labels fit; otherwise thin them and let the
  // tooltip carry the rest. Rotating them would be worse: angled text is
  // slower to read, and the bins are ordered so the ends anchor the axis.
  const labelled = useMemo(
    () => new Set(thinLabels(bins.length, plotWidth, 46)),
    [bins.length, plotWidth],
  );

  if (!ready) return <div ref={ref} style={{ height }} />;

  return (
    <div ref={ref} className="relative">
      <svg width={width} height={height} role="img" aria-label={`${valueLabel} by bucket`} className="block">
        <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
          {yTicks.ticks.map((t) => (
            <line
              key={t}
              x1={0}
              x2={plotWidth}
              y1={y(t)}
              y2={y(t)}
              stroke="var(--chart-grid)"
              strokeWidth="1"
            />
          ))}
          {yTicks.ticks.map((t) => (
            <text
              key={t}
              className="chart-tick"
              x={-6}
              y={y(t)}
              dy="0.32em"
              textAnchor="end"
              fontSize="10"
              fill="var(--chart-ink-muted)"
            >
              {formatY(t)}
            </text>
          ))}

          {bins.map((bin, i) => {
            const id = bin.key ?? i;
            const left = x(id);
            if (left === null) return null;
            const value = Number(bin.value);
            const top = Number.isFinite(value) ? y(value) : y(0);
            const on = active === id;
            return (
              <g
                key={id}
                onPointerEnter={() => setActive(id)}
                onPointerLeave={() => setActive(null)}
                onFocus={() => setActive(id)}
                onBlur={() => setActive(null)}
                tabIndex={0}
                aria-label={`${bin.label}: ${exact(value, { currency })}`}
                className="focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
              >
                {/* The hit area is the whole column slot, floor to ceiling: a
                    short bar is otherwise a few pixels of target. */}
                <rect
                  x={left - (x.step() - x.bandwidth()) / 2}
                  y={0}
                  width={x.step()}
                  height={plotHeight}
                  fill="transparent"
                />
                <path
                  d={barPath({
                    x: left,
                    y: top,
                    width: x.bandwidth(),
                    height: plotHeight - top,
                    side: 'top',
                  })}
                  fill={color}
                  fillOpacity={on ? 1 : 0.9}
                />
                {labelled.has(i) && (
                  <text
                    className="chart-tick"
                    x={left + x.bandwidth() / 2}
                    y={plotHeight + 14}
                    textAnchor="middle"
                    fontSize="9.5"
                    fill="var(--chart-ink-muted)"
                  >
                    {formatBin(bin)}
                  </text>
                )}
              </g>
            );
          })}

          {reference ? (
            <g>
              <line
                x1={0}
                x2={plotWidth}
                y1={y(reference.value)}
                y2={y(reference.value)}
                stroke="var(--series-2)"
                strokeWidth="1.5"
                strokeDasharray="5 4"
              />
              <text
                x={plotWidth}
                y={y(reference.value) - 4}
                textAnchor="end"
                fontSize="10"
                fill="var(--chart-ink-2)"
              >
                {reference.label}
              </text>
            </g>
          ) : null}

          <line x1={0} x2={plotWidth} y1={plotHeight} y2={plotHeight} stroke="var(--chart-axis)" strokeWidth="1" />
        </g>
      </svg>

      {active !== null ? (
        <Readout
          bin={bins.find((b, i) => (b.key ?? i) === active)}
          currency={currency}
          valueLabel={valueLabel}
        />
      ) : null}
    </div>
  );
}

function Readout({ bin, currency, valueLabel }) {
  if (!bin) return null;
  return (
    <div
      role="status"
      className="pointer-events-none absolute right-0 top-0 rounded border border-rule bg-surface px-2 py-1 text-xs shadow-sm"
    >
      <span className="font-semibold text-ink tabular-nums">
        {compact(Number(bin.value), { currency })}
      </span>{' '}
      <span className="text-muted">
        {valueLabel.toLowerCase()} in {bin.label}
      </span>
    </div>
  );
}
