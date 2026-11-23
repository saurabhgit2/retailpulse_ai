import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';

import OUTLOOK from '../components/forecasting/outlook.fixture.json';

// The page's only network calls go through the forecasts service, so mocking
// it keeps this test off the API entirely. getLatest is the research view's.
vi.mock('../services/forecasts.js', () => ({
  getOutlook: vi.fn(() => Promise.resolve(OUTLOOK)),
  getLatest: vi.fn(() => Promise.reject(new Error('no runs'))),
  getRun: vi.fn(),
  startRun: vi.fn(),
}));

const { getOutlook, getLatest } = await import('../services/forecasts.js');
const { ForecastingPage } = await import('./ForecastingPage.jsx');

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/datasets/abc/forecasting']}>
      <Routes>
        <Route path="/datasets/:datasetId/forecasting" element={<ForecastingPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('ForecastingPage', () => {
  it('leads with the forward forecast for the dataset in the URL', async () => {
    renderPage();
    expect(await screen.findByRole('heading', { name: 'Forecasting' })).toBeInTheDocument();
    expect(getOutlook).toHaveBeenCalledWith('abc', expect.anything());
    expect(screen.getByText(/the last year and the next 12 weeks/)).toBeInTheDocument();
    expect(screen.getByText('Why this method')).toBeInTheDocument();
  });

  it('names the method it used and shows how the others compared', async () => {
    renderPage();
    await screen.findByText('Why this method');
    expect(screen.getByText('Used')).toBeInTheDocument();
    expect(screen.getAllByText('(flat line)').length).toBeGreaterThan(0);
  });

  it('switches between revenue and units', async () => {
    renderPage();
    await screen.findByText(/Revenue: the last year/);
    await userEvent.click(screen.getByRole('button', { name: 'Units' }));
    expect(screen.getByText(/Units: the last year/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Units' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('lists the top products and opens a chart for one', async () => {
    renderPage();
    await screen.findByText('Top products: units expected');
    const first = OUTLOOK.products.rows[0];
    expect(screen.getByText(first.description)).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole('button', { name: 'Chart' })[0]);
    expect(screen.getByText(new RegExp(`${first.description}: units`))).toBeInTheDocument();
  });

  it('loads the research experiment only when asked', async () => {
    renderPage();
    await screen.findByText('Why this method');
    expect(getLatest).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: /Show the model comparison/ }));
    expect(getLatest).toHaveBeenCalled();
  });
});
