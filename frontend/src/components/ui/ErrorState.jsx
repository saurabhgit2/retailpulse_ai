import { Button } from './Button';

/**
 * Shows an ApiError: the message tells the user what went wrong, and the
 * request ID (if any) lets a developer find the matching server log entry.
 */
export function ErrorState({ error, title = 'Something went wrong', onRetry }) {
  return (
    <div role="alert" className="rounded-lg border border-rule bg-surface px-5 py-6">
      <h2 className="text-base font-semibold text-crit">{title}</h2>
      <p className="mt-1 text-sm text-ink-2">{error?.message ?? 'An unexpected error occurred.'}</p>
      {error?.requestId && <p className="mt-2 font-mono text-xs text-muted">Request ID: {error.requestId}</p>}
      {onRetry && (
        <Button variant="secondary" size="sm" className="mt-4" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}
