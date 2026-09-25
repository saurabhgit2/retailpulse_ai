/**
 * Which analyses the dataset can support. Shown during mapping (as a live
 * preview) and on the data-quality report.
 */
export function CapabilityList({ capabilities }) {
  return (
    <ul className="grid gap-2 sm:grid-cols-2">
      {capabilities.map((capability) => (
        <li key={capability.key} className="flex items-start gap-2 rounded-md border border-rule bg-surface px-3 py-2 text-sm">
          <span
            aria-hidden="true"
            className={`mt-0.5 inline-flex h-4 w-4 flex-none items-center justify-center rounded-full text-[10px] font-bold ${
              capability.enabled ? 'bg-ok-soft text-ok' : 'bg-surface-2 text-muted'
            }`}
          >
            {capability.enabled ? '✓' : '–'}
          </span>
          <span>
            <span className={capability.enabled ? 'text-ink' : 'text-muted'}>{capability.label}</span>
            <span className="sr-only">{capability.enabled ? ': available' : ': unavailable'}</span>
            {!capability.enabled && (
              <span className="block text-xs text-muted">
                Needs: <code className="font-mono">{capability.missing.join(', ')}</code>
              </span>
            )}
          </span>
        </li>
      ))}
    </ul>
  );
}
