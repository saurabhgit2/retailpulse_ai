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

Each writes a new directory under `results/`, named `<UTC timestamp>Z-<run name>`.
Nothing is overwritten: running the same configuration twice produces two directories,
which is how the repeat runs exist alongside the originals.

## What a result directory contains

| file | contents |
|---|---|
| `config.toml` | the exact configuration used, copied at run time |
| `run.json` | config hash, environment, protocol, per-fold results, significance tests, selection |
| `*.csv` | the same results as flat tables, for the write-up |
| `README.md` | on some runs: what the run was for |

`run.json` records a **SHA-256 digest of the configuration**, the Python and library
versions, and — for runs that read the dataset — the dataset identifier, the pipeline
version and a `clean_data_sha256`. A result can therefore be tied to the data and the
code that produced it, which is the comparability failure Sections 3.1 and 3.2 of
Assessment 1 identify in the literature.

## The recorded runs

| directory | RQ | what it is |
|---|---|---|
| `20261016T012057Z-rq1-forecasting-weekly-total` | 1 | primary run: eight models, three expanding folds, one locked hold-out |
| `20261016T021001Z-rq1-forecasting-weekly-total` | 1 | repeat run |
| `20261017T002315Z-rq2-segmentation-stability` | 2 | primary run: three clustering families across four windows |
| `20261017T004117Z-rq2-segmentation-stability` | 2 | repeat run |
| `20261020T230649Z-rq3-association-rules` | 3 | first execution, uncapped basket size |
| `20261020T232331Z-rq3-association-rules` | 3 | **re-execution of the same configuration** — see below |
| `20261021T002558Z-rq3-association-rules` | 3 | sensitivity run, basket size capped at 200 |
| `20261023T004258Z-rq4-insight-layer` | 4 | both experimental conditions; names the three engine runs it drew on, with their config hashes |

The RQ4 run is the one to read first if you want to see how the three engines are
reconciled: it records which findings corroborate one another and which do not, and it
writes both the integrated and the isolated-component condition.

## Reproducibility, demonstrated

Assessment 1 Table 10 sets a criterion of *"independent re-execution of the published
pipeline — reported metrics reproduced within a stated tolerance"*.

`20261020T230649Z` and `20261020T232331Z` are the same configuration executed seventeen
minutes apart. They agree exactly:

| | value |
|---|---|
| `config_hash` (both) | `dbee4674fb9001f332dd812b77c8d8be1bc97aefedb982a05cee98a07b021682` |
| `rules.csv` SHA-256 (both) | `BBBCD00EA25C43561B15C30F6464033ABFC2049943D51839829F240EB89D7B18` |
| rules generated / retained | 1,148 / 1,106 in both |

**Byte-identical output.** No tolerance is required, because there is no difference to
tolerate. Verify it yourself:

```powershell
Get-FileHash research\results\20261020T230649Z-rq3-association-rules\rules.csv,research\results\20261020T232331Z-rq3-association-rules\rules.csv
```

The third RQ3 directory, `20261021T002558Z`, is a different configuration — basket size
capped at 200 to test whether a small number of very large wholesale orders was carrying
the result. It produces 796 rules against 1,148, and the conclusion does not change.

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
  approximate — and the run says so in its own output.

## Reading the results honestly

Three things in these directories are easy to misread.

**Cross-validation rank is not hold-out rank.** In the RQ1 runs, the model selected on
cross-validation placed fifth of eight on the hold-out, and the model that won the
hold-out was third on cross-validation. Both tables are in the directory. Quote both.

**A missed target is a result.** Assessment 1 Table 10 fixed its targets in advance and
says so explicitly. Several were missed, and the misses carry more information than the
passes — notably that segment instability holds across all three clustering families,
which makes it a property of the customer base rather than of any one algorithm.

**One criterion could never have been met.** Table 10 asks for a cost-sensitive
comparison using an asymmetric holding-versus-shortage cost function. Online Retail II
records neither cost nor stock, which the architecture document identified as finding
F3 before the build began. It is not computable on this dataset and no run attempts it.

## Logs

`rq2_run_k3.log`, `rq3_run_capped200.log`, `rq3_run_uncapped.log` and `rq4_run.log` at
the repository root are console captures from those runs, kept for the record. The
authoritative output is always the result directory.

## A note on version control

`results/.gitignore` once contained a bare `*`. Directories committed before it stayed
tracked, so nothing appeared to be wrong, while every run created afterwards was
silently excluded — including the primary RQ1 run and the re-execution that demonstrates
reproducibility above. The rule now excludes only large binary artefacts. **A result
that is not in version control cannot be cited.**