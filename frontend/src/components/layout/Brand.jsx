/** The RetailPulse wordmark: a small pulse line and the product name. */
export function Brand({ className = '' }) {
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <svg viewBox="0 0 32 32" className="h-7 w-7" aria-hidden="true">
        <rect width="32" height="32" rx="7" fill="var(--accent)" />
        <path
          d="M5 18h5l3-8 5 14 3-9 2 3h4"
          fill="none"
          stroke="var(--accent-ink)"
          strokeWidth="2.4"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <span className="text-lg font-semibold tracking-tight text-ink">
        RetailPulse <span className="text-accent">AI</span>
      </span>
    </div>
  );
}
