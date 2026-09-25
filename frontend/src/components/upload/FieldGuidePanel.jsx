import { useState } from 'react';
import { downloadTemplate } from '../../services/datasets';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { Card } from '../ui/Card';

const STATUS_TONE = { required: 'crit', recommended: 'accent', optional: 'neutral' };

/** The recommended dataset format (brief §33), plus a template download. */
export function FieldGuidePanel({ fields }) {
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState(null);

  async function handleDownload() {
    setDownloading(true);
    setError(null);
    try {
      const blob = await downloadTemplate();
      // Turn the Blob into a temporary URL and click a hidden link to save it.
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'retailpulse_template.csv';
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err.message);
    } finally {
      setDownloading(false);
    }
  }

  return (
    <Card
      title="Recommended format"
      description="One row per sold line. Column names don't have to match: you confirm the mapping in the next step."
      actions={
        <Button variant="secondary" size="sm" loading={downloading} onClick={handleDownload}>
          Download CSV template
        </Button>
      }
      bodyClassName="p-0"
    >
      {error && <p className="px-5 pt-3 text-sm text-crit">{error}</p>}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[36rem] text-sm">
          <thead className="bg-surface-2 text-left text-xs tracking-wide text-muted uppercase">
            <tr>
              <th scope="col" className="px-5 py-2 font-medium">Field</th>
              <th scope="col" className="px-5 py-2 font-medium">Example</th>
              <th scope="col" className="px-5 py-2 font-medium">Also recognised as</th>
            </tr>
          </thead>
          <tbody>
            {fields.map((field) => (
              <tr key={field.key} className="border-t border-rule align-top">
                <td className="px-5 py-2.5">
                  <span className="font-medium text-ink">{field.label}</span>{' '}
                  <Badge tone={STATUS_TONE[field.status]}>{field.status}</Badge>
                </td>
                <td className="px-5 py-2.5 font-mono text-xs text-ink-2">{field.example}</td>
                <td className="px-5 py-2.5 text-xs text-muted">{field.synonyms.slice(0, 4).join(', ')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
