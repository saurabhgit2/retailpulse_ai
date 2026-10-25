import { PRESETS, describe } from '../../hooks/filterState.js';

/**
 * One filter row, above everything it scopes.
 *
 * Never inside a chart card and never per-chart: if two charts on a page
 * answered to different ranges, their numbers would disagree and a reader
 * would have no way to see why.
 *
 * Date range first, presets before the custom inputs, because that is the
 * control a reader reaches for and nobody wants to fight two date pickers to
 * ask for the last ninety days.
 */
export function FilterBar({ filters, update, reset, bounds, options, disabled = false }) {
  const custom = filters.preset === 'custom';
  const min = bounds?.min_date?.slice(0, 10);
  const max = bounds?.max_date?.slice(0, 10);

  return (
    <div className="mb-4 rounded-lg border border-rule bg-surface p-3">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Date range">
          <select
            value={filters.preset}
            onChange={(e) => update({ preset: e.target.value })}
            disabled={disabled}
            className="rounded border border-rule bg-surface px-2 py-1 text-sm text-ink"
          >
            {PRESETS.map((p) => (
              <option key={p.key} value={p.key}>
                {p.label}
              </option>
            ))}
          </select>
        </Field>

        {custom ? (
          <>
            <Field label="From">
              <input
                type="date"
                value={filters.from}
                min={min}
                max={max}
                onChange={(e) => update({ from: e.target.value })}
                disabled={disabled}
                className="rounded border border-rule bg-surface px-2 py-1 text-sm text-ink"
              />
            </Field>
            <Field label="To">
              <input
                type="date"
                value={filters.to}
                min={min}
                max={max}
                onChange={(e) => update({ to: e.target.value })}
                disabled={disabled}
                className="rounded border border-rule bg-surface px-2 py-1 text-sm text-ink"
              />
            </Field>
          </>
        ) : null}

        {options?.regions?.length ? (
          <Field label="Region">
            <select
              value={filters.region}
              onChange={(e) => update({ region: e.target.value })}
              disabled={disabled}
              className="max-w-44 rounded border border-rule bg-surface px-2 py-1 text-sm text-ink"
            >
              <option value="">All regions</option>
              {options.regions.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </Field>
        ) : null}

        {options?.categories?.length ? (
          <Field label="Category">
            <select
              value={filters.category}
              onChange={(e) => update({ category: e.target.value })}
              disabled={disabled}
              className="max-w-44 rounded border border-rule bg-surface px-2 py-1 text-sm text-ink"
            >
              <option value="">All categories</option>
              {options.categories.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </Field>
        ) : null}

        <button
          type="button"
          onClick={reset}
          className="ml-auto rounded border border-rule px-2 py-1 text-xs text-muted hover:text-ink"
        >
          Clear filters
        </button>
      </div>

      {/* The selection stated in words. A reader comparing two screenshots
          should not have to decode the address bar to see what differed. */}
      <p className="mt-2 text-xs text-muted">{describe(filters, bounds)}</p>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-muted">{label}</span>
      {children}
    </label>
  );
}
