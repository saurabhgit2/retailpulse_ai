/**
 * Date-format detection and parsing for the three layouts we expect in retail
 * exports. Dates are the column most often mis-read, because 03/04/2010 is
 * 3 April in the UK and 4 March in the US. We never guess silently: if both
 * readings are possible, the user has to choose (architecture §12.1).
 */

export const DATE_FORMATS = Object.freeze({
  iso: { key: 'iso', label: 'Year-month-day (2010-04-03 14:30)', example: '2010-04-03 14:30:00' },
  dmy: { key: 'dmy', label: 'Day/month/year (03/04/2010 14:30)', example: '03/04/2010 14:30' },
  mdy: { key: 'mdy', label: 'Month/day/year (04/03/2010 14:30)', example: '04/03/2010 14:30' },
});

const ISO_PATTERN = /^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?$/;
const SLASH_PATTERN = /^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})(?: (\d{1,2}):(\d{2})(?::(\d{2}))?)?$/;

function buildDate(year, month, day, hour = 0, minute = 0, second = 0) {
  const [y, mo, d, h, mi, s] = [year, month, day, hour, minute, second].map(Number);
  if (mo < 1 || mo > 12 || d < 1 || d > 31 || h > 23 || mi > 59 || s > 59) return null;
  const date = new Date(Date.UTC(y, mo - 1, d, h, mi, s));
  // Reject impossible dates like 31/02 (JavaScript would roll them into March).
  if (date.getUTCMonth() !== mo - 1 || date.getUTCDate() !== d) return null;
  return date;
}

/** Parse one value with a known format. Returns a Date (UTC) or null. */
export function parseDate(value, format) {
  const text = String(value ?? '').trim();
  if (!text) return null;
  if (format === 'iso') {
    const m = ISO_PATTERN.exec(text);
    return m ? buildDate(m[1], m[2], m[3], m[4], m[5], m[6]) : null;
  }
  const m = SLASH_PATTERN.exec(text);
  if (!m) return null;
  return format === 'dmy'
    ? buildDate(m[3], m[2], m[1], m[4], m[5], m[6])
    : buildDate(m[3], m[1], m[2], m[4], m[5], m[6]);
}

/**
 * Which formats parse at least `threshold` of the non-empty sample values?
 * @returns {{ candidates: string[], ambiguous: boolean }}
 */
export function detectDateFormats(values, threshold = 0.95) {
  const sample = values.map((v) => String(v ?? '').trim()).filter(Boolean);
  if (sample.length === 0) return { candidates: [], ambiguous: false };
  const candidates = Object.keys(DATE_FORMATS).filter((format) => {
    const parsed = sample.filter((v) => parseDate(v, format) !== null).length;
    return parsed / sample.length >= threshold;
  });
  const ambiguous = candidates.includes('dmy') && candidates.includes('mdy');
  return { candidates, ambiguous };
}
