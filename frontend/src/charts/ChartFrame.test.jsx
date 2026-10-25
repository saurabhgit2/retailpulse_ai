import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { ChartFrame } from './ChartFrame.jsx';

const TABLE = {
  caption: 'Net revenue by week',
  columns: [
    { key: 'week', label: 'Week beginning' },
    { key: 'revenue', label: 'Net revenue', numeric: true },
  ],
  rows: [{ key: '2011-12-05', week: '2011-12-05', revenue: '£227,192' }],
};

describe('ChartFrame', () => {
  it('offers a table view, which is what makes the palette legitimate', async () => {
    // Three of the eight light-mode series hues sit below 3:1 against white.
    // That is only allowed because every value is reachable without colour,
    // so losing this toggle would make the charts non-compliant.
    render(
      <ChartFrame title="Net revenue by week" table={TABLE}>
        <svg data-testid="plot" />
      </ChartFrame>,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Table' }));
    expect(screen.getByText('£227,192')).toBeTruthy();
    expect(screen.queryByTestId('plot')).toBeNull();
  });

  it('shows no legend for a single series and one for two', () => {
    const { rerender, container } = render(
      <ChartFrame title="One" series={[{ key: 'a', label: 'Revenue', color: 'red' }]}>
        <svg />
      </ChartFrame>,
    );
    // A one-swatch legend only restates the title.
    expect(container.querySelector('ul')).toBeNull();

    rerender(
      <ChartFrame
        title="Two"
        series={[
          { key: 'a', label: 'Actual', color: 'red' },
          { key: 'b', label: 'Forecast', color: 'blue' },
        ]}
      >
        <svg />
      </ChartFrame>,
    );
    expect(screen.getByText('Forecast')).toBeTruthy();
  });

  it('holds the previous render while refetching rather than flashing a skeleton', () => {
    render(
      <ChartFrame title="Revenue" refreshing>
        <svg data-testid="plot" />
      </ChartFrame>,
    );
    // Still mounted: no layout jump, no skeleton.
    expect(screen.getByTestId('plot')).toBeTruthy();
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('reports an error with its request id so a log line can be found', () => {
    render(
      <ChartFrame title="Revenue" error={{ message: 'Upstream timeout', requestId: 'r-8821' }}>
        <svg />
      </ChartFrame>,
    );
    expect(screen.getByRole('alert').textContent).toContain('r-8821');
  });

  it('distinguishes an empty result from a failure', () => {
    render(
      <ChartFrame title="Revenue" empty emptyMessage="No sales in this range.">
        <svg data-testid="plot" />
      </ChartFrame>,
    );
    expect(screen.getByText('No sales in this range.')).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });
});
