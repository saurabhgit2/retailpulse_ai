import { describe, expect, it } from 'vitest';
import { parseCsv, toCsv } from './csv';

describe('parseCsv', () => {
  it('keeps commas and escaped quotes inside quoted fields', () => {
    const text = 'Code,Description\n85123A,"PAPER CRAFT , LITTLE BIRDIE"\nX1,"NOTEBOOK ""A5"""\n';
    const { header, rows } = parseCsv(text);
    expect(header).toEqual(['Code', 'Description']);
    expect(rows).toEqual([
      ['85123A', 'PAPER CRAFT , LITTLE BIRDIE'],
      ['X1', 'NOTEBOOK "A5"'],
    ]);
  });

  it('handles Windows line endings and a byte-order mark', () => {
    const { header, rows } = parseCsv('\uFEFFa,b\r\n1,2\r\n');
    expect(header).toEqual(['a', 'b']);
    expect(rows).toEqual([['1', '2']]);
  });

  it('drops the cut-off last line when the text is only the start of a file', () => {
    const { rows, truncated } = parseCsv('a,b\n1,2\n3,', { isPartial: true });
    expect(rows).toEqual([['1', '2']]);
    expect(truncated).toBe(true);
  });

  it('stops after maxRows and reports that it did', () => {
    const { rows, truncated } = parseCsv('a\n1\n2\n3\n', { maxRows: 2 });
    expect(rows).toHaveLength(2);
    expect(truncated).toBe(true);
  });

  it('does not report truncation when the file has exactly maxRows rows', () => {
    const { rows, truncated } = parseCsv('a\n1\n2\n', { maxRows: 2 });
    expect(rows).toHaveLength(2);
    expect(truncated).toBe(false);
  });

  it('round-trips through toCsv', () => {
    const rows = [['1', 'has, comma'], ['2', 'has "quote"']];
    expect(parseCsv(toCsv(['id', 'text'], rows)).rows).toEqual(rows);
  });
});
