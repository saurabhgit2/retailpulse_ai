import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ColumnMappingTable } from './ColumnMappingTable';

const FIELDS = [
  { key: 'occurred_at', label: 'Transaction date/time', status: 'required', description: 'When it happened.' },
  { key: 'invoice_id', label: 'Invoice / order ID', status: 'recommended', description: 'Groups lines.' },
  { key: 'product_code', label: 'Product code / SKU', status: 'recommended', description: 'The product.' },
];
const COLUMNS = [
  { name: 'InvoiceDate', inferred_type: 'datetime', null_count_sample: 0, sample_values: ['2009-12-01 07:45:00'] },
  { name: 'Invoice', inferred_type: 'text', null_count_sample: 0, sample_values: ['489434'] },
  { name: 'StockCode', inferred_type: 'text', null_count_sample: 0, sample_values: ['85048'] },
];

describe('ColumnMappingTable', () => {
  it('disables a column in other rows once it is used, so it cannot be mapped twice', () => {
    render(
      <ColumnMappingTable
        fields={FIELDS}
        columns={COLUMNS}
        mapping={{ occurred_at: 'InvoiceDate', invoice_id: 'Invoice', product_code: null }}
        onChange={() => {}}
      />,
    );
    const productSelect = screen.getByLabelText('Product code / SKU');
    const invoiceOption = [...productSelect.options].find((o) => o.value === 'Invoice');
    expect(invoiceOption).toBeDisabled();
    expect(invoiceOption).toHaveTextContent('(used for Invoice / order ID)');
  });

  it('reports each change as (field, column)', async () => {
    const onChange = vi.fn();
    render(
      <ColumnMappingTable
        fields={FIELDS}
        columns={COLUMNS}
        mapping={{ occurred_at: 'InvoiceDate', invoice_id: null, product_code: null }}
        onChange={onChange}
      />,
    );
    await userEvent.selectOptions(screen.getByLabelText('Product code / SKU'), 'StockCode');
    expect(onChange).toHaveBeenCalledWith('product_code', 'StockCode');
  });

  it('marks an unmapped required field', () => {
    render(
      <ColumnMappingTable fields={FIELDS} columns={COLUMNS} mapping={{ occurred_at: null }} onChange={() => {}} />,
    );
    expect(screen.getByText('Required: choose a column.')).toBeInTheDocument();
  });
});
