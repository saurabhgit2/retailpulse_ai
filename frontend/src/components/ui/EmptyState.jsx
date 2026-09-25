/** What to show when there is nothing yet, and what to do about it. */
export function EmptyState({ title, children, action }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-rule bg-surface px-6 py-12 text-center">
      <h2 className="text-base font-semibold text-ink">{title}</h2>
      {children && <div className="max-w-md text-sm text-muted">{children}</div>}
      {action}
    </div>
  );
}
