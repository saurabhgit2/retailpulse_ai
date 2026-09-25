# charts/

Reusable chart components (Recharts) arrive in **Phase 4**, when the analytics
endpoints exist: `TimeSeriesChart`, `BarRanking`, `Histogram`, `ScatterPlot`,
`ForecastChart`, `FeatureComparisonChart`, `HeatmapTable`.

Rule for this folder: a chart component receives data that is already shaped
for display (arrays of `{ x, y }`-style rows) and knows nothing about the API.
Pages fetch; charts draw.
