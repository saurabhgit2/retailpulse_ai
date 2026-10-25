import { useId, useState } from 'react';

import { ChartTable } from './ChartTable.jsx';
import { Legend } from './Legend.jsx';

/**
 * The card every chart sits in.
 *
 * It owns four things the chart itself should not have to:
 *
 * - the four states (loading, error, empty, data), so no page repeats them;
 * - the legend, which is always present for two or more series;
 * - the **table view**, which is what makes a palette with sub-3:1 hues
 *   legitimate: every value stays reachable without relying on colour;
 * - the note, where a withheld figure explains itself.
 *
 * On a refetch the previous render is held at reduced opacity rather than
 * replaced by a skeleton, so the card does not collapse and jump.
 */
export function ChartFrame({
  title,
  subtitle,
  note,
  series = [],
  loading = false,
  refreshing = false,
  error = null,
  empty = false,
  emptyMessage = 'No data for the current filters.',
  table = null,
  actions = null,
  height = 260,
  children,
}) {
  const [showTable, setShowTable] = useState(false);
  const headingId = useId();
  const tableId = useId();

  const hasData = !loading && !error && !empty;

  return (
    <section
      aria-labelledby={headingId}
      className="rounded-lg border border-rule bg-surface p-4"
    >
      <header className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 id={headingId} className="truncate text-sm font-semibold text-ink">
            {title}
          </h3>
          {subtitle ? <p className="mt-0.5 text-xs text-muted">{subtitle}</p> : null}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {actions}
          {table ? (
            <button
              type="button"
              onClick={() => setShowTable((v) => !v)}
              aria-expanded={showTable}
              aria-controls={tableId}
              className="rounded border border-rule px-2 py-1 text-xs text-muted hover:text-ink"
            >
              {showTable ? 'Chart' : 'Table'}
            </button>
          ) : null}
        </div>
      </header>

      {series.length > 1 ? <Legend series={series} /> : null}

      {loading ? (
        <div
          role="status"
          className="flex items-center justify-center text-xs text-muted"
          style={{ height }}
        >
          Loading…
        </div>
      ) : null}

      {error ? (
        <div role="alert" className="rounded border border-crit/30 bg-crit/5 p-3 text-xs text-ink">
          <p className="font-medium">This chart could not be loaded.</p>
          <p className="mt-1 text-muted">{error.message ?? String(error)}</p>
          {error.requestId ? (
            <p className="mt-1 text-muted">Reference: {error.requestId}</p>
          ) : null}
        </div>
      ) : null}

      {empty && !loading && !error ? (
        <div
          className="flex items-center justify-center text-xs text-muted"
          style={{ height }}
        >
          {emptyMessage}
        </div>
      ) : null}

      {hasData ? (
        showTable && table ? (
          <div id={tableId}>
            <ChartTable {...table} />
          </div>
        ) : (
          // Hold the previous render while new data arrives: no skeleton, no
          // layout jump. aria-busy tells a screen reader what the opacity says.
          <div
            aria-busy={refreshing || undefined}
            style={{ opacity: refreshing ? 0.55 : 1, transition: 'opacity 150ms' }}
          >
            {children}
          </div>
        )
      ) : null}

      {note ? <p className="mt-3 text-xs leading-relaxed text-muted">{note}</p> : null}
    </section>
  );
}
