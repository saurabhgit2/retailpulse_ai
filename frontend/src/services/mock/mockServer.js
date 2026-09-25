/**
 * MOCK ONLY. A fetch-compatible fake of the FastAPI backend.
 *
 * `mockFetch(url, init)` has the same signature as the browser's fetch() and
 * returns a real `Response` object. The API client therefore can't tell the
 * difference: status codes, JSON bodies and the error envelope all go through
 * the same code path as the real backend. Set VITE_USE_MOCK_API=false once the
 * backend is running and nothing else in the app changes.
 *
 * It implements only the endpoints the Phase 2–3 screens need, following the
 * contract in architecture §9.
 */
import { API_BASE_URL } from '../../utils/constants';
import { parseCsv } from '../../utils/csv';
import { computeCapabilities, findDuplicateSources } from '../../utils/capabilities';
import { FIELD_GUIDE, DEFAULT_PROCESSING_OPTIONS, TEMPLATE_CSV } from './fixtures';
import { buildUploadProfile } from './schemaDetection';
import { runMockPipeline, MOCK_PIPELINE_VERSION } from './mockProcessing';
import { db, previews } from './mockDb';

const SERVER_MAX_UPLOAD_MB = 200;
const PREVIEW_BYTES = 1024 * 1024; // read the first 1 MB of the file in the browser
const PREVIEW_MAX_ROWS = 5000;
const TOKEN_LIFETIME_MS = 60 * 60 * 1000; // 60 minutes, like the real JWT

// --- Response helpers --------------------------------------------------------
class MockHttpError extends Error {
  constructor(status, code, message, details = null) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

const requestId = () => `mock-${Math.random().toString(16).slice(2, 10)}`;

function jsonResponse(status, data) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function errorResponse(status, code, message, details = null) {
  return jsonResponse(status, { error: { code, message, details, request_id: requestId() } });
}

function delay(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new DOMException('Aborted', 'AbortError'));
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener('abort', () => {
      clearTimeout(timer);
      reject(new DOMException('Aborted', 'AbortError'));
    });
  });
}

// --- Auth helpers --------------------------------------------------------------
// Even in a mock, passwords are never stored in plain text.
async function hashPassword(password) {
  const bytes = new TextEncoder().encode(`retailpulse-mock:${password}`);
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

// A fake token that carries the user id and an expiry time. Unlike a real JWT
// it is not signed, which is fine for a mock and nothing else.
function issueToken(userId) {
  return `mock.${btoa(JSON.stringify({ sub: userId, exp: Date.now() + TOKEN_LIFETIME_MS }))}`;
}

function requireUser(headers) {
  const auth = headers?.Authorization ?? headers?.authorization ?? '';
  const token = auth.startsWith('Bearer ') ? auth.slice(7) : null;
  if (!token) throw new MockHttpError(401, 'NOT_AUTHENTICATED', 'Sign in to continue.');
  try {
    const payload = JSON.parse(atob(token.replace(/^mock\./, '')));
    const user = db.users.find((u) => u.id === payload.sub);
    if (!user || payload.exp < Date.now()) throw new Error('expired');
    return user;
  } catch {
    throw new MockHttpError(401, 'TOKEN_INVALID', 'Your session has expired. Sign in again.');
  }
}

const publicUser = ({ id, email, full_name }) => ({ id, email, full_name });

// --- Dataset helpers -----------------------------------------------------------
function findOwnedDataset(user, datasetId) {
  const dataset = db.datasets.find((d) => d.id === datasetId && d.owner_id === user.id);
  // Someone else's dataset looks exactly like a missing one (architecture §9.1).
  if (!dataset) throw new MockHttpError(404, 'DATASET_NOT_FOUND', 'That dataset does not exist.');
  return dataset;
}

function datasetView(dataset) {
  const { owner_id: _owner, quality_report: _report, ...visible } = dataset;
  // The column profile is only needed while the user is (re)mapping columns.
  if (!['awaiting_mapping', 'failed'].includes(dataset.status)) delete visible.profile;
  return visible;
}

function validateMapping(dataset, mapping) {
  const columns = dataset.profile.detected_columns.map((c) => c.name);
  const unknown = Object.values(mapping).filter((c) => c && !columns.includes(c));
  if (unknown.length) {
    throw new MockHttpError(422, 'UNKNOWN_COLUMN', `These columns are not in the file: ${unknown.join(', ')}.`);
  }
  const duplicates = findDuplicateSources(mapping);
  if (duplicates.length) {
    throw new MockHttpError(
      422,
      'DUPLICATE_MAPPING',
      `Each source column can be mapped to one field only. Used more than once: ${duplicates.join(', ')}.`,
      { columns: duplicates },
    );
  }
  const missingRequired = FIELD_GUIDE.fields
    .filter((f) => f.status === 'required' && !mapping[f.key])
    .map((f) => f.key);
  const blocked = computeCapabilities(mapping, FIELD_GUIDE.capabilities.filter((c) => c.required))
    .filter((c) => !c.enabled)
    .flatMap((c) => c.missing);
  if (missingRequired.length || blocked.length) {
    throw new MockHttpError(
      422,
      'MISSING_REQUIRED_FIELD',
      `Map these before processing: ${[...new Set([...missingRequired, ...blocked])].join('; ')}.`,
      { missing: [...new Set([...missingRequired, ...blocked])] },
    );
  }
}

function resolveDateFormat(dataset, mapping, options) {
  const column = dataset.profile.detected_columns.find((c) => c.name === mapping.occurred_at);
  const candidates = column?.date_format_candidates ?? [];
  if (options.date_format) {
    if (!candidates.includes(options.date_format)) {
      throw new MockHttpError(
        422,
        'DATE_PARSE_FAILURE',
        `Fewer than 95% of the values in "${column?.name}" can be read with the chosen date format.`,
      );
    }
    return options.date_format;
  }
  if (candidates.length === 1) return candidates[0];
  if (candidates.length === 0) {
    throw new MockHttpError(422, 'DATE_PARSE_FAILURE', `"${column?.name}" does not contain readable dates.`);
  }
  throw new MockHttpError(
    422,
    'DATE_FORMAT_REQUIRED',
    'The dates could be read in more than one way. Choose the date format before processing.',
    { candidates },
  );
}

function scheduleProcessing(dataset, mapping, options) {
  const preview = previews.get(dataset.id);
  const duration = 2500 + Math.random() * 1500; // pretend the backend is working
  setTimeout(() => {
    try {
      const { report, rowsClean, dateMin, dateMax } = runMockPipeline({
        header: preview.header,
        rows: preview.rows,
        mapping,
        options,
        fileTruncated: preview.truncated,
      });
      if (rowsClean === 0) {
        Object.assign(dataset, {
          status: 'failed',
          status_message: 'No valid rows remained after cleaning. Check the column mapping and date format.',
        });
      } else {
        Object.assign(dataset, {
          status: 'ready',
          status_message: null,
          quality_report: report,
          capabilities: report.capabilities,
          row_count_raw: report.summary.rows_raw,
          row_count_clean: rowsClean,
          date_min: dateMin,
          date_max: dateMax,
          processed_at: new Date().toISOString(),
        });
      }
    } catch (error) {
      console.error('[mock] processing failed', error);
      Object.assign(dataset, { status: 'failed', status_message: 'Processing failed unexpectedly.' });
    }
    db.save();
  }, duration);
}

// --- Route handlers -----------------------------------------------------------
const routes = [
  {
    method: 'POST',
    pattern: /^\/auth\/register$/,
    handler: async ({ body }) => {
      const { full_name: fullName = '', email = '', password = '' } = JSON.parse(body || '{}');
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
        throw new MockHttpError(422, 'VALIDATION_ERROR', 'Enter a valid email address.');
      }
      if (password.length < 12) {
        throw new MockHttpError(422, 'VALIDATION_ERROR', 'Password must be at least 12 characters.');
      }
      const normalisedEmail = email.trim().toLowerCase();
      if (db.users.some((u) => u.email === normalisedEmail)) {
        throw new MockHttpError(409, 'EMAIL_ALREADY_REGISTERED', 'An account with this email already exists. Sign in instead.');
      }
      const user = {
        id: crypto.randomUUID(),
        email: normalisedEmail,
        full_name: fullName.trim(),
        password_hash: await hashPassword(password),
      };
      db.users.push(user);
      db.save();
      return jsonResponse(201, publicUser(user));
    },
  },
  {
    method: 'POST',
    pattern: /^\/auth\/login$/,
    handler: async ({ body }) => {
      const form = new URLSearchParams(body || '');
      const email = (form.get('username') ?? '').trim().toLowerCase();
      const user = db.users.find((u) => u.email === email);
      const hash = await hashPassword(form.get('password') ?? '');
      // Same message for "no such user" and "wrong password" (architecture §16).
      if (!user || user.password_hash !== hash) {
        throw new MockHttpError(401, 'INVALID_CREDENTIALS', 'Email or password is incorrect.');
      }
      return jsonResponse(200, { access_token: issueToken(user.id), token_type: 'bearer' });
    },
  },
  {
    method: 'GET',
    pattern: /^\/auth\/me$/,
    handler: ({ headers }) => jsonResponse(200, publicUser(requireUser(headers))),
  },
  {
    method: 'GET',
    pattern: /^\/datasets\/template$/,
    handler: () => new Response(TEMPLATE_CSV, { status: 200, headers: { 'Content-Type': 'text/csv' } }),
  },
  {
    method: 'GET',
    pattern: /^\/datasets\/field-guide$/,
    handler: ({ headers }) => {
      requireUser(headers);
      return jsonResponse(200, FIELD_GUIDE);
    },
  },
  {
    method: 'GET',
    pattern: /^\/datasets$/,
    handler: ({ headers }) => {
      const user = requireUser(headers);
      const items = db.datasets
        .filter((d) => d.owner_id === user.id)
        .sort((a, b) => b.created_at.localeCompare(a.created_at))
        .map(datasetView);
      return jsonResponse(200, { items, total: items.length });
    },
  },
  {
    method: 'POST',
    pattern: /^\/datasets$/,
    handler: async ({ headers, body }) => {
      const user = requireUser(headers);
      const file = body instanceof FormData ? body.get('file') : null;
      if (!(file instanceof File)) {
        throw new MockHttpError(422, 'FILE_REQUIRED', 'Attach a CSV file in the "file" field.');
      }
      if (!file.name.toLowerCase().endsWith('.csv')) {
        throw new MockHttpError(415, 'UNSUPPORTED_FILE', 'Only CSV files are accepted.');
      }
      if (file.size > SERVER_MAX_UPLOAD_MB * 1024 * 1024) {
        throw new MockHttpError(413, 'FILE_TOO_LARGE', `Files must be ${SERVER_MAX_UPLOAD_MB} MB or smaller.`);
      }

      const isPartial = file.size > PREVIEW_BYTES;
      const text = await file.slice(0, PREVIEW_BYTES).text();
      const { header, rows, truncated } = parseCsv(text, { maxRows: PREVIEW_MAX_ROWS, isPartial });
      if (header.length === 0 || rows.length === 0) {
        throw new MockHttpError(422, 'EMPTY_FILE', 'The file needs a header row and at least one data row.');
      }
      if (header.length > 200) {
        throw new MockHttpError(422, 'MALFORMED_CSV', 'The file has more than 200 columns. Check the delimiter is a comma.');
      }

      const now = new Date().toISOString();
      const dataset = {
        id: crypto.randomUUID(),
        owner_id: user.id,
        name: file.name.replace(/\.csv$/i, ''),
        is_synthetic: body.get('is_synthetic') === 'true',
        status: 'awaiting_mapping',
        status_message: null,
        original_filename: file.name,
        file_size_bytes: file.size,
        file_sha256: null, // the real backend hashes the stored file
        row_count_raw: null,
        row_count_clean: null,
        date_min: null,
        date_max: null,
        capabilities: null,
        column_mapping: null,
        pipeline_version: MOCK_PIPELINE_VERSION,
        created_at: now,
        processed_at: null,
        profile: buildUploadProfile(header, rows, { truncated }),
      };
      previews.set(dataset.id, { header, rows, truncated });
      db.datasets.push(dataset);
      db.save();
      return jsonResponse(201, datasetView(dataset));
    },
  },
  {
    method: 'GET',
    pattern: /^\/datasets\/([^/]+)$/,
    handler: ({ headers, params }) => {
      const user = requireUser(headers);
      return jsonResponse(200, datasetView(findOwnedDataset(user, params[0])));
    },
  },
  {
    method: 'POST',
    pattern: /^\/datasets\/([^/]+)\/process$/,
    handler: ({ headers, params, body }) => {
      const user = requireUser(headers);
      const dataset = findOwnedDataset(user, params[0]);
      // A failed dataset can be retried with a corrected mapping (architecture §11.5).
      if (!['awaiting_mapping', 'failed'].includes(dataset.status)) {
        throw new MockHttpError(409, 'INVALID_STATUS', `This dataset is ${dataset.status.replace('_', ' ')} and cannot be processed now.`);
      }
      if (!previews.has(dataset.id)) {
        throw new MockHttpError(409, 'PREVIEW_LOST', 'Mock mode lost this file after a page reload. Upload it again.');
      }
      const { mapping = {}, options = {} } = JSON.parse(body || '{}');
      validateMapping(dataset, mapping);
      const dateFormat = resolveDateFormat(dataset, mapping, options);
      const effectiveOptions = { ...DEFAULT_PROCESSING_OPTIONS, ...options, date_format: dateFormat };

      Object.assign(dataset, {
        status: 'processing',
        column_mapping: mapping,
        cleaning_options: effectiveOptions,
      });
      db.save();
      scheduleProcessing(dataset, mapping, effectiveOptions);
      return jsonResponse(202, { id: dataset.id, status: dataset.status });
    },
  },
  {
    method: 'GET',
    pattern: /^\/datasets\/([^/]+)\/quality-report$/,
    handler: ({ headers, params }) => {
      const user = requireUser(headers);
      const dataset = findOwnedDataset(user, params[0]);
      if (dataset.status !== 'ready') {
        throw new MockHttpError(409, 'DATASET_NOT_READY', "This dataset isn't ready yet. Its report appears once processing finishes.", {
          status: dataset.status,
        });
      }
      return jsonResponse(200, dataset.quality_report);
    },
  },
  {
    method: 'DELETE',
    pattern: /^\/datasets\/([^/]+)$/,
    handler: ({ headers, params }) => {
      const user = requireUser(headers);
      const dataset = findOwnedDataset(user, params[0]);
      db.datasets.splice(db.datasets.indexOf(dataset), 1);
      previews.delete(dataset.id);
      db.save();
      return new Response(null, { status: 204 });
    },
  },
];

// --- The fetch replacement ----------------------------------------------------
export async function mockFetch(url, init = {}) {
  const { method = 'GET', headers = {}, body, signal } = init;
  await delay(150 + Math.random() * 250, signal); // simulate network latency

  const { pathname } = new URL(url, window.location.origin);
  const path = pathname.startsWith(API_BASE_URL) ? pathname.slice(API_BASE_URL.length) : pathname;

  for (const route of routes) {
    if (route.method !== method) continue;
    const match = route.pattern.exec(path);
    if (!match) continue;
    try {
      return await route.handler({ headers, body, params: match.slice(1).map(decodeURIComponent) });
    } catch (error) {
      if (error instanceof MockHttpError) {
        return errorResponse(error.status, error.code, error.message, error.details);
      }
      console.error('[mock] unexpected error', error);
      return errorResponse(500, 'INTERNAL_ERROR', 'Something went wrong on the server.');
    }
  }
  return errorResponse(404, 'NOT_FOUND', `No mock endpoint for ${method} ${path}.`);
}
