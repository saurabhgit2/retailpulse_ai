import { describe, expect, it } from 'vitest';
import { validateCsvFile } from './fileValidation';

const csv = (content = 'a,b\n1,2\n', name = 'sales.csv', type = 'text/csv') => new File([content], name, { type });

describe('validateCsvFile', () => {
  it('accepts a normal CSV file', () => {
    expect(validateCsvFile(csv(), 200)).toBeNull();
  });

  it('accepts the MIME type Windows often reports for CSV', () => {
    expect(validateCsvFile(csv('a\n1\n', 'sales.csv', 'application/vnd.ms-excel'), 200)).toBeNull();
  });

  it('rejects other extensions', () => {
    expect(validateCsvFile(csv('x', 'sales.xlsx'), 200)).toMatch(/not a CSV file/);
  });

  it('rejects empty files', () => {
    expect(validateCsvFile(csv(''), 200)).toMatch(/empty/);
  });

  it('rejects files over the size limit', () => {
    const tinyLimitMb = 5 / (1024 * 1024); // 5 bytes
    expect(validateCsvFile(csv('0123456789'), tinyLimitMb)).toMatch(/larger than/);
  });
});
