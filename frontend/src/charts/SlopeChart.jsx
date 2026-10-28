import { useMemo, useState } from 'react';

import { useChartSize } from './useChartSize.js';

const MARGIN = { top: 26, right: 12, bottom: 14, left: 12 };
const ROW = 30;

/**
 * Two rankings, side by side, with a line per item.
 *
 * This is the form for "did the ordering survive?". A pair of bar charts
 * invites the reader to compare lengths across two scales; crossing lines put
 * the reordering itself on screen, which is the thing being claimed.
 *
 * Emphasis rather than eight colours: the items named in `emphasis` carry a
 * hue, everything else is grey. Eight distinguishable lines would make the
 * reader cross-reference a legend to learn something the crossings already
 * say.
 */
export function SlopeChart({
  rows,
  leftLabel,
  rightLabel,
  emphasis = [],
  format = (v) => String(v),
  note = null,
}) {
  const height = Math.max(ROW, rows.length * ROW) + MARGIN.top + MARGIN.bottom;
  const { ref, width, ready } = useChartSize(height);
  const [active, setActive] = useState(null);

  const colors = useMemo(() => {
    const slots = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)'];
    const map = new Map();
    emphasis.slice(0, slots.length).forEach((key, i) => map.set(key, slots[i]));
    return map;
  }, [emphasis]);

  // The label columns are measured in characters rather than pixels: the
  // longest model name decides how much room the middle gets, and leaving it
  // to a fixed fraction either truncates names or wastes half the card.
  const longest = Math.max(...rows.map((r) => r.label.length), 8);
  const column = Math.min(190, Math.max(96, longest * 6.4 + 46));
  const x0 = MARGIN.left + column;
  const x1 = Math.max(x0 + 40, width - MARGIN.right - column);

  const y = (rank) => MARGIN.top + (rank - 0.5) * ROW;

  if (!ready) return <div ref={ref} style={{ height }} />;

  return (
    <div ref={ref}>
      <svg
        width={width}
        height={height}
        role="img"
        aria-label={`${leftLabel} ranking against ${rightLabel} ranking`}
        className="block"
      >
        <text x={x0} y={14} textAnchor="end" fontSize="10.5" fill="var(--chart-ink-2)" fontWeight="600">
          {leftLabel}
        </text>
        <text x={x1} y={14} textAnchor="start" fontSize="10.5" fill="var(--chart-ink-2)" fontWeight="600">
          {rightLabel}
        </text>

        {rows.map((row) => {
          const colour = colors.get(row.key) ?? 'var(--series-muted)';
          const lead = colors.has(row.key);
          const on = active === row.key;
          const ya = y(row.leftRank);
          const yb = y(row.rightRank);
          return (
            <g
              key={row.key}
              onPointerEnter={() => setActive(row.key)}
              onPointerLeave={() => setActive(null)}
              onFocus={() => setActive(row.key)}
              onBlur={() => setActive(null)}
              tabIndex={0}
              aria-label={`${row.label}: ${leftLabel} rank ${row.leftRank} at ${format(
                row.leftValue,
              )}, ${rightLabel} rank ${row.rightRank} at ${format(row.rightValue)}`}
              className="focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
            >
              {/* A transparent band so the row is hoverable anywhere, not only
                  on the two-pixel line itself. */}
              <rect x={0} y={Math.min(ya, yb) - 9} width={width} height={Math.abs(yb - ya) + 18} fill="transparent" />
              <line
                x1={x0 + 6}
                y1={ya}
                x2={x1 - 6}
                y2={yb}
                stroke={colour}
                strokeWidth={lead || on ? 2 : 1.1}
                strokeLinecap="round"
                opacity={on || lead || active === null ? 1 : 0.45}
              />
              {[
                [x0 + 6, ya],
                [x1 - 6, yb],
              ].map(([cx, cy]) => (
                <circle
                  key={cx}
                  cx={cx}
                  cy={cy}
                  r="4"
                  fill={colour}
                  stroke="var(--chart-surface)"
                  strokeWidth="2"
                />
              ))}
              <text
                x={x0 - 4}
                y={ya}
                dy="0.32em"
                textAnchor="end"
                fontSize="10.5"
                fill={lead || on ? 'var(--chart-ink)' : 'var(--chart-ink-2)'}
                fontWeight={lead || on ? 600 : 400}
              >
                {row.label} {format(row.leftValue)}
              </text>
              <text
                x={x1 + 4}
                y={yb}
                dy="0.32em"
                textAnchor="start"
                fontSize="10.5"
                fill={lead || on ? 'var(--chart-ink)' : 'var(--chart-ink-2)'}
                fontWeight={lead || on ? 600 : 400}
              >
                {format(row.rightValue)} {row.label}
              </text>
            </g>
          );
        })}
      </svg>
      {note ? <p className="mt-2 text-xs text-muted">{note}</p> : null}
    </div>
  );
}
