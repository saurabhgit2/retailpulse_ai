/**
 * Shown on every page while the in-browser mock API is active, so nothing the
 * mock produces can be mistaken for real analysis.
 */
export function MockModeBanner() {
  return (
    <div className="border-b border-rule bg-warn-soft px-4 py-2 text-center text-xs text-warn sm:px-8">
      <strong className="font-semibold">Mock API.</strong> Data stays in this browser and reports
      are computed from a preview of your file. They are not real analysis. Set{' '}
      <code className="font-mono">VITE_USE_MOCK_API=false</code> to use the backend.
    </div>
  );
}
