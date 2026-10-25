/**
 * Scales: the mapping from a data value to a pixel position.
 *
 * These are plain functions with no React and no SVG in them, for the same
 * reason `app/analytics/` has no FastAPI in it: the awkward cases (a flat
 * series, a single point, an all-zero column) are where charts actually go
 * wrong, and those are only cheap to test when the mapping is separable from
 * the drawing.
 */

/** Smallest and largest finite value in a list, or null when there is none. */
export function extent(values) {
  let min = Infinity;
  let max = -Infinity;
  for (const v of values) {
    if (v === null || v === undefined || !Number.isFinite(v)) continue;
    if (v < min) min = v;
    if (v > max) max = v;
  }
  return min === Infinity ? null : { min, max };
}

/**
 * A linear mapping from `domain` to `range`.
 *
 * A zero-width domain (every value identical, which a flat week of sales
 * really does produce) would divide by zero, so it maps to the middle of the
 * range instead. Returning NaN there would silently produce an empty chart.
 */
export function linearScale({ domain, range }) {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const span = d1 - d0;

  const scale = (value) => {
    if (value === null || value === undefined || !Number.isFinite(value)) return null;
    if (span === 0) return (r0 + r1) / 2;
    return r0 + ((value - d0) / span) * (r1 - r0);
  };

  scale.invert = (pixel) => {
    if (r1 - r0 === 0) return d0;
    return d0 + ((pixel - r0) / (r1 - r0)) * span;
  };
  scale.domain = () => [d0, d1];
  scale.range = () => [r0, r1];
  return scale;
}

/**
 * Round a domain outward to values a reader can hold in their head.
 *
 * `includeZero` defaults to true because a bar chart whose baseline is not
 * zero exaggerates every difference on it. Line charts of a quantity that
 * never approaches zero pass `false` and say so in the chart's footnote.
 */
export function niceDomain(min, max, { count = 5, includeZero = true } = {}) {
  let lo = min;
  let hi = max;
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [0, 1];
  if (includeZero) {
    lo = Math.min(lo, 0);
    hi = Math.max(hi, 0);
  }
  if (lo === hi) {
    // A flat series still needs a visible band around the line.
    const pad = lo === 0 ? 1 : Math.abs(lo) * 0.1;
    return [lo - pad, hi + pad];
  }
  const step = tickStep(lo, hi, count);
  return [Math.floor(lo / step) * step, Math.ceil(hi / step) * step];
}

/**
 * The 1 / 2 / 5 × 10^n step nearest the one the requested tick count implies.
 *
 * The thresholds are the geometric midpoints between the candidates
 * (sqrt(50), sqrt(10), sqrt(2)) rather than the candidates themselves. Using
 * the candidates — "step <= 2 means 2, otherwise 5" — always rounds upward,
 * so an exact-25 step becomes 50 and an axis asked for four ticks comes back
 * with two. Snapping to the nearer candidate keeps the count close to what
 * was asked for.
 */
const E10 = Math.sqrt(50);
const E5 = Math.sqrt(10);
const E2 = Math.sqrt(2);

export function tickStep(min, max, count = 5) {
  const rough = (max - min) / Math.max(1, count);
  if (!Number.isFinite(rough) || rough <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const normalised = rough / magnitude;
  let nice;
  if (normalised >= E10) nice = 10;
  else if (normalised >= E5) nice = 5;
  else if (normalised >= E2) nice = 2;
  else nice = 1;
  return nice * magnitude;
}

/** Evenly spaced round values covering [min, max]. */
export function niceTicks(min, max, count = 5) {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [];
  if (min === max) return [min];
  const step = tickStep(min, max, count);
  const start = Math.ceil(min / step) * step;
  const ticks = [];
  // Multiply rather than accumulate: repeated addition of 0.1 drifts.
  for (let i = 0; start + i * step <= max + step * 1e-9; i += 1) {
    const value = start + i * step;
    // Clear the floating-point dust that 0.1 + 0.2 leaves behind.
    ticks.push(Number(value.toPrecision(12)));
    if (ticks.length > 1000) break;
  }
  return ticks;
}

/**
 * Categorical positions, one slot per item.
 *
 * `maxBandwidth` caps the mark thickness. The skill's rule is that a bar never
 * fills its slot: with four products in a wide card, 24px bars with air around
 * them read better than four fat blocks.
 */
export function bandScale({ domain, range, paddingInner = 0.25, maxBandwidth = 24 }) {
  const [r0, r1] = range;
  const n = domain.length;
  const index = new Map(domain.map((d, i) => [d, i]));
  const total = r1 - r0;
  const step = n > 0 ? total / n : total;
  const natural = step * (1 - paddingInner);
  const bandwidth = Math.max(1, Math.min(natural, maxBandwidth));

  const scale = (value) => {
    const i = index.get(value);
    if (i === undefined) return null;
    // Centre the capped band inside its slot, so the leftover becomes air on
    // both sides instead of a gap on one.
    return r0 + i * step + (step - bandwidth) / 2;
  };
  scale.bandwidth = () => bandwidth;
  scale.step = () => step;
  scale.centre = (value) => {
    const start = scale(value);
    return start === null ? null : start + bandwidth / 2;
  };
  scale.domain = () => domain.slice();
  return scale;
}

/** The datum whose x pixel is nearest `pixel`; what the crosshair snaps to. */
export function nearestIndex(positions, pixel) {
  if (positions.length === 0) return -1;
  let best = 0;
  let bestDistance = Infinity;
  for (let i = 0; i < positions.length; i += 1) {
    const d = Math.abs(positions[i] - pixel);
    if (d < bestDistance) {
      bestDistance = d;
      best = i;
    }
  }
  return best;
}
