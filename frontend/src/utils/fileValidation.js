/**
 * Client-side checks before an upload starts. They exist for fast feedback
 * only. The server repeats every check, because anything in the browser can
 * be bypassed.
 */

const ACCEPTED_SUFFIXES = ['.csv', '.txt', '.xlsx', '.xlsm'];

// Browsers report these types inconsistently (Windows often calls a CSV
// application/vnd.ms-excel), so the extension is the real check and the type is
// only used to reject something clearly wrong, like an image.
const ACCEPTED_TYPES = [
  'text/csv',
  'text/plain',
  'application/vnd.ms-excel',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'application/vnd.ms-excel.sheet.macroEnabled.12',
  'application/octet-stream',
  '',
];

/** The `accept` attribute for a file input. */
export const ACCEPT_ATTRIBUTE = ACCEPTED_SUFFIXES.join(',');

/**
 * @param {File} file
 * @param {number} maxMb
 * @returns {string|null} a user-facing error message, or null if the file looks fine
 */
export function validateCsvFile(file, maxMb) {
  if (!file) return 'Choose a CSV or Excel file to upload.';

  const name = file.name.toLowerCase();
  if (!ACCEPTED_SUFFIXES.some((suffix) => name.endsWith(suffix))) {
    return `"${file.name}" is not a supported file type. Upload one of: ${ACCEPTED_SUFFIXES.join(', ')}.`;
  }
  if (!ACCEPTED_TYPES.includes(file.type)) {
    return `"${file.name}" does not look like a spreadsheet or CSV file (type: ${file.type}).`;
  }
  if (file.size === 0) return `"${file.name}" is empty.`;
  if (file.size > maxMb * 1024 * 1024) {
    return `"${file.name}" is larger than the ${maxMb} MB upload limit.`;
  }
  return null;
}
