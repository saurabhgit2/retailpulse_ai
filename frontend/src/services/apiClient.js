/**
 * The single place where the frontend talks HTTP.
 *
 * Every page calls functions in services/*.js, and those call `request()` here.
 * Keeping HTTP in one module means:
 *  - the auth header is added in one place;
 *  - every error, whatever its source, becomes one ApiError shape;
 *  - switching between the mock API and the real backend changes one line.
 */
import { API_BASE_URL, USE_MOCK_API } from '../utils/constants';

/** One error type for the whole UI. Components read .message and .code. */
export class ApiError extends Error {
  constructor({ status, code, message, details = null, requestId = null }) {
    super(message);
    this.name = 'ApiError';
    this.status = status; // HTTP status (0 = network failure)
    this.code = code; // machine-readable, e.g. MISSING_REQUIRED_FIELD
    this.details = details;
    this.requestId = requestId; // quote this when reporting a server error
  }
}

// --- Dependency injection points -------------------------------------------
// The API client must not import React state. Instead, the AuthProvider hands
// it two functions when the app starts (see context/AuthProvider.jsx).
let authHooks = { getToken: () => null, onUnauthorized: () => {} };

export function configureAuth(hooks) {
  authHooks = { ...authHooks, ...hooks };
}

// The transport is the function that actually sends the request: the browser's
// fetch, or the mock server's fetch-compatible function. Tests replace it with
// setTransport().
let transport = null;

export function setTransport(fn) {
  transport = fn;
}

async function getTransport() {
  if (transport) return transport;
  if (USE_MOCK_API) {
    // Dynamic import: the mock code is only downloaded when mock mode is on.
    const { mockFetch } = await import('./mock/mockServer');
    transport = mockFetch;
  } else {
    transport = (url, init) => fetch(url, init);
  }
  return transport;
}

// --- Helpers ----------------------------------------------------------------
function buildUrl(path, query) {
  const url = `${API_BASE_URL}${path}`;
  if (!query) return url;
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    // Arrays become repeated keys: ?region=UK&region=France
    (Array.isArray(value) ? value : [value]).forEach((v) => params.append(key, String(v)));
  });
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

const FALLBACK_MESSAGES = {
  400: 'The request could not be processed.',
  401: 'You need to sign in.',
  403: 'You do not have access to this.',
  404: 'We could not find that.',
  409: 'That action conflicts with the current state. Refresh and try again.',
  413: 'The file is too large.',
  415: 'That file type is not supported.',
  422: 'Some of the information provided is not valid.',
  429: 'Too many requests. Wait a moment and try again.',
  500: 'Something went wrong on the server.',
  502: 'An upstream service returned an invalid response.',
  503: 'The service is temporarily unavailable.',
  504: 'The server took too long to respond.',
};

/** Convert any non-2xx response into an ApiError. */
async function toApiError(response) {
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    // Body was empty or not JSON (e.g. an HTML error page from a proxy).
  }

  // 1) Our own error envelope: { error: { code, message, details, request_id } }
  if (payload?.error) {
    return new ApiError({
      status: response.status,
      code: payload.error.code ?? 'ERROR',
      message: payload.error.message ?? FALLBACK_MESSAGES[response.status] ?? 'Request failed.',
      details: payload.error.details ?? null,
      requestId: payload.error.request_id ?? null,
    });
  }

  // 2) FastAPI's built-in validation format: { detail: [{ loc, msg, type }] }
  if (Array.isArray(payload?.detail)) {
    const first = payload.detail[0];
    const field = first?.loc?.slice(1).join('.') || 'request';
    return new ApiError({
      status: response.status,
      code: 'VALIDATION_ERROR',
      message: `${field}: ${first?.msg ?? 'invalid value'}`,
      details: payload.detail,
    });
  }

  // 3) Anything else.
  return new ApiError({
    status: response.status,
    code: `HTTP_${response.status}`,
    message:
      (typeof payload?.detail === 'string' && payload.detail) ||
      FALLBACK_MESSAGES[response.status] ||
      'Request failed.',
  });
}

// --- The request function -----------------------------------------------------
/**
 * @param {string} path  e.g. '/datasets' (the /api/v1 prefix is added here)
 * @param {object} options
 * @param {string} [options.method]
 * @param {object} [options.query]     query-string parameters
 * @param {object} [options.json]      body sent as JSON
 * @param {object} [options.form]      body sent as application/x-www-form-urlencoded
 * @param {FormData} [options.formData] body sent as multipart/form-data (file uploads)
 * @param {AbortSignal} [options.signal] lets a component cancel the request
 * @param {'json'|'blob'|'text'} [options.responseType]
 */
export async function request(
  path,
  { method = 'GET', query, json, form, formData, signal, responseType = 'json' } = {},
) {
  const headers = { Accept: responseType === 'json' ? 'application/json' : '*/*' };
  const token = authHooks.getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  let body;
  if (json !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(json);
  } else if (form !== undefined) {
    headers['Content-Type'] = 'application/x-www-form-urlencoded';
    body = new URLSearchParams(form).toString();
  } else if (formData !== undefined) {
    // No Content-Type here on purpose: the browser adds the multipart boundary.
    body = formData;
  }

  const send = await getTransport();
  let response;
  try {
    response = await send(buildUrl(path, query), { method, headers, body, signal });
  } catch (error) {
    if (error?.name === 'AbortError') throw error; // the component cancelled; not a failure
    throw new ApiError({
      status: 0,
      code: 'NETWORK_ERROR',
      message: 'Cannot reach the RetailPulse server. Check your connection and that the backend is running.',
    });
  }

  if (!response.ok) {
    const apiError = await toApiError(response);
    // A 401 on a request that carried a token means the session has ended.
    // A 401 without a token (e.g. a wrong password at login) is just an error.
    if (response.status === 401 && token) authHooks.onUnauthorized();
    throw apiError;
  }

  if (response.status === 204) return null;
  if (responseType === 'blob') return response.blob();
  if (responseType === 'text') return response.text();
  return response.json();
}

// Small conveniences so service files read naturally.
export const api = {
  get: (path, options) => request(path, { ...options, method: 'GET' }),
  post: (path, json, options) => request(path, { ...options, method: 'POST', json }),
  postForm: (path, form, options) => request(path, { ...options, method: 'POST', form }),
  upload: (path, formData, options) => request(path, { ...options, method: 'POST', formData }),
  delete: (path, options) => request(path, { ...options, method: 'DELETE' }),
};
