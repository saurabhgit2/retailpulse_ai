const STEPS = [
  { key: 'choose', label: 'Choose file' },
  { key: 'map', label: 'Map columns' },
  { key: 'process', label: 'Process' },
];

/** Progress indicator for the upload wizard. The numbers are a real sequence. */
export function UploadSteps({ current }) {
  const currentIndex = STEPS.findIndex((s) => s.key === current);
  return (
    <ol className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
      {STEPS.map((step, index) => {
        const state = index < currentIndex ? 'done' : index === currentIndex ? 'current' : 'todo';
        return (
          <li key={step.key} className="flex items-center gap-2" aria-current={state === 'current' ? 'step' : undefined}>
            <span
              className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold ${
                state === 'current'
                  ? 'bg-accent text-accent-ink'
                  : state === 'done'
                    ? 'bg-accent-soft text-accent'
                    : 'bg-surface-2 text-muted'
              }`}
            >
              {state === 'done' ? '✓' : index + 1}
            </span>
            <span className={state === 'todo' ? 'text-muted' : 'font-medium text-ink'}>{step.label}</span>
          </li>
        );
      })}
    </ol>
  );
}
