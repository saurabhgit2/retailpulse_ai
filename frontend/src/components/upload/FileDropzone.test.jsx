import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FileDropzone } from './FileDropzone';

// applyAccept: false lets the test pick files the <input accept> would hide,
// so we can check our own validation rather than the browser's filter.
const user = () => userEvent.setup({ applyAccept: false });
const inputOf = (container) => container.querySelector('input[type="file"]');

describe('FileDropzone', () => {
  it('passes a valid CSV file to the parent', async () => {
    const onFileSelected = vi.fn();
    const { container } = render(<FileDropzone file={null} onFileSelected={onFileSelected} maxMb={10} />);
    const file = new File(['a,b\n1,2\n'], 'sales.csv', { type: 'text/csv' });

    await user().upload(inputOf(container), file);
    expect(onFileSelected).toHaveBeenCalledWith(file);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('rejects a non-CSV file with a message', async () => {
    const onFileSelected = vi.fn();
    const { container } = render(<FileDropzone file={null} onFileSelected={onFileSelected} maxMb={10} />);

    await user().upload(inputOf(container), new File(['x'], 'report.pdf', { type: 'application/pdf' }));
    expect(onFileSelected).toHaveBeenCalledWith(null);
    expect(screen.getByRole('alert')).toHaveTextContent('is not a CSV file');
  });

  it('rejects a file over the size limit', async () => {
    const onFileSelected = vi.fn();
    const tinyLimitMb = 4 / (1024 * 1024); // 4 bytes
    const { container } = render(<FileDropzone file={null} onFileSelected={onFileSelected} maxMb={tinyLimitMb} />);

    await user().upload(inputOf(container), new File(['a,b\n1,2\n'], 'sales.csv', { type: 'text/csv' }));
    expect(screen.getByRole('alert')).toHaveTextContent('larger than');
  });
});
