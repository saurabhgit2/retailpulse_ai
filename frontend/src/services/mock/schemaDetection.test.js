import { describe, expect, it } from 'vitest';
import { buildUploadProfile, normaliseHeader } from './schemaDetection';

// The header and a few rows in the layout of Online Retail II.
const HEADER = ['Invoice', 'StockCode', 'Description', 'Quantity', 'InvoiceDate', 'Price', 'Customer ID', 'Country'];
const ROWS = [
  ['489434', '85048', '15CM CHRISTMAS GLASS BALL 20 LIGHTS', '12', '2009-12-01 07:45:00', '6.95', '13085.0', 'United Kingdom'],
  ['489434', '79323P', 'PINK CHERRY LIGHTS', '12', '2009-12-01 07:45:00', '6.75', '13085.0', 'United Kingdom'],
  ['C489449', '22087', 'PAPER BUNTING WHITE LACE', '-12', '2009-12-01 10:33:00', '2.95', '', 'Australia'],
];

describe('schema detection (mock of the backend algorithm)', () => {
  it('normalises header names before matching synonyms', () => {
    expect(normaliseHeader('Customer ID')).toBe('customerid');
    expect(normaliseHeader('Invoice_Date')).toBe('invoicedate');
  });

  it('maps every Online Retail II column to the right canonical field', () => {
    const { suggested_mapping: mapping } = buildUploadProfile(HEADER, ROWS, { truncated: false });
    expect(mapping).toMatchObject({
      invoice_id: 'Invoice',
      product_code: 'StockCode',
      product_name: 'Description',
      quantity: 'Quantity',
      occurred_at: 'InvoiceDate',
      unit_price: 'Price',
      customer_id: 'Customer ID',
      region: 'Country',
      revenue: null,
      category: null,
    });
  });

  it('warns that revenue will be derived and category is missing', () => {
    const { warnings } = buildUploadProfile(HEADER, ROWS, { truncated: false });
    const codes = warnings.map((w) => w.code);
    expect(codes).toContain('REVENUE_WILL_BE_DERIVED');
    expect(codes).toContain('NO_CATEGORY');
  });

  it('does not map a column whose contents contradict its name', () => {
    const { suggested_mapping: mapping, warnings } = buildUploadProfile(
      ['Date', 'Price'],
      [['2020-01-01', 'n/a'], ['2020-01-02', 'call us']],
      { truncated: false },
    );
    expect(mapping.unit_price).toBeNull();
    expect(warnings.map((w) => w.code)).toContain('TYPE_MISMATCH');
  });

  it('flags ambiguous day/month dates', () => {
    const { warnings } = buildUploadProfile(['Date', 'Sales'], [['01/02/2010', '5'], ['03/04/2010', '7']], {
      truncated: false,
    });
    expect(warnings.map((w) => w.code)).toContain('AMBIGUOUS_DATE_FORMAT');
  });
});
