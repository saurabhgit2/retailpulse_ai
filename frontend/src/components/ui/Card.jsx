/** A bordered surface with an optional header row (title, description, actions). */
export function Card({ title, description, actions, children, className = '', bodyClassName = 'p-5' }) {
  const hasHeader = title || description || actions;
  return (
    <section className={`rounded-lg border border-rule bg-surface ${className}`}>
      {hasHeader && (
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-rule px-5 py-4">
          <div className="min-w-0">
            {title && <h2 className="text-base font-semibold text-ink">{title}</h2>}
            {description && <p className="mt-1 text-sm text-muted">{description}</p>}
          </div>
          {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
        </header>
      )}
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}
