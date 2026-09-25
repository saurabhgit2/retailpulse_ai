import { useMemo, useState } from 'react';
import { processDataset } from '../../services/datasets';
import { computeCapabilities, findDuplicateSources, findMissingRequired } from '../../utils/capabilities';
import { formatNumber } from '../../utils/format';
import { METHOD_CARDS } from '../../content/methodCards';
import { Alert } from '../ui/Alert';
import { Button } from '../ui/Button';
import { Card } from '../ui/Card';
import { MethodCard } from '../explain/MethodCard';
import { ColumnMappingTable } from './ColumnMappingTable';
import { DateFormatPicker } from './DateFormatPicker';
import { CapabilityList } from './CapabilityList';
import { WarningList } from './WarningList';

/** Step 2: confirm the column mapping, then start processing. */
export function MapColumnsStep({ dataset, fieldGuide, onStarted, onChooseAnotherFile }) {
  const { profile } = dataset;
  const [mapping, setMapping] = useState(() => ({ ...profile.suggested_mapping, ...(dataset.column_mapping ?? {}) }));
  const [chosenDateFormat, setChosenDateFormat] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  // Everything below is *derived* from mapping on each render, so it can never
  // fall out of step with what the user has selected.
  const dateColumn = profile.detected_columns.find((c) => c.name === mapping.occurred_at);
  const dateCandidates = dateColumn?.date_format_candidates ?? [];
  const dateFormat =
    dateCandidates.length === 1 ? dateCandidates[0] : dateCandidates.includes(chosenDateFormat) ? chosenDateFormat : null;

  const capabilities = useMemo(
    () => computeCapabilities(mapping, fieldGuide.capabilities),
    [mapping, fieldGuide.capabilities],
  );

  const problems = [];
  const missingRequired = findMissingRequired(mapping, fieldGuide.fields);
  if (missingRequired.length) problems.push(`Map the required field(s): ${missingRequired.join(', ')}.`);
  const requiredKeys = new Set(fieldGuide.capabilities.filter((c) => c.required).map((c) => c.key));
  capabilities
    .filter((c) => requiredKeys.has(c.key) && !c.enabled)
    .forEach((c) => problems.push(`${c.label} needs: ${c.missing.join(', ')}.`));
  const duplicates = findDuplicateSources(mapping);
  if (duplicates.length) problems.push(`Each column can be used once. Used twice: ${duplicates.join(', ')}.`);
  if (mapping.occurred_at && !dateFormat) problems.push('Choose how dates should be read.');

  function handleFieldChange(fieldKey, column) {
    // Always create a new object: React only re-renders when state is replaced.
    setMapping((previous) => ({ ...previous, [fieldKey]: column }));
    setError(null);
  }

  async function handleSubmit() {
    setSubmitting(true);
    setError(null);
    try {
      await processDataset(dataset.id, { mapping, options: { date_format: dateFormat } });
      onStarted();
    } catch (err) {
      setError(err);
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      {dataset.status === 'failed' && dataset.status_message && (
        <Alert tone="error" title="The last attempt failed">
          {dataset.status_message}
        </Alert>
      )}

      <Card
        title="Map your columns"
        description={`${profile.detected_columns.length} columns detected from the first ${formatNumber(
          profile.preview.rows_examined,
        )} rows of ${dataset.original_filename}.`}
      >
        <div className="flex flex-col gap-5">
          <WarningList warnings={profile.warnings} title="Found when reading your file" />
          <ColumnMappingTable
            fields={fieldGuide.fields}
            columns={profile.detected_columns}
            mapping={mapping}
            onChange={handleFieldChange}
          />
          {mapping.occurred_at && (
            <DateFormatPicker candidates={dateCandidates} value={dateFormat} onChange={setChosenDateFormat} />
          )}
        </div>
      </Card>

      <Card title="What this mapping enables" description="Updates as you change the mapping.">
        <CapabilityList capabilities={capabilities} />
      </Card>

      <MethodCard card={METHOD_CARDS.columnMapping} />

      {problems.length > 0 && (
        <Alert tone="warning" title="Before you continue">
          <ul className="list-disc space-y-1 pl-4">
            {problems.map((problem) => (
              <li key={problem}>{problem}</li>
            ))}
          </ul>
        </Alert>
      )}
      {error && (
        <Alert tone="error" title="Processing could not start">
          {error.message}
        </Alert>
      )}

      <div className="flex flex-wrap gap-3">
        <Button onClick={handleSubmit} disabled={problems.length > 0} loading={submitting}>
          Confirm mapping and process
        </Button>
        <Button variant="secondary" onClick={onChooseAnotherFile} disabled={submitting}>
          Choose a different file
        </Button>
      </div>
    </div>
  );
}
