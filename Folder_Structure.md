retailpulse_ai/
├── README.md                     # Overview, setup, run, test, dataset format
├── docker-compose.yml            # PostgreSQL (and nothing else) for reproducible local setup
├── .gitignore                    # .env, data/raw, data/uploads, data/artifacts, node_modules, .venv
├── .github/workflows/ci.yml      # Lint + tests on every push (Should)
│
├── backend/
│   ├── .env.example              # DATABASE_URL=, AI_API_KEY=, … placeholders only
│   ├── requirements.txt          # Pinned runtime dependencies
│   ├── requirements-dev.txt      # pytest, ruff, httpx, …
│   ├── requirements-deep.txt     # PyTorch (optional LSTM)
│   ├── pyproject.toml            # Tool config (ruff, pytest); project metadata
│   ├── alembic.ini
│   ├── alembic/versions/         # One migration per schema change, committed to git
│   ├── scripts/
│   │   ├── generate_synthetic_data.py   # Labelled SYNTHETIC dataset for development/tests
│   │   └── seed_demo_user.py
│   ├── app/
│   │   ├── main.py               # App factory: routers, CORS, exception handlers, startup
│   │   ├── core/                 # Cross-cutting: config.py (settings), logging.py, errors.py, security.py (hashing, JWT)
│   │   ├── api/
│   │   │   ├── deps.py           # Dependencies: DB session, current user, dataset ownership, filters
│   │   │   ├── error_handlers.py # Exceptions → error envelope
│   │   │   └── routes/           # health, auth, datasets, analytics, forecasts, segmentations,
│   │   │                         # associations, recommendations, ai — HTTP only
│   │   ├── schemas/              # Pydantic request/response models, one file per resource
│   │   ├── db/
│   │   │   ├── session.py        # Engine + session factory
│   │   │   ├── base.py           # Declarative base, naming conventions
│   │   │   ├── models/           # SQLAlchemy ORM classes, one file per aggregate
│   │   │   └── repositories/     # Query functions; SQL aggregation → DataFrames; bulk COPY
│   │   ├── services/             # Use-case orchestration and status transitions
│   │   ├── preprocessing/        # PURE: schema_detection, column_mapping, validation, cleaning, report
│   │   ├── analytics/            # PURE: kpis, eda, statistics, entropy, features, series_profile, anomalies
│   │   ├── forecasting/          # PURE: base (model interface), baselines, statistical, ml (xgboost),
│   │   │                         # deep (lstm), combination, features, splits, metrics, significance, registry
│   │   ├── segmentation/         # PURE: rfm, clustering, quality, stability
│   │   ├── association/          # PURE: baskets, mining, actionability
│   │   ├── recommendations/      # PURE: signals, rules (weights from config), engine
│   │   ├── ai/
│   │   │   ├── providers/        # base.py (interface), anthropic_provider, openai_provider, mock_provider, factory
│   │   │   ├── prompts/          # insights_v1.md, chat_v1.md — versioned prompt templates
│   │   │   ├── fact_sheet.py     # Builds the grounded fact sheet from analytics results
│   │   │   ├── prompt_builder.py
│   │   │   ├── grounding.py      # Validates output: fact IDs exist, numbers match facts
│   │   │   ├── insight_service.py
│   │   │   └── chat_service.py
│   │   └── utils/                # dates (ISO weeks, partial periods), hashing
│   └── tests/
│       ├── conftest.py           # Fixtures: tiny DataFrames, test DB, API client, auth
│       ├── fixtures/             # Hand-computed mini CSVs (expected values known)
│       ├── unit/                 # Pure-core tests: no DB, no network
│       ├── api/                  # Endpoint tests against the test database
│       └── integration/          # Upload → process → analytics; analytics → forecast → AI (mock)
│
├── frontend/
│   ├── .env.example              # VITE_API_BASE_URL=/api/v1 (public; never secrets)
│   ├── package.json · vite.config.js · tailwind config · index.html
│   └── src/
│       ├── main.jsx · App.jsx · routes.jsx
│       ├── pages/                # One per screen: Login, Datasets, UploadWizard, DataQuality, Dashboard,
│       │                         # Explore, StatisticsFeatures, Forecasting, Customers, Baskets, Insights
│       ├── components/
│       │   ├── layout/           # AppShell, Sidebar, TopBar, DatasetSwitcher, FilterBar
│       │   ├── ui/               # Card, KpiCard, Button, Alert, Spinner, EmptyState, ErrorState, Badge
│       │   ├── upload/           # FileDropzone, ColumnMappingTable, QualityReport
│       │   ├── explain/          # MethodCard ("About this analysis"), SourceBadge (Data / AI)
│       │   └── ai/               # InsightList, ChatPanel, GroundingIndicator
│       ├── charts/               # TimeSeriesChart, ForecastChart, BarRanking, Histogram, ScatterPlot,
│       │                         # FeatureComparisonChart, HeatmapTable
│       ├── services/             # apiClient.js (fetch wrapper, auth header, error normalisation) +
│       │                         # datasets.js, analytics.js, forecasts.js, segments.js, ai.js, auth.js
│       ├── hooks/                # useApi, usePolling, useFilters (URL-synced), useAuth
│       ├── context/              # AuthContext, DatasetContext (current dataset + capabilities)
│       ├── content/              # methodCards.js — explanation text for each analysis
│       └── utils/                # format.js (currency, %, dates), constants.js
│       (tests sit next to components as *.test.jsx)
│
├── research/                     # EXPERIMENTS — separate from the app, same core code
│   ├── README.md                 # How to reproduce each RQ result
│   ├── configs/                  # rq1_forecasting.toml, rq2_segmentation.toml, rq3_rules.toml (pre-declared)
│   ├── run_experiment.py         # CLI: python -m research.run_experiment configs/rq1_forecasting.toml
│   ├── notebooks/                # 01_profile_online_retail.ipynb, 02_eda.ipynb, 03_rq1_analysis.ipynb, …
│   ├── notes/                    # Research write-ups, e.g. rq1_inductive_bias.md (separate from software docs)
│   ├── results/                  # Exported tables/figures (large raw outputs git-ignored)
│   └── rq4_evaluation/           # Rubric, protocol, task scripts, consent form template
│
├── data/
│   ├── sample/                   # synthetic_retail_sales.csv + README stating it is SYNTHETIC
│   ├── raw/                      # online_retail_II.csv (git-ignored; download instructions in README)
│   ├── uploads/                  # Stored uploads (git-ignored)
│   └── artifacts/                # Model files (git-ignored)
│
└── docs/
    ├── ARCHITECTURE.md           # This document, kept up to date
    ├── adr/                      # 0001-modular-monolith.md, …
    ├── API.md · DATABASE.md · DATASET_GUIDE.md · MODELS.md · AI.md · TESTING.md
    ├── USER_JOURNEY.md · LIMITATIONS.md · DEMO_SCRIPT.md · INTERVIEW_PREP.md
    └── images/                   # Diagrams and screenshots
