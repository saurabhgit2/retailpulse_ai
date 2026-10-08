import { describe, expect, it } from 'vitest';
import { ACCEPT_ATTRIBUTE, validateCsvFile } from './fileValidation';

const file = (content = 'a,b\n1,2\n', name = 'sales.csv', type = 'text/csv') =>
  new File([content], name, { type });

const XLSX_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';

describe('validateCsvFile', () => {
  it('accepts a normal CSV file', () => {
    expect(validateCsvFile(file(), 200)).toBeNull();
  });

  it('accepts the MIME type Windows often reports for CSV', () => {
    expect(validateCsvFile(file('a\n1\n', 'sales.csv', 'application/vnd.ms-excel'), 200)).toBeNull();
  });

  it('accepts an Excel workbook, which is how Online Retail II is distributed', () => {
    expect(validateCsvFile(file('x', 'online_retail_II.xlsx', XLSX_TYPE), 200)).toBeNull();
  });

  it('accepts a workbook the browser reports as a generic binary', () => {
    expect(validateCsvFile(file('x', 'data.xlsx', 'application/octet-stream'), 200)).toBeNull();
  });

  it('rejects unsupported extensions', () => {
    expect(validateCsvFile(file('x', 'report.pdf', 'application/pdf'), 200)).toMatch(
      /not a supported file type/,
    );
  });

  it('rejects a supported extension carrying an obviously wrong type', () => {
    expect(validateCsvFile(file('x', 'sales.csv', 'image/png'), 200)).toMatch(/does not look like/);
  });

  it('rejects empty files', () => {
    expect(validateCsvFile(file(''), 200)).toMatch(/empty/);
  });

  it('rejects files over the size limit', () => {
    const tinyLimitMb = 5 / (1024 * 1024); // 5 bytes
    expect(validateCsvFile(file('0123456789'), tinyLimitMb)).toMatch(/larger than/);
  });

  it('exposes an accept attribute covering every supported suffix', () => {
    expect(ACCEPT_ATTRIBUTE).toContain('.csv');
    expect(ACCEPT_ATTRIBUTE).toContain('.xlsx');
  });
});
