# Research

The experiments behind the four research questions. These are **separate programs from
the web application and share its analytical code**: the runners import
`backend/app/forecasting`, `segmentation`, `association` and `insights` directly, which
is why a figure in the dissertation and a figure in the dashboard cannot disagree.

```
research/
├── configs/               one TOML per research question, pre-declared
├── run_experiment.py      RQ1 — forecasting comparison
├── run_segmentation.py    RQ2 — clustering quality and temporal stability
├── run_association.py     RQ3 — rule mining, filtering and hold-out validation
├── run_insights.py        RQ4 — the insight layer, both experimental conditions
└── results/               one timestamped directory per run
```

## Running an experiment

With the backend virtual environment active and the database up:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
cd ..
python -m research.run_experiment research/configs/rq1_forecasting.toml
python -m research.run_segmentation research/configs/rq2_segmentation.toml
python -m research.run_association research/configs/rq3_association.toml
python -m research.run_insights research/configs/rq4_insights.toml
```

Each writes a new directory under `results/`, named
`<UTC timestamp>Z-<run name>`. Nothing is overwritten: a second run of the same
configuration produces a second directory, which is how the robustness runs exist
alongside the primary ones.

## What a result directory contains

Every directory holds the configuration that produced it and enough provenance to
re-execute it:

| file | contents |
|---|---|
| `config.toml` | the exact configuration used, copied at run time |
| `run.json` | everything: config hash, environment, protocol, per-fold results, significance tests, selection |
| `*.csv` | the same results as flat tables, for the write-up |
| `README.md` | present on some runs: what the run was for |

`run.json` records a **SHA-256 digest of the configuration**, the Python and library
versions, and — for runs that read the dataset — the dataset identifier, the pipeline
version and a `clean_data_sha256`. A result can therefore be tied to the data and the
code that produced it, which is the comparability failure Sections 3.1 and 3.2 of
Assessment 1 identify in the literature.

## The recorded runs

| directory | question | notes |
|---|---|---|
| `20261016T021001Z-rq1-forecasting-weekly-total` | RQ1 | eight models, three expanding folds, one locked hold-out |
| `20261017T002315Z-rq2-segmentation-stability` | RQ2 | three clustering families |
| `20261017T004117Z-rq2-segmentation-stability` | RQ2 | robustness run |
| `20261020T232331Z-rq3-association-rules` | RQ3 | uncapped basket size |
| `20261021T002558Z-rq3-association-rules` | RQ3 | basket size capped at 200 |
| `20261023T004258Z-rq4-insight-layer` | RQ4 | names the three engine runs it drew on, with their config hashes |

The RQ4 run is the one to read first if you want to see how the three engines are
reconciled: it records which findings corroborate each other and which do not, and it
writes both the integrated and the isolated-component condition.

## Protocol

The safeguards that make the comparison valid, and which the reviewed literature
generally lacks:

- **Chronological splitting, never random.** No look-ahead leakage.
- **The hold-out is locked** and scored once, at the end. Model selection uses
  rolling-origin cross-validation on the training portion only.
- **Identical preprocessing for every model**, so a difference traces to the model and
  not to the data.
- **Feature asymmetry is reported, not absorbed.** A univariate baseline cannot consume
  promotional features; `uses_exogenous` is recorded per model rather than hidden.
- **Significance is tested**, with the number of blocks reported alongside the p-value,
  because three blocks makes the chi-square approximation behind Friedman's test
  approximate.

## Reading the results honestly

Two things in these directories are easy to misread.

**Cross-validation rank is not hold-out rank.** In the RQ1 run, the model selected on
cross-validation placed fifth of eight on the hold-out, and the model that won the
hold-out was third on cross-validation. Both tables are in the directory; quote both.

**A missed target is a result.** Assessment 1 Table 10 fixed seven targets in advance
and says so explicitly. Several were missed, and the misses carry more information than
the passes — notably that segment instability holds across all three clustering
families, which makes it a property of the customer base rather than of any algorithm.

## Logs

`rq2_run_k3.log`, `rq3_run_capped200.log`, `rq3_run_uncapped.log` and `rq4_run.log` at
the repository root are console captures from those runs, kept for the record. The
authoritative output is always the result directory.
