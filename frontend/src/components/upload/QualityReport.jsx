import { formatDate, formatNumber } from '../../utils/format';
import { Alert } from '../ui/Alert';
import { Badge } from '../ui/Badge';
import { Card } from '../ui/Card';
import { StatTile } from '../ui/StatTile';
import { CapabilityList } from './CapabilityList';
import { WarningList } from './WarningList';

const KIND = {
  excluded: { label: 'Excluded', tone: 'crit' },
  flagged: { label: 'Flagged, kept', tone: 'warn' },
  transformed: { label: 'Transformed', tone: 'info' },
};

/** Renders the report returned by GET /datasets/{id}/quality-report. */
export function QualityReport({ report }) {
  const { summary, conservation, actions, warnings, capabilities, scope, date_range: dateRange } = report;

  return (
    <div className="flex flex-col gap-6">
      {scope?.mode === 'mock_preview' && (
        <Alert tone="info" title="Mock report">
          {scope.note} Rows examined: {formatNumber(scope.rows_examined)}.
        </Alert>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile label={scope?.mode === 'mock_preview' ? 'Rows examined' : 'Rows in file'} value={formatNumber(summary.rows_raw)} />
        <StatTile label="Rows kept" value={formatNumber(summary.rows_clean)} />
        <StatTile label="Rows excluded" value={formatNumber(summary.rows_excluded)} hint="See reasons below" />
        <StatTile label="Returns flagged" value={formatNumber(summary.rows_returns_flagged)} hint="Kept for net revenue" />
      </div>

      <p className={`tabular text-sm ${conservation.ok ? 'text-ok' : 'text-crit'}`}>
        <strong>Conservation check {conservation.ok ? 'passed' : 'FAILED'}:</strong>{' '}
        {formatNumber(conservation.rows_raw)} rows = {formatNumber(conservation.rows_clean)} kept +{' '}
        {formatNumber(conservation.rows_excluded)} excluded
        {conservation.ok ? '. No rows were dropped silently.' : '. Some rows are unaccounted for.'}
      </p>

      <Card title="What the pipeline did" description="In the order the steps ran." bodyClassName="p-0">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[44rem] text-sm">
            <thead className="bg-surface-2 text-left text-xs tracking-wide text-muted uppercase">
              <tr>
                <th scope="col" className="w-10 px-4 py-2 font-medium">#</th>
                <th scope="col" className="px-4 py-2 font-medium">Step</th>
                <th scope="col" className="px-4 py-2 text-right font-medium">Rows affected</th>
                <th scope="col" className="px-4 py-2 font-medium">Why</th>
              </tr>
            </thead>
            <tbody>
              {actions.map((action, index) => (
                <tr key={action.step} className="border-t border-rule align-top">
                  <td className="tabular px-4 py-3 text-muted">{index + 1}</td>
                  <td className="px-4 py-3">
                    <div className="font-medium text-ink">{action.title}</div>
                    <Badge tone={KIND[action.kind]?.tone} className="mt-1">
                      {KIND[action.kind]?.label ?? action.kind}
                    </Badge>
                  </td>
                  <td className="tabular px-4 py-3 text-right font-semibold text-ink">
                    {formatNumber(action.rows_affected)}
                  </td>
                  <td className="px-4 py-3 text-ink-2">
                    <p>{action.rationale}</p>
                    {action.examples?.length > 0 && (
                      <details className="mt-2">
                        <summary className="cursor-pointer text-xs font-medium text-accent">
                          Show {action.examples.length} example row{action.examples.length > 1 ? 's' : ''}
                        </summary>
                        <pre className="mt-2 overflow-x-auto rounded-md bg-surface-2 p-3 font-mono text-xs text-ink-2">
                          {action.examples.map((example) => JSON.stringify(example)).join('\n')}
                        </pre>
                      </details>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <WarningList warnings={warnings} title="Warnings" />

      <Card
        title="Analyses available for this dataset"
        description={
          dateRange?.min
            ? `Data from ${formatDate(dateRange.min, { utc: true })} to ${formatDate(dateRange.max, { utc: true })} · pipeline ${report.pipeline_version}`
            : `Pipeline ${report.pipeline_version}`
        }
      >
        <CapabilityList capabilities={capabilities} />
      </Card>
    </div>
  );
}
