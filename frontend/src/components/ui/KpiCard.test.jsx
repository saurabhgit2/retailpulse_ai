import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { KpiCard } from './KpiCard.jsx';

describe('KpiCard', () => {
  it('shows a compacted value', () => {
    render(<KpiCard label="Net revenue" value={17_743_000} currency="£" />);
    expect(screen.getByText('£17.7M')).toBeTruthy();
  });

  it('says a missing value is not available instead of showing zero', () => {
    // The pipeline withholds a KPI whose source column is absent. Rendering
    // it as 0 would turn "we cannot compute this" into "there were none".
    render(
      <KpiCard
        label="Units sold"
        value={null}
        unavailableReason="This dataset has no quantity column."
      />,
    );
    expect(screen.getByText('Not available')).toBeTruthy();
    expect(screen.queryByText('0')).toBeNull();
  });

  it('shows the reason instead of a growth figure when growth was withheld', () => {
    // Growth is only computed when both comparison windows are the same
    // length and complete. 0% would be a claim the backend refused to make.
    render(
      <KpiCard
        label="Average order value"
        value={448.9}
        growth={null}
        currency="£"
        note="Growth withheld: the comparison windows are not the same length."
      />,
    );
    expect(screen.getByText(/windows are not the same length/)).toBeTruthy();
    expect(screen.queryByText(/0\.0%/)).toBeNull();
  });

  it('marks direction with an arrow as well as a colour', () => {
    const { container } = render(<KpiCard label="Orders" value={100} growth={-0.031} />);
    expect(container.textContent).toContain('↓');
    expect(container.textContent).toContain('-3.1%');
  });

  it('treats no change as neither good nor bad', () => {
    const { container } = render(<KpiCard label="Customers" value={10} growth={0} />);
    expect(container.textContent).toContain('→');
  });
});
