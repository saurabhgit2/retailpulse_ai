/**
 * SVG path strings for lines, bands and bars.
 *
 * The one rule that matters here: a missing value is a gap, never a straight
 * line drawn across it. A retail series with a closed trading week would
 * otherwise show a confident diagonal through the closure, which is an
 * invented observation.
 */

/**
 * Split points into runs of consecutive drawable points.
 * A point is drawable when both coordinates are finite.
 */
export function segments(points) {
  const runs = [];
  let current = [];
  for (const p of points) {
    const ok =
      p &&
      Number.isFinite(p.x) &&
      p.y !== null &&
      p.y !== undefined &&
      Number.isFinite(p.y);
    if (ok) {
      current.push(p);
    } else if (current.length) {
      runs.push(current);
      current = [];
    }
  }
  if (current.length) runs.push(current);
  return runs;
}

const round = (n) => Math.round(n * 100) / 100;

/**
 * A polyline through the points, with gaps where data is missing.
 *
 * A single isolated point produces a zero-length path, which renders as
 * nothing with a round linecap set and as nothing at all without one, so
 * `markersFor` below reports those points and the chart draws them as dots.
 */
export function linePath(points) {
  return segments(points)
    .map((run) =>
      run
        .map((p, i) => `${i === 0 ? 'M' : 'L'}${round(p.x)},${round(p.y)}`)
        .join(' '),
    )
    .join(' ');
}

/** Points that have no drawable neighbour, so the line alone would hide them. */
export function isolatedPoints(points) {
  return segments(points)
    .filter((run) => run.length === 1)
    .map((run) => run[0]);
}

/**
 * A filled band between an upper and a lower edge, for prediction intervals.
 *
 * Both edges are walked from the same run boundaries, so a gap in the forecast
 * is a gap in the band. Drawing the band across a gap would imply the model
 * made a claim it did not make.
 */
export function bandPath(points) {
  const runs = segments(
    points.map((p) => ({
      x: p.x,
      y: Number.isFinite(p.upper) && Number.isFinite(p.lower) ? p.upper : null,
      upper: p.upper,
      lower: p.lower,
    })),
  );
  return runs
    .map((run) => {
      const forward = run
        .map((p, i) => `${i === 0 ? 'M' : 'L'}${round(p.x)},${round(p.upper)}`)
        .join(' ');
      const back = run
        .slice()
        .reverse()
        .map((p) => `L${round(p.x)},${round(p.lower)}`)
        .join(' ');
      return `${forward} ${back} Z`;
    })
    .join(' ');
}

/**
 * A rectangle with the two far corners rounded.
 *
 * The skill's bar spec is a 4px rounded data-end and a square baseline, which
 * `rx` on a `<rect>` cannot express: it rounds all four. `side` names the end
 * the value grows towards.
 */
export function barPath({ x, y, width, height, radius = 4, side = 'top' }) {
  const w = Math.max(0, width);
  const h = Math.max(0, height);
  // A bar shorter than its own corner radius would turn inside out.
  const r = Math.max(0, Math.min(radius, side === 'top' || side === 'bottom' ? h : w, w / 2, h / 2));
  const [l, t, right, b] = [round(x), round(y), round(x + w), round(y + h)];
  if (r === 0) return `M${l},${t} L${right},${t} L${right},${b} L${l},${b} Z`;

  if (side === 'top') {
    return `M${l},${b} L${l},${t + r} Q${l},${t} ${l + r},${t} L${right - r},${t} Q${right},${t} ${right},${t + r} L${right},${b} Z`;
  }
  if (side === 'right') {
    return `M${l},${t} L${right - r},${t} Q${right},${t} ${right},${t + r} L${right},${b - r} Q${right},${b} ${right - r},${b} L${l},${b} Z`;
  }
  if (side === 'bottom') {
    return `M${l},${t} L${right},${t} L${right},${b - r} Q${right},${b} ${right - r},${b} L${l + r},${b} Q${l},${b} ${l},${b - r} Z`;
  }
  // left
  return `M${right},${t} L${l + r},${t} Q${l},${t} ${l},${t + r} L${l},${b - r} Q${l},${b} ${l + r},${b} L${right},${b} Z`;
}
