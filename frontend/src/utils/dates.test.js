import { describe, expect, it } from 'vitest';
import { detectDateFormats, parseDate } from './dates';

describe('date parsing', () => {
  it('reads the same text differently depending on the format', () => {
    expect(parseDate('03/04/2010', 'dmy').toISOString()).toBe('2010-04-03T00:00:00.000Z');
    expect(parseDate('03/04/2010', 'mdy').toISOString()).toBe('2010-03-04T00:00:00.000Z');
  });

  it('rejects impossible dates instead of rolling them over', () => {
    expect(parseDate('31/02/2010', 'dmy')).toBeNull();
    expect(parseDate('2024-13-45 10:00:00', 'iso')).toBeNull();
  });

  it('reads ISO timestamps', () => {
    expect(parseDate('2009-12-01 07:45:00', 'iso').toISOString()).toBe('2009-12-01T07:45:00.000Z');
  });
});

describe('detectDateFormats', () => {
  it('flags day/month vs month/day as ambiguous when both fit', () => {
    const result = detectDateFormats(['01/02/2010 08:26', '05/06/2010 09:00']);
    expect(result.ambiguous).toBe(true);
  });

  it('is not ambiguous once a value rules one format out', () => {
    const result = detectDateFormats(['12/13/2010 08:26', '12/01/2010 09:00'], 0.95);
    expect(result.candidates).toEqual(['mdy']);
    expect(result.ambiguous).toBe(false);
  });
});
