/**
 * Pages that exist in the design but are built in later phases (architecture
 * §17). The sidebar lists them so the whole product is visible from day one,
 * and each links to a "coming in Phase N" page that says what it will contain.
 * When a page is built, remove it from this list and add a real route.
 */
export const PLANNED_PAGES = [
  {
    path: 'statistics',
    label: 'Statistics & features',
    phase: 'Phase 4',
    capability: 'sales_analytics',
    summary: 'Descriptive statistics with method explanations, entropy and mutual information, and model-based feature importance compared side by side.',
    endpoints: ['GET /analytics/statistics', 'GET /analytics/features', 'GET /analytics/series-profile'],
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
