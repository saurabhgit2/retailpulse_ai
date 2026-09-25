/**
 * App-wide constants. Values that differ between environments come from
 * environment variables (import.meta.env), which Vite fills in at build time.
 */

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1';

// Environment variables are always strings, so compare with 'true'.
export const USE_MOCK_API = import.meta.env.VITE_USE_MOCK_API === 'true';

export const MAX_UPLOAD_MB = Number(import.meta.env.VITE_MAX_UPLOAD_MB || 200);

export const POLL_INTERVAL_MS = 2000;

// Locale used for number and date formatting throughout the UI.
export const DISPLAY_LOCALE = 'en-NZ';

// Dataset lifecycle (architecture §11.5). Matches the backend's status values.
export const DATASET_STATUS = Object.freeze({
  AWAITING_MAPPING: 'awaiting_mapping',
  PROCESSING: 'processing',
  READY: 'ready',
  FAILED: 'failed',
});

// Minimum password length, matching the backend rule (architecture §16).
export const MIN_PASSWORD_LENGTH = 12;
