import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { useDatasets } from '../hooks/useDatasets';
import { deleteDataset } from '../services/datasets';
import { DATASET_STATUS } from '../utils/constants';
import { formatBytes, formatDate, formatDateTime, formatNumber } from '../utils/format';
import { PageHeader } from '../components/layout/PageHeader';
import { buttonClasses } from '../components/ui/buttonStyles';
import { Alert } from '../components/ui/Alert';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { EmptyState } from '../components/ui/EmptyState';
import { ErrorState } from '../components/ui/ErrorState';
import { Spinner } from '../components/ui/Spinner';
import { StatusPill } from '../components/ui/StatusPill';

const REFRESH_WHILE_PROCESSING_MS = 3000;

export function DatasetsPage() {
  const { datasets, loading, error, reload } = useDatasets();
  const [deletingId, setDeletingId] = useState(null);
  const [actionError, setActionError] = useState(null);

  // While any dataset is still processing, refresh the list every few seconds.
  const anyProcessing = datasets.some((d) => d.status === DATASET_STATUS.PROCESSING);
  useEffect(() => {
    if (!anyProcessing) return undefined;
    const timer = setTimeout(reload, REFRESH_WHILE_PROCESSING_MS);
    return () => clearTimeout(timer);
  }, [anyProcessing, datasets, reload]);

  async function handleDelete(dataset) {
    // window.confirm is basic, but it is accessible and needs no extra code.
    if (!window.confirm(`Delete "${dataset.name}" and everything calculated from it? This cannot be undone.`)) return;
    setDeletingId(dataset.id);
    setActionError(null);
    try {
      await deleteDataset(dataset.id);
      reload();
    } catch (err) {
      setActionError(err);
    } finally {
      setDeletingId(null);
    }
  }

  const uploadLink = (
    <Link to="/upload" className={buttonClasses()}>
      Upload dataset
    </Link>
  );

  return (
    <>
      <PageHeader
        title="Datasets"
        description="Each upload is stored unchanged, cleaned by a documented pipeline, and analysed separately."
        actions={datasets.length > 0 ? uploadLink : null}
      />

      {actionError && (
        <Alert tone="error" title="Could not delete the dataset" className="mb-4">
          {actionError.message}
        </Alert>
      )}

      {loading && datasets.length === 0 ? (
        <Spinner label="Loading datasets" className="text-muted" />
      ) : error ? (
        <ErrorState error={error} title="Could not load your datasets" onRetry={reload} />
      ) : datasets.length === 0 ? (
        <EmptyState title="No datasets yet" action={uploadLink}>
          Upload a CSV of sales transactions. RetailPulse detects your columns, lets you confirm them, and
          reports every cleaning step it takes.
        </EmptyState>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-rule bg-surface">
          <table className="w-full min-w-[48rem] text-sm">
            <thead className="bg-surface-2 text-left text-xs tracking-wide text-muted uppercase">
              <tr>
                <th scope="col" className="px-4 py-2 font-medium">Dataset</th>
                <th scope="col" className="px-4 py-2 font-medium">Status</th>
                <th scope="col" className="px-4 py-2 text-right font-medium">Rows kept</th>
                <th scope="col" className="px-4 py-2 font-medium">Data covers</th>
                <th scope="col" className="px-4 py-2 font-medium">Uploaded</th>
                <th scope="col" className="px-4 py-2 font-medium">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {datasets.map((dataset) => (
                <DatasetRow
                  key={dataset.id}
                  dataset={dataset}
                  deleting={deletingId === dataset.id}
                  onDelete={() => handleDelete(dataset)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function DatasetRow({ dataset, deleting, onDelete }) {
  const isReady = dataset.status === DATASET_STATUS.READY;
  const canResume = dataset.status === DATASET_STATUS.AWAITING_MAPPING || dataset.status === DATASET_STATUS.FAILED;

  return (
    <tr className="border-t border-rule align-top">
      <td className="px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-ink">{dataset.name}</span>
          {dataset.is_synthetic && (
            <Badge tone="warn" title="Invented data: never report its results as findings">
              Synthetic
            </Badge>
          )}
        </div>
        <div className="mt-0.5 text-xs text-muted">
          {dataset.original_filename} · {formatBytes(dataset.file_size_bytes)}
        </div>
      </td>
      <td className="px-4 py-3">
        <StatusPill status={dataset.status} />
        {dataset.status === DATASET_STATUS.FAILED && dataset.status_message && (
          <p className="mt-1 max-w-xs text-xs text-crit">{dataset.status_message}</p>
        )}
      </td>
      <td className="tabular px-4 py-3 text-right text-ink-2">
        {isReady ? `${formatNumber(dataset.row_count_clean)} / ${formatNumber(dataset.row_count_raw)}` : '—'}
      </td>
      <td className="px-4 py-3 text-ink-2">
        {dataset.date_min
          ? `${formatDate(dataset.date_min, { utc: true })} – ${formatDate(dataset.date_max, { utc: true })}`
          : '—'}
      </td>
      <td className="px-4 py-3 text-ink-2">{formatDateTime(dataset.created_at)}</td>
      <td className="px-4 py-3">
        <div className="flex justify-end gap-2">
          {isReady && (
            <Link to={`/datasets/${dataset.id}/quality`} className={buttonClasses({ variant: 'secondary', size: 'sm' })}>
              Data quality
            </Link>
          )}
          {canResume && (
            <Link to={`/upload?dataset=${dataset.id}`} className={buttonClasses({ variant: 'secondary', size: 'sm' })}>
              {dataset.status === DATASET_STATUS.FAILED ? 'Fix mapping' : 'Continue'}
            </Link>
          )}
          <Button
            variant="danger"
            size="sm"
            loading={deleting}
            onClick={onDelete}
            aria-label={`Delete ${dataset.name}`}
          >
            Delete
          </Button>
        </div>
      </td>
    </tr>
  );
}
