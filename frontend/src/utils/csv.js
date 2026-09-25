/**
 * A small CSV parser (RFC 4180 style).
 *
 * Why not split on commas? Because real data contains commas inside quoted
 * fields, e.g.  "PAPER CRAFT , LITTLE BIRDIE"  and quotes inside quotes ("").
 * This parser walks the text one character at a time and tracks whether it is
 * inside a quoted field.
 *
 * The frontend only uses it for previews in mock mode; the real parsing is done
 * by pandas in the backend.
 */

/**
 * @param {string} text        CSV text
 * @param {object} options
 * @param {number} [options.maxRows]    stop after this many data rows
 * @param {boolean} [options.isPartial] text is the start of a larger file, so the
 *                                      last line may be cut off and is dropped
 * @returns {{ header: string[], rows: string[][], truncated: boolean }}
 */
export function parseCsv(text, { maxRows = Infinity, isPartial = false } = {}) {
  const source = text.charCodeAt(0) === 0xfeff ? text.slice(1) : text; // strip byte-order mark
  const records = [];
  let field = '';
  let record = [];
  let inQuotes = false;
  let truncated = false;

  const endRecord = () => {
    record.push(field);
    field = '';
    // Skip completely empty lines.
    if (!(record.length === 1 && record[0] === '')) records.push(record);
    record = [];
  };

  for (let i = 0; i < source.length; i += 1) {
    const char = source[i];

    if (inQuotes) {
      if (char === '"') {
        if (source[i + 1] === '"') {
          field += '"'; // escaped quote
          i += 1;
        } else {
          inQuotes = false;
        }
      } else {
        field += char;
      }
      continue;
    }

    if (char === '"') {
      inQuotes = true;
    } else if (char === ',') {
      record.push(field);
      field = '';
    } else if (char === '\n' || char === '\r') {
      if (char === '\r' && source[i + 1] === '\n') i += 1; // treat CRLF as one line break
      endRecord();
      // records holds the header plus data rows; one row beyond the limit proves
      // the file has more data, so we can stop reading.
      if (records.length > maxRows + 1) {
        truncated = true;
        break;
      }
    } else {
      field += char;
    }
  }

  // Whatever is left after the loop is the final line.
  const hasLeftover = field !== '' || record.length > 0;
  if (!truncated && hasLeftover) {
    if (isPartial) {
      truncated = true; // the last line was cut off mid-way: drop it
    } else {
      endRecord();
    }
  }

  const [header = [], ...rows] = records;
  if (rows.length > maxRows) {
    rows.length = maxRows;
    truncated = true;
  }
  return { header: header.map((name) => name.trim()), rows, truncated };
}

/** Turn an array of rows into CSV text, quoting fields only when needed. */
export function toCsv(header, rows) {
  const quote = (value) => {
    const text = value === null || value === undefined ? '' : String(value);
    return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  return [header, ...rows].map((row) => row.map(quote).join(',')).join('\n') + '\n';
}
