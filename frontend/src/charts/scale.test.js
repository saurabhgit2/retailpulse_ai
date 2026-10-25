import { describe, expect, it } from 'vitest';

import {
  bandScale,
  extent,
  linearScale,
  nearestIndex,
  niceDomain,
  niceTicks,
  tickStep,
} from './scale.js';

describe('extent', () => {
  it('ignores nulls and non-finite values rather than returning NaN', () => {
    expect(extent([3, null, 7, undefined, NaN, Infinity, 1])).toEqual({ min: 1, max: 7 });
  });

  it('returns null when nothing is plottable', () => {
    expect(extent([null, undefined, NaN])).toBeNull();
  });
});

describe('linearScale', () => {
  it('maps the domain onto the range', () => {
    const s = linearScale({ domain: [0, 100], range: [0, 200] });
    expect(s(50)).toBe(100);
  });

  it('inverts a range that runs downward, as a y axis does', () => {
    const s = linearScale({ domain: [0, 10], range: [100, 0] });
    expect(s(0)).toBe(100);
    expect(s(10)).toBe(0);
  });

  it('puts a flat series in the middle instead of dividing by zero', () => {
    // A week where every day took exactly the same revenue is real data, and
    // the alternative here is NaN, which renders as an empty chart.
    const s = linearScale({ domain: [5, 5], range: [0, 100] });
    expect(s(5)).toBe(50);
    expect(Number.isNaN(s(5))).toBe(false);
  });

  it('returns null for an unplottable value so the caller can break the line', () => {
    const s = linearScale({ domain: [0, 10], range: [0, 100] });
    expect(s(null)).toBeNull();
    expect(s(NaN)).toBeNull();
  });

  it('round-trips through invert', () => {
    const s = linearScale({ domain: [12, 480], range: [0, 300] });
    expect(s.invert(s(240))).toBeCloseTo(240, 9);
  });
});

describe('tickStep', () => {
  it('only ever returns 1, 2 or 5 times a power of ten', () => {
    for (const [min, max] of [[0, 1], [0, 7], [0, 93], [0, 1040], [0, 0.03], [-50, 50]]) {
      const step = tickStep(min, max, 5);
      const mantissa = step / 10 ** Math.floor(Math.log10(step));
      expect([1, 2, 5, 10]).toContain(Math.round(mantissa * 1e6) / 1e6);
    }
  });
});

describe('niceDomain', () => {
  it('includes zero by default, so a bar baseline is never truncated', () => {
    expect(niceDomain(120, 180)[0]).toBe(0);
  });

  it('can be told not to, for a line that never approaches zero', () => {
    const [lo] = niceDomain(120, 180, { includeZero: false });
    expect(lo).toBeGreaterThan(0);
  });

  it('pads a flat series so the line is not drawn on the axis', () => {
    const [lo, hi] = niceDomain(7, 7, { includeZero: false });
    expect(lo).toBeLessThan(7);
    expect(hi).toBeGreaterThan(7);
  });

  it('pads an all-zero series without producing a zero-width domain', () => {
    const [lo, hi] = niceDomain(0, 0);
    expect(hi).toBeGreaterThan(lo);
  });
});

describe('niceTicks', () => {
  it('produces round values covering the domain', () => {
    expect(niceTicks(0, 100, 4)).toEqual([0, 20, 40, 60, 80, 100]);
  });

  it('stays near the requested count instead of always rounding the step up', () => {
    // An implied step of exactly 25 snaps to 20, not to 50. Rounding up
    // would answer a request for four ticks with two.
    expect(niceTicks(0, 100, 4).length).toBeGreaterThanOrEqual(4);
    expect(niceTicks(0, 1000, 5).length).toBeGreaterThanOrEqual(5);
  });

  it('carries no floating-point dust', () => {
    // Accumulating 0.1 at a time gives 0.30000000000000004, which renders.
    for (const t of niceTicks(0, 1, 10)) {
      expect(String(t).length).toBeLessThan(6);
    }
  });

  it('terminates on a degenerate domain instead of looping', () => {
    expect(niceTicks(5, 5)).toEqual([5]);
    expect(niceTicks(NaN, 10)).toEqual([]);
  });
});

describe('bandScale', () => {
  it('caps the bar thickness and turns the leftover into air on both sides', () => {
    // Three rows in a tall card would otherwise give 100px-thick bars.
    const s = bandScale({ domain: ['a', 'b', 'c'], range: [0, 300], maxBandwidth: 24 });
    expect(s.bandwidth()).toBe(24);
    const slotCentre = s.step() / 2;
    expect(s('a') + 12).toBeCloseTo(slotCentre, 6);
  });

  it('never returns a bandwidth below one pixel', () => {
    const s = bandScale({ domain: Array.from({ length: 400 }, (_, i) => i), range: [0, 100] });
    expect(s.bandwidth()).toBeGreaterThanOrEqual(1);
  });

  it('returns null for a key it does not know', () => {
    expect(bandScale({ domain: ['a'], range: [0, 10] })('zzz')).toBeNull();
  });
});

describe('nearestIndex', () => {
  it('snaps to the closest position, which is what the crosshair needs', () => {
    expect(nearestIndex([0, 50, 100], 60)).toBe(1);
    expect(nearestIndex([0, 50, 100], 80)).toBe(2);
  });

  it('reports -1 on an empty series rather than throwing', () => {
    expect(nearestIndex([], 10)).toBe(-1);
  });
});
