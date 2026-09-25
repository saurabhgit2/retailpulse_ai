import { useCallback } from 'react';
import { Link, useParams } from 'react-router';
import { useApi } from '../hooks/useApi';
import { useDatasets } from '../hooks/useDatasets';
import { getQualityReport } from '../services/datasets';
import { METHOD_CARDS } from '../content/methodCards';
import { formatDateTime } from '../utils/format';
import { PageHeader } from '../components/layout/PageHeader';
import { Alert } from '../components/ui/Alert';
import { Badge } from '../components/ui/Badge';
import { ErrorState } from '../components/ui/ErrorState';
import { Spinner } from '../components/ui/Spinner';
import { StatusPill } from '../components/ui/StatusPill';
import { MethodCard } from '../components/explain/MethodCard';
import { QualityReport } from '../components/upload/QualityReport';

/** Step 5 of the user journey: "User receives data-quality summary". */
export function DataQualityPage() {
  const { datasetId } = useParams(); // from the route /datasets/:datasetId/quality
  const { currentDataset } = useDatasets();

  const load = useCallback((signal) => getQualityReport(datasetId, { signal }), [datasetId]);
  const { data: report, error, loading, reload } = useApi(load);

  return (
    <>
      <PageHeader
        eyebrow={
          currentDataset && (
            <>
              <span>{currentDataset.name}</span>
              <StatusPill status={currentDataset.status} />
              {currentDataset.is_synthetic && <Badge tone="warn">Synthetic</Badge>}
            </>
          )
        }
        title="Data-quality report"
        description={
          currentDataset?.processed_at
            ? `Processed ${formatDateTime(currentDataset.processed_at)}. Every change made to your file is listed below.`
            : 'Every change made to your file is listed below.'
        }
      />

      {currentDataset?.is_synthetic && (
        <Alert tone="warning" title="Synthetic dataset" className="mb-6">
          This data was invented for development. Don't present its results as real-world findings.
        </Alert>
      )}

      {loading ? (
        <Spinner label="Loading report" className="text-muted" />
      ) : error?.code === 'DATASET_NOT_READY' ? (
        <Alert tone="info" title="Not ready yet">
          {error.message} <Link to="/datasets" className="font-medium underline">Back to datasets</Link>
        </Alert>
      ) : error ? (
        <ErrorState error={error} title="Could not load the report" onRetry={reload} />
      ) : (
        <div className="flex flex-col gap-6">
          <QualityReport report={report} />
          <MethodCard card={METHOD_CARDS.qualityReport} />
        </div>
      )}
    </>
  );
}
