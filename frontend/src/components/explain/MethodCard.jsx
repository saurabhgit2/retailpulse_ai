/**
 * The "About this analysis" panel. Uses the native <details> element: it is
 * keyboard-accessible and needs no JavaScript state to open and close.
 */
export function MethodCard({ card }) {
  if (!card) return null;
  return (
    <details className="group rounded-lg border border-rule bg-surface">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-3 text-sm font-semibold text-ink">
        {card.title}
        <span className="text-muted transition-transform group-open:rotate-90" aria-hidden="true">
          ›
        </span>
      </summary>
      <dl className="grid gap-4 border-t border-rule px-5 py-4 text-sm sm:grid-cols-2">
        <Entry term="What it does">{card.what}</Entry>
        <Entry term="Why it is used">{card.why}</Entry>
        <Entry term="Input">{card.input}</Entry>
        <Entry term="Output">{card.output}</Entry>
        <Entry term="Assumptions">
          <List items={card.assumptions} />
        </Entry>
        <Entry term="Limitations">
          <List items={card.limitations} />
        </Entry>
        <Entry term="How to interpret it" wide>
          {card.interpretation}
        </Entry>
      </dl>
    </details>
  );
}

function Entry({ term, children, wide = false }) {
  return (
    <div className={wide ? 'sm:col-span-2' : ''}>
      <dt className="text-xs font-medium tracking-wide text-muted uppercase">{term}</dt>
      <dd className="mt-1 text-ink-2">{children}</dd>
    </div>
  );
}

function List({ items = [] }) {
  return (
    <ul className="list-disc space-y-1 pl-4">
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}
