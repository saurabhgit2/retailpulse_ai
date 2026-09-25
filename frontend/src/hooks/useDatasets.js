import { useContext } from 'react';
import { DatasetContext } from '../context/dataset-context';

/** The user's datasets and the dataset currently open in the URL. */
export function useDatasets() {
  const value = useContext(DatasetContext);
  if (!value) throw new Error('useDatasets must be used inside <DatasetProvider>.');
  return value;
}
