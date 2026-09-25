import { useCallback, useMemo } from 'react';
import { useMatch } from 'react-router';
import { DatasetContext } from './dataset-context';
import { useApi } from '../hooks/useApi';
import { listDatasets } from '../services/datasets';

/*
 * Shares the signed-in user's datasets with the whole app shell (sidebar, top
 * bar, pages), so they are loaded once instead of by every component.
 *
 * The *current* dataset comes from the URL (/datasets/:datasetId/...), not
 * from state. The URL is the single source of truth: reloads, the back button
 * and shared links all work without extra code.
 */
export function DatasetProvider({ children }) {
  const load = useCallback((signal) => listDatasets({ signal }), []);
  const { data, error, loading, reload } = useApi(load);

  const match = useMatch('/datasets/:datasetId/*');
  const currentDatasetId = match?.params.datasetId ?? null;

  const value = useMemo(() => {
    const datasets = data?.items ?? [];
    return {
      datasets,
      loading,
      error,
      reload,
      currentDatasetId,
      currentDataset: datasets.find((d) => d.id === currentDatasetId) ?? null,
    };
  }, [data, loading, error, reload, currentDatasetId]);

  return <DatasetContext.Provider value={value}>{children}</DatasetContext.Provider>;
}
