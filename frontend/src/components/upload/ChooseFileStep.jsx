import { useState } from 'react';
import { uploadDataset } from '../../services/datasets';
import { USE_MOCK_API } from '../../utils/constants';
import { Alert } from '../ui/Alert';
import { Button } from '../ui/Button';
import { Card } from '../ui/Card';
import { FileDropzone } from './FileDropzone';
import { FieldGuidePanel } from './FieldGuidePanel';

/** Step 1: pick a file and send it to POST /datasets. */
export function ChooseFileStep({ fieldGuide, onUploaded }) {
  const [file, setFile] = useState(null);
  const [isSynthetic, setIsSynthetic] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState(null);

  async function handleUpload() {
    setUploading(true);
    setError(null);
    try {
      const dataset = await uploadDataset(file, { isSynthetic });
      onUploaded(dataset);
    } catch (err) {
      setError(err);
      setUploading(false);
    }
  }

  async function loadSyntheticSample() {
    // Loaded on demand so the generator never ships in the real-backend build.
    const { generateSyntheticSample } = await import('../../services/mock/syntheticSample');
    setFile(generateSyntheticSample());
    setIsSynthetic(true);
    setError(null);
  }

  return (
    <div className="flex flex-col gap-6">
      <Card title="Choose a CSV file">
        <div className="flex flex-col gap-4">
          <FileDropzone file={file} onFileSelected={setFile} disabled={uploading} />

          <label className="flex items-start gap-2 text-sm text-ink-2">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={isSynthetic}
              onChange={(event) => setIsSynthetic(event.target.checked)}
            />
            <span>
              This dataset is <strong className="text-ink">synthetic</strong> (invented data). Its results will be
              labelled as synthetic everywhere.
            </span>
          </label>

          {error && (
            <Alert tone="error" title="Upload failed">
              {error.message}
            </Alert>
          )}

          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={handleUpload} disabled={!file} loading={uploading}>
              {uploading ? 'Uploading…' : 'Upload and detect columns'}
            </Button>
            {USE_MOCK_API && (
              <Button variant="ghost" onClick={loadSyntheticSample} disabled={uploading}>
                Use a synthetic sample file
              </Button>
            )}
          </div>
        </div>
      </Card>

      <FieldGuidePanel fields={fieldGuide.fields} />
    </div>
  );
}
