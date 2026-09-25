/**
 * Dataset endpoints (architecture §9.2, "Datasets and data quality").
 * Each function maps to exactly one endpoint, so this file doubles as a
 * readable index of what the backend offers.
 */
import { api } from './apiClient';

export function listDatasets({ signal } = {}) {
  return api.get('/datasets', { signal });
}

export function getDataset(datasetId, { signal } = {}) {
  return api.get(`/datasets/${encodeURIComponent(datasetId)}`, { signal });
}

/** Canonical fields, their synonyms, and the capability rules. */
export function getFieldGuide({ signal } = {}) {
  return api.get('/datasets/field-guide', { signal });
}

/** The recommended-format CSV template, as a Blob the browser can save. */
export function downloadTemplate() {
  return api.get('/datasets/template', { responseType: 'blob' });
}

/**
 * Step 1 of the upload: send the file. The server stores it, profiles the
 * columns and suggests a mapping. Returns 201 with status "awaiting_mapping".
 */
export function uploadDataset(file, { isSynthetic = false, signal } = {}) {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('is_synthetic', String(isSynthetic));
  return api.upload('/datasets', formData, { signal });
}

/**
 * Step 2: confirm the mapping and start background processing (202 Accepted).
 * The caller then polls getDataset() until status is "ready" or "failed".
 */
export function processDataset(datasetId, { mapping, options }) {
  return api.post(`/datasets/${encodeURIComponent(datasetId)}/process`, { mapping, options });
}

export function getQualityReport(datasetId, { signal } = {}) {
  return api.get(`/datasets/${encodeURIComponent(datasetId)}/quality-report`, { signal });
}

export function deleteDataset(datasetId) {
  return api.delete(`/datasets/${encodeURIComponent(datasetId)}`);
}
