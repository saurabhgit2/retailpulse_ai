/**
 * MOCK ONLY. The mock API's "database".
 *
 * Users and dataset metadata are saved to localStorage so a page reload keeps
 * them. File previews are held only in memory (they can be megabytes), so after
 * a reload a dataset that was never processed has to be uploaded again. The
 * mock reports that honestly instead of pretending.
 */

const STORAGE_KEY = 'retailpulse.mock.v1';

function emptyState() {
  return { users: [], datasets: [] };
}

function load() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? { ...emptyState(), ...JSON.parse(raw) } : emptyState();
  } catch {
    return emptyState(); // storage blocked (private mode) or corrupted: start fresh
  }
}

const state = load();

function persist() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Storage full or blocked: the mock keeps working in memory.
  }
}

// Anything that was "processing" when the page was closed can't finish now,
// because its in-memory timer and preview are gone.
state.datasets.forEach((dataset) => {
  if (dataset.status === 'processing' || dataset.status === 'awaiting_mapping') {
    dataset.status = 'failed';
    dataset.status_message =
      'Mock mode: the page was reloaded before processing finished, so the file preview was lost. Upload the file again.';
  }
});
persist();

/** In-memory only: parsed preview rows per dataset id. */
export const previews = new Map();

export const db = {
  get users() {
    return state.users;
  },
  get datasets() {
    return state.datasets;
  },
  save: persist,
  reset() {
    state.users.length = 0;
    state.datasets.length = 0;
    previews.clear();
    this.save();
  },
};
