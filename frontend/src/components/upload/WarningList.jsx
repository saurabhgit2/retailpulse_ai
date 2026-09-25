import { Alert } from '../ui/Alert';

/** Server warnings ({ code, message }) shown as a single alert. */
export function WarningList({ warnings, title = 'Things to check' }) {
  if (!warnings?.length) return null;
  return (
    <Alert tone="warning" title={title}>
      <ul className="list-disc space-y-1 pl-4">
        {warnings.map((warning) => (
          <li key={warning.code}>{warning.message}</li>
        ))}
      </ul>
    </Alert>
  );
}
