import { api } from './apiClient.js';

/**
 * The Phase 5 forecasting endpoints.
 *
 * The shape here mirrors dataset processing: starting a run answers 202 with
 * a `poll` URL, and the client polls the run until `status` is 'ready' or
 * 'failed'. `usePolling` already does exactly that for uploads, so the
 * forecasting page reuses it rather than inventing a second mechanism.
 *
 * `startRun` sends no body by default, deliberately. The server's defaults
 * are the protocol the report describes, so the common case needs no
 * parameters and a page that quietly passed its own would make the
 * dashboard's figures diverge from the dissertation's.
 */

const base = (datasetId) => `/datasets/${encodeURIComponent(datasetId)}`;

/**
 * Which models this server can run, and which cannot run here and why.
 * Not dataset-scoped. Worth calling before offering a model list: an
 * optional library that is not installed should cost a second, not an hour.
 */
export function getModels({ signal } = {}) {
  return api.get('/forecast/models', { signal });
}

/** 202 Accepted with { id, status, poll }. The run is queued, not finished. */
export function startRun(datasetId, { body = null, signal } = {}) {
  return api.post(`${base(datasetId)}/forecast/runs`, body, { signal });
}

/** Recent runs, newest first. `limit` is 1 to 100. */
export function listRuns(datasetId, { query, signal } = {}) {
  return api.get(`${base(datasetId)}/forecast/runs`, { query, signal });
}

/**
 * One run: protocol, results, significance and environment.
 * Also the polling endpoint; `status` is queued, running, ready or failed.
 */
export function getRun(datasetId, runId, { signal } = {}) {
  return api.get(
    `${base(datasetId)}/forecast/runs/${encodeURIComponent(runId)}`,
    { signal },
  );
}

/**
 * The most recent finished run, which is what the dashboard shows.
 * `series_key` selects a series; omitting it takes the default, which for
 * this project is total weekly revenue.
 */
export function getLatest(datasetId, { query, signal } = {}) {
  return api.get(`${base(datasetId)}/forecast/latest`, { query, signal });
}

/** A run is finished, either way, when it stops being queued or running. */
export function isFinished(run) {
  return run?.status === 'ready' || run?.status === 'failed';
}
