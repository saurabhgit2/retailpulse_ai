/** A labelled figure. Used where a few headline numbers are the point. */
export function StatTile({ label, value, hint }) {
  return (
    <div className="rounded-lg border border-rule bg-surface px-4 py-3">
      <p className="text-xs font-medium tracking-wide text-muted uppercase">{label}</p>
      <p className="tabular mt-1 text-2xl font-semibold text-ink">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-muted">{hint}</p>}
    </div>
  );
}
