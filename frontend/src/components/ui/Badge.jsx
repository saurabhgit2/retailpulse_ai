const TONES = {
  neutral: 'bg-surface-2 text-ink-2',
  accent: 'bg-accent-soft text-accent',
  ok: 'bg-ok-soft text-ok',
  warn: 'bg-warn-soft text-warn',
  crit: 'bg-crit-soft text-crit',
  info: 'bg-info-soft text-info',
};

/** A small label, e.g. SYNTHETIC or Required. */
export function Badge({ tone = 'neutral', children, className = '', title }) {
  return (
    <span
      title={title}
      className={`inline-flex items-center rounded px-1.5 py-0.5 font-mono text-[11px] font-medium tracking-wide uppercase ${TONES[tone]} ${className}`}
    >
      {children}
    </span>
  );
}
