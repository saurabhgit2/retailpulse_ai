import { describe, expect, it } from 'vitest';
import { runMockPipeline } from './mockProcessing';
import { DEFAULT_PROCESSING_OPTIONS } from './fixtures';

const HEADER = ['Invoice', 'StockCode', 'Quantity', 'InvoiceDate', 'Price', 'Customer ID'];
const MAPPING = {
  invoice_id: 'Invoice',
  product_code: 'StockCode',
  quantity: 'Quantity',
  occurred_at: 'InvoiceDate',
  unit_price: 'Price',
  customer_id: 'Customer ID',
};
// Product codes look like real stock codes: short codes such as 'B' or 'M' are
// fee/adjustment codes in Online Retail II and would be excluded.
const ROWS = [
  ['1001', '85123A', '2', '2024-01-01 09:00:00', '3.00', '501'],
  ['1001', '85123A', '2', '2024-01-01 09:00:00', '3.00', '501'], // exact duplicate
  ['1002', 'POST', '1', '2024-01-02 09:00:00', '18.00', '502'], // fee line
  ['1003', '22423', '1', '2024-01-03 09:00:00', '0.00', '503'], // zero price
  ['C1004', '85123A', '-1', '2024-01-04 09:00:00', '3.00', '501'], // return (kept)
  ['1005', '22423', '4', 'not a date', '2.50', ''], // invalid date
  ['1006', '22423', '4', '2024-01-05 09:00:00', '2.50', ''], // guest (kept)
];

function run(options = {}) {
  return runMockPipeline({
    header: HEADER,
    rows: ROWS,
    mapping: MAPPING,
    options: { ...DEFAULT_PROCESSING_OPTIONS, date_format: 'iso', ...options },
    fileTruncated: false,
  }).report;
}

describe('mock cleaning pipeline', () => {
  it('accounts for every row: kept + excluded = rows in file (conservation)', () => {
    const report = run();
    expect(report.conservation.ok).toBe(true);
    expect(report.summary.rows_clean + report.summary.rows_excluded).toBe(ROWS.length);
  });

  it('records one exclusion per problem, with the reason', () => {
    const { excluded_by_reason: excluded } = run();
    expect(excluded).toMatchObject({ invalid_value: 1, exact_duplicate: 1, non_product_code: 1, non_positive_price: 1 });
  });

  it('flags returns and guest rows instead of deleting them', () => {
    const { summary } = run();
    expect(summary.rows_clean).toBe(3);
    expect(summary.rows_returns_flagged).toBe(1);
    expect(summary.rows_guest).toBe(1);
  });

  it('respects the option to keep duplicates', () => {
    const { excluded_by_reason: excluded } = run({ drop_exact_duplicates: false });
    expect(excluded.exact_duplicate).toBeUndefined();
  });
});
