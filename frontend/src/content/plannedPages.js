/**
 * Pages that exist in the design but are built in later phases (architecture
 * §17). The sidebar lists them so the whole product is visible from day one,
 * and each links to a "coming in Phase N" page that says what it will contain.
 * When a page is built, remove it from this list and add a real route.
 */
export const PLANNED_PAGES = [
  {
    path: 'dashboard',
    label: 'Dashboard',
    phase: 'Phase 7',
    capability: 'sales_analytics',
    summary: 'KPI cards, sales over time, top products and regions, a forecast snapshot and an AI insight summary, all filterable by date, product and region.',
    endpoints: ['GET /analytics/kpis', 'GET /analytics/trends', 'GET /analytics/products', 'GET /analytics/regions'],
  },
  {
    path: 'explore',
    label: 'Explore',
    phase: 'Phase 4',
    capability: 'sales_analytics',
    summary: 'Exploratory analysis: distributions, daily/weekly/monthly trends, seasonality, breakdowns and relationships between variables.',
    endpoints: ['GET /analytics/distributions', 'GET /analytics/seasonality', 'GET /analytics/relationships'],
  },
  {
    path: 'statistics',
    label: 'Statistics & features',
    phase: 'Phase 4',
    capability: 'sales_analytics',
    summary: 'Descriptive statistics with method explanations, entropy and mutual information, and model-based feature importance compared side by side.',
    endpoints: ['GET /analytics/statistics', 'GET /analytics/features', 'GET /analytics/series-profile'],
  },
  {
    path: 'forecasting',
    label: 'Forecasting',
    phase: 'Phase 5',
    capability: 'demand_forecasting',
    summary: 'Configure and run forecasts, compare models (MAE, RMSE, WAPE, MASE, MAPE), view actual vs predicted, and see significance tests (RQ1).',
    endpoints: ['POST /forecasts', 'GET /forecasts/{run_id}', 'GET /forecasts/{run_id}/series'],
  },
  {
    path: 'customers',
    label: 'Customers',
    phase: 'Phase 5b',
    capability: 'segmentation',
    summary: 'RFM segments from three clustering algorithms, their quality scores, and how stable they are across time windows (RQ2).',
    endpoints: ['POST /segmentations', 'GET /segmentations/{run_id}'],
  },
  {
    path: 'baskets',
    label: 'Baskets',
    phase: 'Phase 5b',
    capability: 'association_rules',
    summary: 'Association rules ranked by actionability rather than frequency, with the size of the rule set after each filter (RQ3).',
    endpoints: ['POST /association-runs', 'GET /association-runs/{run_id}/rules'],
  },
  {
    path: 'insights',
    label: 'Insights',
    phase: 'Phase 6',
    capability: 'sales_analytics',
    summary: 'Ranked, evidence-backed recommendations, grounded AI interpretation (labelled as AI), and the RetailPulse assistant (RQ4).',
    endpoints: ['GET /recommendations', 'POST /ai/insights', 'POST /ai/chat'],
  },
];
