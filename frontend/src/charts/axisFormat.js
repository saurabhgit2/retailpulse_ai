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
    // Zero carries no unit. "0.0K" is a thousand of nothing and reads as a
    // rounding artefact on the axis a bar chart sits on.
    if (value === 0) return `${prefix}0`;
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
  return thinLabels(values.length, width, minSpacing);
}

/**
 * Where to anchor a tick label so it stays inside the plot.
 *
 * A label centred under the last bar runs off the right-hand edge and is
 * clipped by the SVG viewport, which is worse than it sounds: "£119,626"
 * renders as "£119,62", a number that looks complete and is wrong by a
 * factor of ten. The first label can do the same thing on the left.
 *
 * Width is estimated from the character count rather than measured. Measuring
 * means `getComputedTextLength`, which forces a layout on every label on
 * every render; the estimate only has to be good enough to decide which of
 * three anchors to use, and the digits these axes carry are near enough
 * fixed-width to make it reliable.
 */
export function labelAnchor(text, centre, width, perChar = 5.3) {
  const half = (String(text ?? '').length * perChar) / 2;
  if (centre - half < 0) return { anchor: 'start', x: 0 };
  if (centre + half > width) return { anchor: 'end', x: width };
  return { anchor: 'middle', x: centre };
}

/**
 * Which of `count` evenly spaced labels to draw in `width` pixels.
 *
 * Shared by the date axis and the column axis, because both got the same
 * thing wrong independently: taking every nth label and then forcing the last
 * one in leaves a short gap before it, and the label it crowds has to go.
 *
 * The gap is measured in pixels, not in strides. A fraction of the stride
 * looks like the same test and is not: with 107 weekly points in 560px the
 * remainder was 8 of a 14 stride, which passed, while leaving the final two
 * labels 42px apart and overlapping on screen.
 */
export function thinLabels(count, width, minSpacing = 64) {
  if (count <= 0) return [];
  const maximum = Math.max(1, Math.floor(width / minSpacing));
  if (count <= maximum) return Array.from({ length: count }, (_, i) => i);
  const stride = Math.ceil(count / maximum);
  const indices = [];
  for (let i = 0; i < count; i += stride) indices.push(i);

  const last = count - 1;
  if (indices[indices.length - 1] !== last) {
    const perStep = width / Math.max(1, last);
    while (indices.length > 1 && (last - indices[indices.length - 1]) * perStep < minSpacing) {
      indices.pop();
    }
    indices.push(last);
  }
  return indices;
}
