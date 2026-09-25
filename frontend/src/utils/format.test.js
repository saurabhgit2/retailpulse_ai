import { describe, expect, it } from 'vitest';
import { formatBytes, formatDate, formatNumber, formatPercent } from './format';

describe('format helpers', () => {
  it('formats whole numbers with thousands separators', () => {
    expect(formatNumber(1067371)).toBe('1,067,371');
  });

  it('shows a dash for missing values instead of "NaN" or "0"', () => {
    expect(formatNumber(null)).toBe('—');
    expect(formatNumber(undefined)).toBe('—');
    expect(formatPercent(null)).toBe('—');
  });

  it('formats ratios as percentages', () => {
    expect(formatPercent(0.1234)).toBe('12.3%');
    expect(formatPercent(0.5, { digits: 0 })).toBe('50%');
  });

  it('formats file sizes in binary units', () => {
    expect(formatBytes(512)).toBe('512 bytes');
    expect(formatBytes(1536)).toBe('1.5 KB');
    expect(formatBytes(95 * 1024 * 1024)).toBe('95.0 MB');
  });

  it('shows dataset dates exactly as recorded when utc is set', () => {
    // 23:30 UTC would be the next day in New Zealand; the utc option prevents that shift.
    expect(formatDate('2011-12-09T23:30:00Z', { utc: true })).toBe('9 Dec 2011');
  });
});
