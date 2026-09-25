import { useId, useState } from 'react';
import { validateCsvFile } from '../../utils/fileValidation';
import { formatBytes } from '../../utils/format';
import { MAX_UPLOAD_MB } from '../../utils/constants';

/**
 * Choose a CSV by clicking or by dragging a file onto the box.
 *
 * The visible box is a <label> for a hidden file <input>: clicking anywhere on
 * it opens the file picker, and keyboard users can still tab to the input.
 * The component checks the file and reports either onFileSelected(file) or an
 * error message. It does not upload anything itself.
 */
export function FileDropzone({ file, onFileSelected, maxMb = MAX_UPLOAD_MB, disabled = false }) {
  const inputId = useId();
  const [error, setError] = useState(null);
  const [dragging, setDragging] = useState(false);

  function accept(candidate) {
    const problem = validateCsvFile(candidate, maxMb);
    setError(problem);
    onFileSelected(problem ? null : candidate);
  }

  function handleDrop(event) {
    event.preventDefault(); // stop the browser from opening the file
    setDragging(false);
    if (disabled) return;
    const dropped = event.dataTransfer.files?.[0];
    if (dropped) accept(dropped);
  }

  return (
    <div>
      <label
        htmlFor={inputId}
        onDragOver={(event) => {
          event.preventDefault();
          if (!disabled) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-6 py-10 text-center transition-colors ${
          dragging ? 'border-accent bg-accent-soft' : 'border-rule bg-surface hover:bg-surface-2'
        } ${disabled ? 'cursor-not-allowed opacity-60' : ''}`}
      >
        <span className="text-sm font-semibold text-ink">
          {file ? file.name : 'Drop a CSV file here, or click to choose one'}
        </span>
        <span className="text-xs text-muted">
          {file ? formatBytes(file.size) : `CSV only · up to ${maxMb} MB`}
        </span>
      </label>
      <input
        id={inputId}
        type="file"
        accept=".csv,text/csv"
        className="sr-only"
        disabled={disabled}
        aria-describedby={error ? `${inputId}-error` : undefined}
        onChange={(event) => {
          const chosen = event.target.files?.[0];
          if (chosen) accept(chosen);
          event.target.value = ''; // allow choosing the same file again
        }}
      />
      {error && (
        <p id={`${inputId}-error`} role="alert" className="mt-2 text-sm text-crit">
          {error}
        </p>
      )}
    </div>
  );
}
