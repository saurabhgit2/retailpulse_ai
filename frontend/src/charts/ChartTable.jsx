/**
 * The table twin of a chart.
 *
 * Not a fallback. It is the reason the chart is allowed to use hues that sit
 * below 3:1 against white, and the reason a tooltip is permitted to be the
 * only *convenient* way to read a point: every value is reachable here,
 * without hovering, with a keyboard, and in a screen reader.
 *
 * Numbers are right-aligned with tabular figures because this is a column
 * that has to line up — the one place those figures belong.
 */
export function ChartTable({ caption, columns, rows }) {
  return (
    <div className="max-h-72 overflow-auto">
      <table className="chart-table w-full text-left text-xs">
        {caption ? <caption className="sr-only">{caption}</caption> : null}
        <thead className="sticky top-0 bg-surface">
          <tr className="border-b border-rule">
            {columns.map((c) => (
              <th
                key={c.key}
                scope="col"
                className={`py-1.5 pr-3 font-medium text-muted ${
                  c.numeric ? 'text-right' : 'text-left'
                }`}
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={row.key ?? i} className="border-b border-rule/50 last:border-0">
              {columns.map((c) => (
                <td
                  key={c.key}
                  className={`py-1.5 pr-3 text-ink2 ${c.numeric ? 'text-right' : 'text-left'}`}
                >
                  {row[c.key] ?? '—'}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
