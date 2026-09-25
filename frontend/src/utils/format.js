/**
 * Formatting helpers. Keeping them in one place means every screen shows
 * numbers, sizes and dates the same way, and they are easy to unit-test.
 */
import { DISPLAY_LOCALE } from './constants';

const EMPTY = '—';

export function formatNumber(value, { maximumFractionDigits = 0 } = {}) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return EMPTY;
  return new Intl.NumberFormat(DISPLAY_LOCALE, { maximumFractionDigits }).format(Number(value));
}

/** ratio 0.1234 -> "12.3%" */
export function formatPercent(ratio, { digits = 1 } = {}) {
  if (ratio === null || ratio === undefined || Number.isNaN(Number(ratio))) return EMPTY;
  return new Intl.NumberFormat(DISPLAY_LOCALE, {
    style: 'percent',
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(Number(ratio));
}

/** 1536 -> "1.5 KB" (binary units, 1 KB = 1024 bytes) */
export function formatBytes(bytes) {
  if (bytes === null || bytes === undefined || Number.isNaN(Number(bytes))) return EMPTY;
  const units = ['bytes', 'KB', 'MB', 'GB'];
  let value = Number(bytes);
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  const digits = unitIndex === 0 ? 0 : 1;
  return `${value.toFixed(digits)} ${units[unitIndex]}`;
}

/*
 * Dates: events in *your* timeline (uploaded at, processed at) are shown in the
 * viewer's time zone. Transaction dates from a dataset are wall-clock times
 * from the retailer's system, stored without a zone, so pass { utc: true } to
 * show them exactly as recorded instead of shifting them by the viewer's offset.
 */
export function formatDateTime(isoString, { utc = false } = {}) {
  if (!isoString) return EMPTY;
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return EMPTY;
  return new Intl.DateTimeFormat(DISPLAY_LOCALE, {
    dateStyle: 'medium',
    timeStyle: 'short',
    ...(utc ? { timeZone: 'UTC' } : {}),
  }).format(date);
}

export function formatDate(isoString, { utc = false } = {}) {
  if (!isoString) return EMPTY;
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return EMPTY;
  return new Intl.DateTimeFormat(DISPLAY_LOCALE, {
    dateStyle: 'medium',
    ...(utc ? { timeZone: 'UTC' } : {}),
  }).format(date);
}
