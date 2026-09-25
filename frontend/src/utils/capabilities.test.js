import { describe, expect, it } from 'vitest';
import { computeCapabilities, findDuplicateSources, findMissingRequired } from './capabilities';

const SALES = {
  key: 'sales_analytics',
  label: 'Sales',
  requires_all: ['occurred_at'],
  requires_one_of: [['revenue'], ['quantity', 'unit_price']],
};

describe('computeCapabilities', () => {
  it('accepts revenue derived from quantity and unit price', () => {
    const [result] = computeCapabilities({ occurred_at: 'Date', quantity: 'Qty', unit_price: 'Price' }, [SALES]);
    expect(result.enabled).toBe(true);
  });

  it('explains what is missing when no revenue path exists', () => {
    const [result] = computeCapabilities({ occurred_at: 'Date', quantity: 'Qty' }, [SALES]);
    expect(result.enabled).toBe(false);
    expect(result.missing).toEqual(['revenue or quantity + unit_price']);
  });
});

describe('mapping checks', () => {
  it('finds a column mapped to two fields', () => {
    expect(findDuplicateSources({ quantity: 'Qty', revenue: 'Qty', occurred_at: 'Date' })).toEqual(['Qty']);
  });

  it('lists required fields that are not mapped', () => {
    const fields = [
      { key: 'occurred_at', status: 'required' },
      { key: 'category', status: 'optional' },
    ];
    expect(findMissingRequired({ occurred_at: null }, fields)).toEqual(['occurred_at']);
  });
});
