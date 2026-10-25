import { compact } from '../../charts/axisFormat.js';

/**
 * A stat tile.
 *
 * The whole point of this component is what it does with absent data. The
 * backend withholds a KPI whose source column does not exist, and withholds
 * growth when the two comparison windows are not the same length or not both
 * complete. Rendering either as `0` or `0%` would turn "we do not know" into
 * "it did not change", which is the single most misleading thing a dashboard
 * can do and exactly what the cleaning pipeline was built to avoid.
 *
 * So: a missing value reads "Not available", and a withheld growth figure
 * shows its reason instead of a number.
 */
export function KpiCard({ label, value, growth, currency = null, note = null, unavailableReason = null }) {
  const hasValue = value !== null && value !== undefined && Number.isFinite(value);
  const hasGrowth = growth !== null && growth !== undefined && Number.isFinite(growth);

  return (
    <div className="rounded-lg border border-rule bg-surface p-3">
      <p className="text-xs text-muted">{label}</p>

      {hasValue ? (
        // Proportional figures, not tabular: these are standalone numbers, and
        // equal-width digits make a value like 121 look loose at this size.
        <p className="mt-1 text-2xl font-semibold text-ink">{compact(value, { currency })}</p>
      ) : (
        <p className="mt-1 text-sm text-muted">Not available</p>
      )}

      {!hasValue && unavailableReason ? (
        <p className="mt-1 text-xs text-muted">{unavailableReason}</p>
      ) : null}

      {hasValue && hasGrowth ? <Delta value={growth} /> : null}

      {hasValue && !hasGrowth && note ? (
        <p className="mt-1 text-xs text-muted">{note}</p>
      ) : null}
    </div>
  );
}

/**
 * A signed change against the previous period.
 *
 * Colour carries direction, and the arrow carries it again, because colour
 * alone is not an encoding anyone can rely on. Up is treated as good here;
 * a metric where up is bad (returns, stockouts) passes `upIsGood={false}`.
 */
function Delta({ value, upIsGood = true }) {
  const up = value > 0;
  const flat = value === 0;
  const good = flat ? null : up === upIsGood;
  const color = good === null ? 'var(--chart-ink-muted)' : good ? 'var(--chart-good)' : 'var(--chart-critical)';
  return (
    <p className="mt-1 flex items-center gap-1 text-xs" style={{ color }}>
      <span aria-hidden="true">{flat ? '→' : up ? '↑' : '↓'}</span>
      <span className="tabular-nums">
        {up ? '+' : ''}
        {(value * 100).toFixed(1)}%
      </span>
      <span className="text-muted">vs previous period</span>
    </p>
  );
}
