/**
 * The legend.
 *
 * Present whenever there are two or more series, because it is the only
 * identity channel that survives colour-vision deficiency, a greyscale print
 * and a `forced-colors` display. Direct labels on the marks supplement it;
 * they do not replace it.
 *
 * The key mirrors the mark: a short stroke for a line, a swatch for a fill.
 * The text wears an ink token, never the series colour — a light hue such as
 * aqua or yellow is illegible as text on white, and that is precisely the
 * mistake the mark-beside-the-text arrangement avoids.
 */
export function Legend({ series }) {
  return (
    <ul className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1">
      {series.map((s) => (
        <li key={s.key ?? s.label} className="flex items-center gap-1.5 text-xs text-ink2">
          <LegendKey color={s.color} mark={s.mark ?? 'line'} dashed={s.dashed} />
          <span>{s.label}</span>
        </li>
      ))}
    </ul>
  );
}

function LegendKey({ color, mark, dashed }) {
  if (mark === 'band') {
    return (
      <span
        aria-hidden="true"
        className="inline-block h-2.5 w-4 rounded-sm"
        style={{ backgroundColor: color, opacity: 0.18, outline: `1px solid ${color}` }}
      />
    );
  }
  if (mark === 'rect') {
    return (
      <span
        aria-hidden="true"
        className="inline-block h-2.5 w-2.5 rounded-sm"
        style={{ backgroundColor: color }}
      />
    );
  }
  return (
    <svg aria-hidden="true" width="16" height="10" viewBox="0 0 16 10">
      <line
        x1="0"
        y1="5"
        x2="16"
        y2="5"
        stroke={color}
        strokeWidth="2"
        strokeLinecap="round"
        strokeDasharray={dashed ? '4 3' : undefined}
      />
    </svg>
  );
}
