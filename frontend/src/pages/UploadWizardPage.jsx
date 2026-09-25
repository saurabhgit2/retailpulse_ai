import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { useApi } from '../hooks/useApi';
import { useDatasets } from '../hooks/useDatasets';
import { getDataset, getFieldGuide } from '../services/datasets';
import { PageHeader } from '../components/layout/PageHeader';
import { Alert } from '../components/ui/Alert';
import { ErrorState } from '../components/ui/ErrorState';
import { Spinner } from '../components/ui/Spinner';
import { UploadSteps } from '../components/upload/UploadSteps';
import { ChooseFileStep } from '../components/upload/ChooseFileStep';
import { MapColumnsStep } from '../components/upload/MapColumnsStep';
import { ProcessingStep } from '../components/upload/ProcessingStep';

/**
 * The upload wizard: choose file → map columns → process.
 *
 * This page only decides WHICH step to show and passes data between steps.
 * Each step is its own component with its own state, so no single file has to
 * understand the whole flow. `?dataset=<id>` in the URL reopens the mapping
 * step for a dataset that still needs it (from the Datasets list).
 */
export function UploadWizardPage() {
  const [searchParams] = useSearchParams();
  const resumeId = searchParams.get('dataset');
  const navigate = useNavigate();
  const { reload: reloadDatasets } = useDatasets();

  const [step, setStep] = useState('choose'); // 'choose' | 'map' | 'process'
  const [dataset, setDataset] = useState(null);

  const loadGuide = useCallback((signal) => getFieldGuide({ signal }), []);
  const guide = useApi(loadGuide);

  const loadResume = useCallback((signal) => getDataset(resumeId, { signal }), [resumeId]);
  const resume = useApi(loadResume, { enabled: Boolean(resumeId) });

  // When resuming, jump straight to the mapping step once the dataset arrives.
  useEffect(() => {
    if (resume.data?.profile) {
      setDataset(resume.data);
      setStep('map');
    }
  }, [resume.data]);

  const handleUploaded = useCallback(
    (uploaded) => {
      setDataset(uploaded);
      setStep('map');
      reloadDatasets();
    },
    [reloadDatasets],
  );

  const handleStarted = useCallback(() => {
    setStep('process');
    reloadDatasets();
  }, [reloadDatasets]);

  const handleReady = useCallback(
    (ready) => {
      reloadDatasets();
      navigate(`/datasets/${ready.id}/quality`, { replace: true });
    },
    [navigate, reloadDatasets],
  );

  const handleBackToMapping = useCallback((failed) => {
    setDataset(failed);
    setStep('map');
  }, []);

  const handleChooseAnotherFile = useCallback(() => {
    setDataset(null);
    setStep('choose');
    if (resumeId) navigate('/upload', { replace: true });
  }, [navigate, resumeId]);

  let content;
  if (guide.loading || (resumeId && resume.loading)) {
    content = <Spinner label="Loading" className="text-muted" />;
  } else if (guide.error) {
    content = <ErrorState error={guide.error} title="Could not load the field guide" onRetry={guide.reload} />;
  } else if (resumeId && resume.error) {
    content = <ErrorState error={resume.error} title="Could not reopen this dataset" onRetry={resume.reload} />;
  } else if (resumeId && resume.data && !resume.data.profile && !dataset) {
    content = (
      <Alert tone="warning" title="This dataset can't be remapped">
        Its column profile is no longer available. <Link to="/upload" className="font-medium underline">Upload the file again</Link>.
      </Alert>
    );
  } else if (step === 'map' && dataset) {
    content = (
      <MapColumnsStep
        key={dataset.id}
        dataset={dataset}
        fieldGuide={guide.data}
        onStarted={handleStarted}
        onChooseAnotherFile={handleChooseAnotherFile}
      />
    );
  } else if (step === 'process' && dataset) {
    content = <ProcessingStep datasetId={dataset.id} onReady={handleReady} onBackToMapping={handleBackToMapping} />;
  } else {
    content = <ChooseFileStep fieldGuide={guide.data} onUploaded={handleUploaded} />;
  }

  return (
    <>
      <PageHeader
        title="Upload data"
        description="Your file is stored unchanged. You confirm how its columns are read before anything is cleaned."
      />
      <div className="mb-6">
        <UploadSteps current={step} />
      </div>
      {content}
    </>
  );
}
