/**
 * Client-side checks before an upload starts. They exist for fast feedback
 * only. The server repeats every check, because anything in the browser can
 * be bypassed.
 */

const ACCEPTED_TYPES = ['text/csv', 'application/vnd.ms-excel', 'text/plain', ''];

/**
 * @param {File} file
 * @param {number} maxMb
 * @returns {string|null} a user-facing error message, or null if the file looks fine
 */
export function validateCsvFile(file, maxMb) {
  if (!file) return 'Choose a CSV file to upload.';
  if (!file.name.toLowerCase().endsWith('.csv')) {
    return `"${file.name}" is not a CSV file. Export your data as .csv and try again.`;
  }
  // Browsers report CSV types inconsistently (Windows often says
  // application/vnd.ms-excel), so only clearly wrong types are rejected.
  if (!ACCEPTED_TYPES.includes(file.type)) {
    return `"${file.name}" does not look like a text CSV file (type: ${file.type}).`;
  }
  if (file.size === 0) return `"${file.name}" is empty.`;
  if (file.size > maxMb * 1024 * 1024) {
    return `"${file.name}" is larger than the ${maxMb} MB upload limit.`;
  }
  return null;
}
