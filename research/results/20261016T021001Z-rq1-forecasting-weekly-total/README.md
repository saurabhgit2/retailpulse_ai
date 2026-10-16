# rq1-forecasting-weekly-total

Run at **2026-10-16T02:10:01.264616+00:00**.

Config: `rq1_forecasting.toml`
Config SHA-256: `798b9ecf55bd6922212f23c413a3cdad2c8a20cc9d3f09fa157608eae91a53b3`

A result and the protocol that produced it belong together. If the config hash
here differs from another run's, the two ran different experiments.

## Selection

Selected on cross-validation: **combination_median**
Hold-out scored at: 2026-10-16T02:09:53.638032+00:00

Selection was recorded before the hold-out was scored.

## Significance

Friedman's test does not reject the null (p = 0.384) across 3 blocks, so the differences between these 8 models are not distinguishable from noise. 'combination_median' has the best mean rank, but that ranking should not be presented as a finding.

## Environment

| component | version |
|---|---|
| python | 3.12.1 |
| numpy | 2.3.5 |
| pandas | 2.3.3 |
| scipy | 1.16.3 |
| scikit-learn | 1.7.2 |
| xgboost | not installed |

## Files

| file | what it is |
|---|---|
| `config.toml` | the config that ran, copied byte for byte |
| `run.json` | protocol, summary, significance, hold-out, per-fold detail |
| `per_fold.csv` | models x folds - the input to the significance test |
| `summary.csv` | one row per model |
| `holdout.csv` | the locked window, scored once |
