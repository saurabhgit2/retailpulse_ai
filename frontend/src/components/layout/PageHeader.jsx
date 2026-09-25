/** Title row used at the top of every page. */
export function PageHeader({ title, description, actions, eyebrow }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <div className="mb-1 flex flex-wrap items-center gap-2 text-sm text-muted">{eyebrow}</div>}
        <h1 className="text-2xl font-semibold tracking-tight text-balance text-ink">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-sm text-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}
