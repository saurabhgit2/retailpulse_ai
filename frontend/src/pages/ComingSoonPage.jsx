import { Link } from 'react-router';
import { PageHeader } from '../components/layout/PageHeader';
import { buttonClasses } from '../components/ui/buttonStyles';
import { Badge } from '../components/ui/Badge';
import { Card } from '../components/ui/Card';
import { useDatasets } from '../hooks/useDatasets';

/**
 * Placeholder for pages built in later phases. It says what the page will do
 * and which endpoints it will call, so the roadmap is visible in the product.
 */
export function ComingSoonPage({ page }) {
  const { currentDataset } = useDatasets();
  return (
    <>
      <PageHeader
        eyebrow={<Badge tone="accent">{page.phase}</Badge>}
        title={page.label}
        description={page.summary}
      />
      <Card title="Planned for this page">
        <p className="text-sm text-ink-2">This page is built in {page.phase}. It will call:</p>
        <ul className="mt-3 flex flex-col gap-1">
          {page.endpoints.map((endpoint) => (
            <li key={endpoint}>
              <code className="font-mono text-xs text-ink-2">{endpoint}</code>
            </li>
          ))}
        </ul>
        {currentDataset && (
          <Link to={`/datasets/${currentDataset.id}/quality`} className={buttonClasses({ variant: 'secondary', size: 'sm', className: 'mt-5' })}>
            Back to data quality
          </Link>
        )}
      </Card>
    </>
  );
}
