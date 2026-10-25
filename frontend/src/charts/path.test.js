import { describe, expect, it } from 'vitest';

import { bandPath, barPath, isolatedPoints, linePath, segments } from './path.js';

const p = (x, y) => ({ x, y });

describe('segments', () => {
  it('breaks a run at a missing value', () => {
    const runs = segments([p(0, 1), p(1, 2), p(2, null), p(3, 4), p(4, 5)]);
    expect(runs.map((r) => r.length)).toEqual([2, 2]);
  });

  it('treats NaN and undefined as missing, not as zero', () => {
    expect(segments([p(0, NaN), p(1, undefined), p(2, 3)]).length).toBe(1);
  });
});

describe('linePath', () => {
  it('draws a gap rather than a line across missing data', () => {
    // A closed trading week must not become a confident diagonal: that is an
    // observation the data does not contain.
    const d = linePath([p(0, 10), p(1, 20), p(2, null), p(3, 40)]);
    expect(d.match(/M/g)).toHaveLength(2);
  });

  it('produces an empty string when nothing is plottable', () => {
    expect(linePath([p(0, null), p(1, null)])).toBe('');
  });
});

describe('isolatedPoints', () => {
  it('finds a point with no drawable neighbour', () => {
    // One week of trade between two closures draws as a zero-length path,
    // which is invisible. The chart renders these as dots instead.
    const alone = isolatedPoints([p(0, null), p(1, 5), p(2, null), p(3, 1), p(4, 2)]);
    expect(alone).toHaveLength(1);
    expect(alone[0].x).toBe(1);
  });

  it('finds nothing in a continuous series', () => {
    expect(isolatedPoints([p(0, 1), p(1, 2), p(2, 3)])).toHaveLength(0);
  });
});

describe('bandPath', () => {
  it('closes the shape so it can be filled', () => {
    const d = bandPath([
      { x: 0, upper: 10, lower: 2 },
      { x: 1, upper: 12, lower: 4 },
    ]);
    expect(d.endsWith('Z')).toBe(true);
  });

  it('breaks the band wherever the interval is missing', () => {
    const d = bandPath([
      { x: 0, upper: 10, lower: 2 },
      { x: 1, upper: null, lower: null },
      { x: 2, upper: 12, lower: 4 },
      { x: 3, upper: 13, lower: 5 },
    ]);
    expect(d.match(/Z/g)).toHaveLength(2);
  });
});

describe('barPath', () => {
  it('rounds only the data end, leaving the baseline square', () => {
    const d = barPath({ x: 0, y: 0, width: 100, height: 20, radius: 4, side: 'right' });
    // Two quadratic curves at the right-hand end, none at the baseline.
    expect(d.match(/Q/g)).toHaveLength(2);
  });

  it('does not turn inside out on a bar shorter than its own radius', () => {
    // A product with near-zero revenue produces a 1px bar; a 4px radius on it
    // would produce a path with negative control points.
    const d = barPath({ x: 0, y: 0, width: 1, height: 20, radius: 4, side: 'right' });
    expect(d).not.toMatch(/-\d/);
  });

  it('degrades to a plain rectangle at zero length', () => {
    const d = barPath({ x: 0, y: 0, width: 0, height: 20, side: 'right' });
    expect(d).not.toMatch(/Q/);
  });
});
