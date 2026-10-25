/**
 * Formatting that belongs to an axis rather than to the app.
 *
 * `utils/format.js` formats one value for a sentence. An axis formats a *set*
 * of values that have to read as a column, which is a different problem: the
 * unit has to be chosen once for the whole axis. Ticks reading
 * 800 / 900 / 1K / 1.1K force the reader to switch scale mid-column, so the
 * unit is picked from the largest tick and then applied to all of them.
 */

const UNITS = [
  { limit: 1e12, divisor: 1e12, suffix: 'T' },
  { limit: 1e9, divisor: 1e9, suffix: 'B' },
  { limit: 1e6, divisor: 1e6, suffix: 'M' },
  { limit: 1e3, divisor: 1e3, suffix: 'K' },
];

/** The single unit to use for a whole axis, chosen from its largest tick. */
export function axisUnit(ticks) {
  const largest = Math.max(0, ...ticks.map((t) => Math.abs(t)).filter(Number.isFinite));
  const unit = UNITS.find((u) => largest >= u.limit);
  return unit ?? { divisor: 1, suffix: '' };
}

/**
 * A formatter for one axis.
 *
 * Decimal places are decided once, from the smallest gap between ticks, so
 * 2.5K and 3K never appear in the same column as 2.5K and 3.0K.
 */
export function axisFormatter(ticks, { currency = null } = {}) {
  const unit = axisUnit(ticks);
  const scaled = ticks.map((t) => t / unit.divisor);
  let decimals = 0;
  for (let i = 1; i < scaled.length; i += 1) {
    const gap = Math.abs(scaled[i] - scaled[i - 1]);
    if (gap > 0 && gap < 1) decimals = Math.max(decimals, gap < 0.1 ? 2 : 1);
  }
  const prefix = currency ?? '';
  return (value) => {
    if (value === null || value === undefined || !Number.isFinite(value)) return '';
    const n = value / unit.divisor;
    const sign = n < 0 ? '-' : '';
    const body = Math.abs(n).toLocaleString('en-NZ', {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    });
    return `${sign}${prefix}${body}${unit.suffix}`;
  };
}

/**
 * One value, compacted on its own. For stat tiles and tooltips, where there
 * is no column to agree with.
 */
export function compact(value, { currency = null, decimals = 1 } = {}) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  const prefix = currency ?? '';
  const abs = Math.abs(value);
  const unit = UNITS.find((u) => abs >= u.limit);
  if (!unit) {
    return `${value < 0 ? '-' : ''}${prefix}${abs.toLocaleString('en-NZ', {
      maximumFractionDigits: abs < 10 ? 2 : 0,
    })}`;
  }
  const n = abs / unit.divisor;
  // Keep the fractional digit up to three significant figures. Dropping it
  // at 10 turned £17,743,000 into "£18M", which loses three quarters of a
  // million pounds from a headline figure, and rounded a £99,668 bar label
  // up to a flat "£100K".
  return `${value < 0 ? '-' : ''}${prefix}${n.toLocaleString('en-NZ', {
    maximumFractionDigits: n < 100 ? decimals : 0,
  })}${unit.suffix}`;
}

/** A value shown in full, for tooltips and table views. */
export function exact(value, { currency = null, decimals = 0 } = {}) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  const prefix = currency ?? '';
  const sign = value < 0 ? '-' : '';
  return `${sign}${prefix}${Math.abs(value).toLocaleString('en-NZ', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })}`;
}

export function percent(value, { decimals = 1 } = {}) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return `${(value * 100).toFixed(decimals)}%`;
}

/**
 * A date tick, read in UTC.
 *
 * Dataset timestamps are UTC throughout the app (the frontend guide's §13
 * rule). Formatting them in the viewer's zone would move a Monday week-start
 * to the previous Sunday for anyone west of London, which silently shifts
 * every weekly point by one bucket.
 */
export function dateTick(value, granularity = 'week') {
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return '';
  const options =
    granularity === 'month'
      ? { month: 'short', year: '2-digit', timeZone: 'UTC' }
      : granularity === 'year'
        ? { year: 'numeric', timeZone: 'UTC' }
        : { day: 'numeric', month: 'short', timeZone: 'UTC' };
  return new Intl.DateTimeFormat('en-NZ', options).format(d);
}

/** The full date, for tooltips and table rows. */
export function dateFull(value) {
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return '';
  return new Intl.DateTimeFormat('en-NZ', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(d);
}

/**
 * How many date ticks fit, and which ones.
 *
 * Taking every nth point keeps the spacing even; dropping the label when it
 * would collide keeps it readable. 64px is roughly the width of "12 Oct" plus
 * breathing room.
 */
export function pickDateTicks(values, width, minSpacing = 64) {
  if (values.length === 0) return [];
  const maximum = Math.max(1, Math.floor(width / minSpacing));
  if (values.length <= maximum) return values.map((_, i) => i);
  const stride = Math.ceil(values.length / maximum);
  const indices = [];
  for (let i = 0; i < values.length; i += stride) indices.push(i);
  // Always show the last point: it is the one a reader looks for.
  if (indices[indices.length - 1] !== values.length - 1) {
    if (values.length - 1 - indices[indices.length - 1] < stride / 2) indices.pop();
    indices.push(values.length - 1);
  }
  return indices;
}
