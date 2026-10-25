import { useMemo, useRef, useState } from 'react';

import { axisFormatter, dateFull, dateTick, exact, pickDateTicks } from './axisFormat.js';
import { bandPath, isolatedPoints, linePath } from './path.js';
import { linearScale, nearestIndex, niceDomain, niceTicks } from './scale.js';
import { useChartSize } from './useChartSize.js';

const MARGIN = { top: 8, right: 16, bottom: 24, left: 52 };

/**
 * A time-series line chart with an optional prediction band.
 *
 * ```jsx
 * <LineChart
 *   x={weeks}                                   // ISO date strings
 *   series={[{ key: 'actual', label: 'Revenue', color: 'var(--series-1)', values: [...] }]}
 *   band={{ lower: [...], upper: [...], color: 'var(--series-2)', label: '80% interval' }}
 * />
 * ```
 *
 * The crosshair finds the X and the readout lists every series at that point,
 * so the pointer never has to land on a 2px line. Arrow keys do the same
 * thing from the keyboard, which is the accessibility obligation a hover-only
 * tooltip fails.
 */
export function LineChart({
  x,
  series,
  band = null,
  height = 260,
  yLabel = null,
  currency = null,
  includeZero = true,
  granularity = 'week',
  valueFormat = null,
}) {
  const { ref, width, ready } = useChartSize(height);
  const [active, setActive] = useState(null);
  const svgRef = useRef(null);

  const plotWidth = Math.max(0, width - MARGIN.left - MARGIN.right);
  const plotHeight = Math.max(0, height - MARGIN.top - MARGIN.bottom);

  const model = useMemo(() => {
    const numbers = [];
    for (const s of series) for (const v of s.values) if (Number.isFinite(v)) numbers.push(v);
    if (band) {
      for (const v of band.lower) if (Number.isFinite(v)) numbers.push(v);
      for (const v of band.upper) if (Number.isFinite(v)) numbers.push(v);
    }
    const lo = numbers.length ? Math.min(...numbers) : 0;
    const hi = numbers.length ? Math.max(...numbers) : 1;
    const domain = niceDomain(lo, hi, { count: 4, includeZero });
    return { domain, ticks: niceTicks(domain[0], domain[1], 4) };
  }, [series, band, includeZero]);

  const xScale = useMemo(
    () =>
      linearScale({
        domain: [0, Math.max(1, x.length - 1)],
        range: [0, plotWidth],
      }),
    [x.length, plotWidth],
  );
  const yScale = useMemo(
    () => linearScale({ domain: model.domain, range: [plotHeight, 0] }),
    [model.domain, plotHeight],
  );

  const xPositions = useMemo(() => x.map((_, i) => xScale(i)), [x, xScale]);
  const formatY = useMemo(
    () => valueFormat ?? axisFormatter(model.ticks, { currency }),
    [valueFormat, model.ticks, currency],
  );
  const tickIndices = useMemo(
    () => pickDateTicks(x, plotWidth),
    [x, plotWidth],
  );

  function pointerToIndex(event) {
    const svg = svgRef.current;
    if (!svg) return null;
    const rect = svg.getBoundingClientRect();
    const px = event.clientX - rect.left - MARGIN.left;
    const index = nearestIndex(xPositions, px);
    return index < 0 ? null : index;
  }

  function onKeyDown(event) {
    if (x.length === 0) return;
    const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
    if (step === 0) {
      if (event.key === 'Home') setActive(0);
      else if (event.key === 'End') setActive(x.length - 1);
      else if (event.key === 'Escape') setActive(null);
      else return;
    } else {
      setActive((current) => {
        const base = current === null ? (step > 0 ? -1 : x.length) : current;
        return Math.min(x.length - 1, Math.max(0, base + step));
      });
    }
    event.preventDefault();
  }

  if (!ready) return <div ref={ref} style={{ height }} />;

  return (
    <div ref={ref} className="relative">
      <svg
        ref={svgRef}
        width={width}
        height={height}
        role="img"
        tabIndex={0}
        aria-label={`${series.map((s) => s.label).join(', ')} over time. Use the arrow keys to read each point, or switch to the table view.`}
        onPointerMove={(e) => setActive(pointerToIndex(e))}
        onPointerLeave={() => setActive(null)}
        onKeyDown={onKeyDown}
        onBlur={() => setActive(null)}
        className="block focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
          {/* Gridlines: solid hairlines one step off the surface, never dashed. */}
          {model.ticks.map((t) => (
            <line
              key={t}
              x1={0}
              x2={plotWidth}
              y1={yScale(t)}
              y2={yScale(t)}
              stroke="var(--chart-grid)"
              strokeWidth="1"
            />
          ))}

          {model.ticks.map((t) => (
            <text
              key={t}
              className="chart-tick"
              x={-8}
              y={yScale(t)}
              dy="0.32em"
              textAnchor="end"
              fontSize="10"
              fill="var(--chart-ink-muted)"
            >
              {formatY(t)}
            </text>
          ))}

          {tickIndices.map((i) => (
            <text
              key={i}
              className="chart-tick"
              x={xPositions[i]}
              y={plotHeight + 16}
              textAnchor={i === 0 ? 'start' : i === x.length - 1 ? 'end' : 'middle'}
              fontSize="10"
              fill="var(--chart-ink-muted)"
            >
              {dateTick(x[i], granularity)}
            </text>
          ))}

          {band ? (
            <path
              d={bandPath(
                x.map((_, i) => ({
                  x: xPositions[i],
                  upper: Number.isFinite(band.upper[i]) ? yScale(band.upper[i]) : null,
                  lower: Number.isFinite(band.lower[i]) ? yScale(band.lower[i]) : null,
                })),
              )}
              fill={band.color}
              stroke={band.color}
              strokeWidth="1"
              /* A presentation attribute such as fill-opacity="..." is not a
                 CSS declaration, so var() in one is ignored and the band
                 renders solid. These have to go through style. */
              style={{
                fillOpacity: 'var(--chart-band-fill, 0.12)',
                strokeOpacity: 'var(--chart-band-edge, 0.5)',
              }}
            />
          ) : null}

          {series.map((s) => {
            const points = x.map((_, i) => ({
              x: xPositions[i],
              y: Number.isFinite(s.values[i]) ? yScale(s.values[i]) : null,
            }));
            return (
              <g key={s.key}>
                <path
                  d={linePath(points)}
                  fill="none"
                  stroke={s.color}
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeDasharray={s.dashed ? '5 4' : undefined}
                />
                {/* A point with no drawable neighbour would be invisible as a
                    line, so it is drawn as a dot instead of disappearing. */}
                {isolatedPoints(points).map((p) => (
                  <circle
                    key={p.x}
                    cx={p.x}
                    cy={p.y}
                    r="3"
                    fill={s.color}
                    stroke="var(--chart-surface)"
                    strokeWidth="2"
                  />
                ))}
              </g>
            );
          })}

          {active !== null && xPositions[active] !== null ? (
            <g>
              <line
                x1={xPositions[active]}
                x2={xPositions[active]}
                y1={0}
                y2={plotHeight}
                stroke="var(--chart-axis)"
                strokeWidth="1"
              />
              {series.map((s) =>
                Number.isFinite(s.values[active]) ? (
                  <circle
                    key={s.key}
                    cx={xPositions[active]}
                    cy={yScale(s.values[active])}
                    r="4"
                    fill={s.color}
                    stroke="var(--chart-surface)"
                    strokeWidth="2"
                  />
                ) : null,
              )}
            </g>
          ) : null}

          <line
            x1={0}
            x2={plotWidth}
            y1={plotHeight}
            y2={plotHeight}
            stroke="var(--chart-axis)"
            strokeWidth="1"
          />
        </g>

        {yLabel ? (
          <text
            x={12}
            y={MARGIN.top + plotHeight / 2}
            fontSize="10"
            fill="var(--chart-ink-muted)"
            textAnchor="middle"
            transform={`rotate(-90 12 ${MARGIN.top + plotHeight / 2})`}
          >
            {yLabel}
          </text>
        ) : null}
      </svg>

      {active !== null ? (
        <Readout
          x={xPositions[active] + MARGIN.left}
          width={width}
          label={dateFull(x[active])}
          rows={[
            ...series.map((s) => ({
              key: s.key,
              color: s.color,
              label: s.label,
              value: exact(s.values[active], { currency }),
            })),
            ...(band && Number.isFinite(band.lower[active])
              ? [
                  {
                    key: 'band',
                    color: band.color,
                    label: band.label ?? 'Interval',
                    value: `${exact(band.lower[active], { currency })} to ${exact(
                      band.upper[active],
                      { currency },
                    )}`,
                  },
                ]
              : []),
          ]}
        />
      ) : null}
    </div>
  );
}

/**
 * The readout. Value first and strong, series name second: the reader already
 * knows which series they are looking at and came for the number.
 *
 * Labels arrive from the API, so they go in as text nodes. React does that by
 * default for `{value}`, which is the reason nothing here builds HTML strings.
 */
function Readout({ x, width, label, rows }) {
  const flip = x > width - 160;
  return (
    <div
      role="status"
      className="pointer-events-none absolute top-0 z-10 min-w-36 rounded border border-rule bg-surface p-2 text-xs shadow-sm"
      style={{ left: flip ? undefined : x + 10, right: flip ? width - x + 10 : undefined }}
    >
      <p className="mb-1 text-muted">{label}</p>
      <ul className="space-y-0.5">
        {rows.map((r) => (
          <li key={r.key} className="flex items-baseline gap-2">
            <svg aria-hidden="true" width="10" height="8" className="shrink-0">
              <line x1="0" y1="4" x2="10" y2="4" stroke={r.color} strokeWidth="2" strokeLinecap="round" />
            </svg>
            <span className="font-semibold text-ink tabular-nums">{r.value}</span>
            <span className="truncate text-muted">{r.label}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
