import { useMemo, useState } from 'react';

import { compact, exact } from './axisFormat.js';
import { barPath } from './path.js';
import { bandScale, linearScale, niceDomain } from './scale.js';
import { useChartSize } from './useChartSize.js';

const MARGIN = { top: 4, right: 56, bottom: 4, left: 8 };
const ROW_HEIGHT = 28;
const LABEL_WIDTH = 0.38; // share of the card given to category names

/**
 * A horizontal bar chart for ranked categories.
 *
 * Horizontal rather than vertical because product descriptions in this
 * dataset run to forty characters; rotated x labels would be unreadable and
 * truncating them would hide which product a bar is.
 *
 * One series, so one colour for every bar. Shading each bar darker where it
 * is longer would double-encode length as hue and spend the only free channel
 * on information the bar already carries.
 */
export function BarChart({
  rows,
  color = 'var(--series-1)',
  currency = null,
  valueLabel = 'Value',
  maxBarThickness = 24,
}) {
  const height = Math.max(ROW_HEIGHT, rows.length * ROW_HEIGHT) + MARGIN.top + MARGIN.bottom;
  const { ref, width, ready } = useChartSize(height);
  const [active, setActive] = useState(null);

  const labelWidth = Math.min(220, Math.max(96, width * LABEL_WIDTH));
  const plotLeft = MARGIN.left + labelWidth + 12;
  const plotWidth = Math.max(0, width - plotLeft - MARGIN.right);
  const plotHeight = Math.max(0, height - MARGIN.top - MARGIN.bottom);

  const xScale = useMemo(() => {
    const values = rows.map((r) => Number(r.value)).filter(Number.isFinite);
    // Bars always start at zero. A truncated baseline makes a 4% difference
    // look like a 40% one, which is the oldest chart lie there is.
    const [lo, hi] = niceDomain(0, values.length ? Math.max(...values) : 1, {
      count: 3,
      includeZero: true,
    });
    return linearScale({ domain: [lo, hi], range: [0, plotWidth] });
  }, [rows, plotWidth]);

  const yScale = useMemo(
    () =>
      bandScale({
        domain: rows.map((r) => r.key ?? r.label),
        range: [0, plotHeight],
        paddingInner: 0.3,
        maxBandwidth: maxBarThickness,
      }),
    [rows, plotHeight, maxBarThickness],
  );

  if (!ready) return <div ref={ref} style={{ height }} />;

  return (
    <div ref={ref} className="relative">
      <svg width={width} height={height} role="img" aria-label={`${valueLabel} by category`} className="block">
        <g transform={`translate(0,${MARGIN.top})`}>
          {rows.map((row) => {
            const id = row.key ?? row.label;
            const y = yScale(id);
            if (y === null) return null;
            const value = Number(row.value);
            const length = Number.isFinite(value) ? Math.max(0, xScale(value) - xScale(0)) : 0;
            const isActive = active === id;
            const fill = row.isOther ? 'var(--series-muted)' : color;
            return (
              <g
                key={id}
                onPointerEnter={() => setActive(id)}
                onPointerLeave={() => setActive(null)}
                onFocus={() => setActive(id)}
                onBlur={() => setActive(null)}
                tabIndex={0}
                role="listitem"
                aria-label={`${row.label}: ${exact(value, { currency })}`}
                className="focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
              >
                {/* The hit area spans the whole row, not just the painted bar:
                    a 6px bar is not a target anyone lands on. */}
                <rect
                  x={0}
                  y={y - (yScale.step() - yScale.bandwidth()) / 2}
                  width={width}
                  height={yScale.step()}
                  fill="transparent"
                />
                <text
                  x={MARGIN.left}
                  y={y + yScale.bandwidth() / 2}
                  dy="0.32em"
                  fontSize="11"
                  fill={isActive ? 'var(--chart-ink)' : 'var(--chart-ink-2)'}
                >
                  {truncate(row.label, labelWidth)}
                </text>
                <path
                  d={barPath({
                    x: plotLeft,
                    y,
                    width: length,
                    height: yScale.bandwidth(),
                    side: 'right',
                  })}
                  fill={fill}
                  fillOpacity={isActive ? 1 : 0.9}
                />
                {/* The value rides the bar tip rather than appearing on every
                    gridline, and sits outside the bar so it is never clipped. */}
                <text
                  className="chart-tick"
                  x={plotLeft + length + 6}
                  y={y + yScale.bandwidth() / 2}
                  dy="0.32em"
                  fontSize="10"
                  fill="var(--chart-ink-2)"
                >
                  {compact(value, { currency })}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
}

/**
 * Cut a label to the space available and mark the cut.
 *
 * Measuring text properly needs a canvas; 6.1px per character at 11px is
 * close enough for this font size, and the full name is in the table view and
 * the row's accessible name, so a trimmed label never hides a value.
 */
function truncate(text, pixels) {
  const max = Math.max(6, Math.floor(pixels / 6.1));
  return text.length <= max ? text : `${text.slice(0, max - 1)}…`;
}
