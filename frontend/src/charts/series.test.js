import { describe, expect, it } from 'vitest';

import { emphasisPalette, foldTail, seriesPalette, slotColor } from './series.js';

describe('seriesPalette', () => {
  it('keeps a series on its colour when another is filtered out', () => {
    // The failure this prevents: a reader learns that Regency Cakestand is
    // orange, filters out the series above it, and the cakestand turns blue.
    const palette = seriesPalette(['cakestand', 'hanging heart', 'jumbo bag']);
    const before = palette.of('jumbo bag');
    palette.of('cakestand');
    expect(palette.of('jumbo bag')).toBe(before);
  });

  it('refuses a ninth colour instead of generating one', () => {
    const palette = seriesPalette(Array.from({ length: 8 }, (_, i) => `s${i}`));
    expect(() => palette.of('s8')).toThrow(/ninth series colour/i);
  });

  it('assigns the validated slots in order', () => {
    const palette = seriesPalette(['a', 'b']);
    expect(palette.of('a')).toBe('var(--series-1)');
    expect(palette.of('b')).toBe('var(--series-2)');
  });
});

describe('slotColor', () => {
  it('wraps rather than producing series-0 or series-9', () => {
    expect(slotColor(0)).toBe('var(--series-1)');
    expect(slotColor(8)).toBe('var(--series-1)');
    expect(slotColor(-1)).toBe('var(--series-8)');
  });
});

describe('emphasisPalette', () => {
  it('greys everything that is not the story', () => {
    const palette = emphasisPalette(['a', 'b', 'c', 'd'], ['b']);
    expect(palette.of('b')).toBe('var(--series-1)');
    expect(palette.of('a')).toBe('var(--series-muted)');
  });
});

describe('foldTail', () => {
  it('leaves a short list alone', () => {
    const rows = [{ label: 'a', value: 1 }];
    expect(foldTail(rows).rows).toHaveLength(1);
  });

  it('combines the tail rather than dropping it, so the total still adds up', () => {
    const rows = Array.from({ length: 12 }, (_, i) => ({ label: `p${i}`, value: 10 }));
    const { rows: folded, folded: count } = foldTail(rows, { limit: 5 });
    expect(folded).toHaveLength(5);
    expect(count).toBe(8);
    expect(folded[4].value).toBe(80);
    expect(folded[4].label).toBe('Other (8)');
    expect(folded.reduce((s, r) => s + r.value, 0)).toBe(120);
  });
});
