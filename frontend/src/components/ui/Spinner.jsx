/** An accessible loading indicator: screen readers announce the label. */
export function Spinner({ label = 'Loading', size = 'md', className = '' }) {
  const dimension = size === 'sm' ? 'h-4 w-4' : 'h-6 w-6';
  return (
    <span role="status" className={`inline-flex items-center gap-2 ${className}`}>
      <svg className={`${dimension} animate-spin`} viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
        <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
      </svg>
      <span className="sr-only">{label}</span>
    </span>
  );
}

export function FullPageSpinner({ label }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 text-muted">
      <Spinner label={label} />
      <p className="text-sm">{label}</p>
    </div>
  );
}
