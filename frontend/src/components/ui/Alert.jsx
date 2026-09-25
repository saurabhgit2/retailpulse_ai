const TONES = {
  info: 'bg-info-soft text-info',
  success: 'bg-ok-soft text-ok',
  warning: 'bg-warn-soft text-warn',
  error: 'bg-crit-soft text-crit',
};

/**
 * A message box. Errors use role="alert" so screen readers announce them
 * immediately; other tones use role="status", which is announced politely.
 */
export function Alert({ tone = 'info', title, children, className = '' }) {
  return (
    <div role={tone === 'error' ? 'alert' : 'status'} className={`rounded-md px-4 py-3 text-sm ${TONES[tone]} ${className}`}>
      {title && <p className="font-semibold">{title}</p>}
      {children && <div className={`text-ink-2 ${title ? 'mt-1' : ''}`}>{children}</div>}
    </div>
  );
}
