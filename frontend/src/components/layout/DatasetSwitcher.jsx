import { useNavigate } from 'react-router';
import { useDatasets } from '../../hooks/useDatasets';
import { DATASET_STATUS } from '../../utils/constants';

/** Jump between processed datasets. A controlled <select>: React owns its value. */
export function DatasetSwitcher() {
  const { datasets, currentDatasetId } = useDatasets();
  const navigate = useNavigate();
  const ready = datasets.filter((d) => d.status === DATASET_STATUS.READY);
  if (ready.length === 0) return null;

  return (
    <div className="flex min-w-0 items-center gap-2">
      <label htmlFor="dataset-switcher" className="hidden text-sm text-muted sm:block">
        Dataset
      </label>
      <select
        id="dataset-switcher"
        className="h-9 max-w-[16rem] min-w-0 truncate rounded-md border border-rule bg-surface px-2 text-sm text-ink"
        value={currentDatasetId ?? ''}
        onChange={(event) => navigate(`/datasets/${event.target.value}/quality`)}
      >
        <option value="" disabled>
          Choose a dataset
        </option>
        {ready.map((dataset) => (
          <option key={dataset.id} value={dataset.id}>
            {dataset.name}
            {dataset.is_synthetic ? ' (synthetic)' : ''}
          </option>
        ))}
      </select>
    </div>
  );
}
