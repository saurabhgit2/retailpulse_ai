# RetailPulse AI

An integrated decision-support platform for retail analytics. It takes one public
transactional dataset and runs demand forecasting, RFM-based customer segmentation and
association-rule mining over a **single shared data foundation**, then reconciles the three
into ranked recommendations with their evidence attached.

MSE907 Industry-based Capstone Research Project · Master of Software Engineering ·
Yoobee College of Creative Innovation. Saurabh Singh (270732411), supervised by
Dr. Haider Ali.

## Why it exists

Forecasting, segmentation and market-basket analysis are each mature, and each is
evaluated in isolation — on different datasets, at different granularities, with metrics
that cannot be compared. Aras et al. (2017) note in their own limitations that the
decision-support platform their methods needed was never built. Alves Gomes and Meisen
(2023) reviewed 105 segmentation studies and could not name a best method, because
evaluation practice is too inconsistent to rank them.

This project builds the thing those papers describe as missing, and measures whether
integrating the three analyses beats using them separately.

## What is in the repository

| | |
|---|---|
| `backend/` | FastAPI service: accounts, upload, cleaning pipeline, and six analytical packages |
| `frontend/` | React single-page application: seven analysis pages |
| `research/` | Experiment runners and their recorded results, one directory per run |
| `docs/` | Architecture, backend and frontend guides, local setup |
| `data/sample/` | Synthetic data for development. Clearly labelled; never a result |

Roughly 160 Python modules and 140 JavaScript modules. **637 backend tests and 280
frontend tests** across 26 files.

The analytical packages — `preprocessing`, `analytics`, `forecasting`, `segmentation`,
`association`, `insights` — import no web framework, no ORM and no database session. An
automated test walks every file in them and fails the build if one does. That rule is
what lets the research scripts and the API share the same code, which is why the
dashboard and the dissertation cannot disagree about a number.

## Quick start

Three processes: PostgreSQL in Docker, the API, and the dev server. Full instructions,
including the problems you are likely to hit, are in
[`docs/RUNNING_LOCALLY.md`](docs/RUNNING_LOCALLY.md).

```bash
docker compose up -d db                     # PostgreSQL 16

cd backend
python -m venv .venv && . .venv/bin/activate   # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
cp .env.example .env                        # then set JWT_SECRET_KEY
alembic upgrade head
uvicorn app.main:app --reload               # http://localhost:8000/docs
```

```bash
cd frontend
npm install
cp .env.example .env
npm run dev                                 # http://localhost:5173
```

Create an account, then **Upload data**. For the real dataset, download Online Retail II
from Kaggle and upload the `.xlsx` unchanged — both year sheets are read and stacked.

## The dashboard

Seven pages, each reading only analyses the API exposes:

- **Data quality** — what the twelve-step cleaning pipeline did, and what it withheld
- **Dashboard** — headline figures with URL-synced date and region filters
- **Explore** — calendar seasonality, the weekly trend, revenue-per-line distribution
- **Forecasting** — start a run, poll it, compare models on a locked hold-out
- **Customers** — RFM segments, concentration, value and recency distributions
- **Baskets** — basket size and order value, on linear or logarithmic axes
- **Statistics & features** — descriptive statistics, group comparison with its test,
  mutual information, and the demand-series forecastability profile
- **Insights** — explains where the insight layer lives and why it is not a page here

Charts are hand-written SVG rather than a charting library. Every other analytical
component in this project is implemented from its definition so the report can explain
it, and the chart layer follows the same rule: scales and path generation are about 200
lines. The cost, stated in the limitations, is no zoom, no brush selection and no
animated transitions.

## Reproducing the research

Each research question has a runner and a configuration file, and each run writes a
timestamped directory holding its configuration, the SHA-256 digest of that
configuration, the library versions and the outputs. See
[`research/README.md`](research/README.md).

## What is deliberately not here

- **No generative language model.** "AI" here means machine learning and statistical
  pattern discovery: gradient-boosted trees, three unsupervised clustering families,
  association-rule mining, and information-theoretic feature analysis. A conversational
  assistant was specified in Assessment 1 and withdrawn in Assessment 2.
- **No segmentation, association or recommendation API endpoints.** Those engines run as
  reproducible research pipelines. The dashboard presents what the API exposes; the
  decision and its limitation are recorded in Assessment 2.
- **No LSTM.** Assessment 1 §9.5 permitted dropping it, and it was dropped. The
  forecasting comparison stands on statistical, tree-based and combination approaches.

## Dataset

Online Retail II (UCI, via Kaggle) — a public set of invoices from a UK online retailer
covering about two years. Public, transaction-level, and able to support all three
analyses from one source, which is what the shared-foundation requirement needs.

It is **not** committed to this repository. `data/raw/` and `data/uploads/` are ignored.

## Documentation

| Document | What it covers |
|---|---|
| [`docs/RUNNING_LOCALLY.md`](docs/RUNNING_LOCALLY.md) | Setup, daily start-up, and what goes wrong |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Design, layering, API contract, data model |
| [`docs/BACKEND_GUIDE.md`](docs/BACKEND_GUIDE.md) | Walkthrough of `backend/`, written to be rebuilt from |
| [`docs/FRONTEND_GUIDE.md`](docs/FRONTEND_GUIDE.md) | Walkthrough of `frontend/` |
| [`research/README.md`](research/README.md) | Reproducing each research result |
| [`Folder_Structure.md`](Folder_Structure.md) | The tree, annotated |
