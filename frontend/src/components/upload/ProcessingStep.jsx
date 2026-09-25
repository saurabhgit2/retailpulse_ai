import { useCallback, useEffect } from 'react';
import { getDataset } from '../../services/datasets';
import { usePolling } from '../../hooks/usePolling';
import { DATASET_STATUS } from '../../utils/constants';
import { Alert } from '../ui/Alert';
import { Button } from '../ui/Button';
import { Card } from '../ui/Card';
import { ErrorState } from '../ui/ErrorState';
import { Spinner } from '../ui/Spinner';

const isFinished = (dataset) =>
  dataset?.status === DATASET_STATUS.READY || dataset?.status === DATASET_STATUS.FAILED;

/**
 * Step 3: the server is processing in the background (it answered 202
 * Accepted), so we poll GET /datasets/{id} until the status is final.
 */
export function ProcessingStep({ datasetId, onReady, onBackToMapping }) {
  const fetcher = useCallback((signal) => getDataset(datasetId, { signal }), [datasetId]);
  const { data: dataset, error, retry } = usePolling(fetcher, { isDone: isFinished });

  useEffect(() => {
    if (dataset?.status === DATASET_STATUS.READY) onReady(dataset);
  }, [dataset, onReady]);

  if (error) return <ErrorState error={error} title="Lost contact while processing" onRetry={retry} />;

  if (dataset?.status === DATASET_STATUS.FAILED) {
    return (
      <div className="flex flex-col gap-4">
        <Alert tone="error" title="Processing failed">
          {dataset.status_message ?? 'The dataset could not be processed.'}
        </Alert>
        <div>
          <Button variant="secondary" onClick={() => onBackToMapping(dataset)} disabled={!dataset.profile}>
            Back to column mapping
          </Button>
        </div>
      </div>
    );
  }

  return (
    <Card>
      <div className="flex flex-col items-center gap-3 py-8 text-center">
        <Spinner label="Processing" className="text-accent" />
        <h2 className="text-base font-semibold text-ink">Cleaning and storing your data</h2>
        <p className="max-w-md text-sm text-muted">
          Validating rows, removing duplicates, flagging returns and building the data-quality report. This page
          updates automatically when it's done.
        </p>
      </div>
    </Card>
  );
}
