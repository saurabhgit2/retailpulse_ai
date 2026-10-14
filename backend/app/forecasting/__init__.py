"""Forecasting: the RQ1 experiment (architecture §13).

Same rule as `app/analytics/` and `app/preprocessing/`: **no web framework and
no ORM in here.** Everything takes arrays, Series or DataFrames and returns
plain data. That is what lets the research CLI and the API return the same
numbers, and it is what makes these modules testable in milliseconds.

The order of the modules is the order of the argument:

1. `splits`   - how the data is divided. Written first and locked, because a
                comparison is only worth as much as its protocol.
2. `metrics`  - how error is measured, including the ones that break on zeros.
3. `base`     - the one interface every model implements, and the registry.
4. `baselines`, `fourier`, `ets`, `trees` - the model ladder.
5. `combination` - averaging the members (Aras et al. 2017).
6. `intervals`   - empirical prediction intervals and their coverage.
7. `significance` - Friedman + Bonferroni, as in Aras et al. (2017).
8. `evaluate` - the harness that runs the ladder over the folds.

**What the supplied literature actually supports**, so the report does not
overclaim. Checked against the seventeen papers provided:

* **Multiple out-of-sample windows rather than one split.** Chu & Zhang (2003)
  used a five-fold moving validation scheme, rebuilding every model for each
  window, and state that it "is critical to employ multiple out-of-samples to
  ensure that the results obtained for one particular sample are not due to
  chance or sampling variations".
* **Several error measures, not one.** Chu & Zhang: "there is no universally
  agreed-upon performance measure that can be applied to every forecasting
  situation, multiple criteria are therefore often needed".
* **Combination, and specifically the simple kinds.** Aras, Deveci Kocakoç &
  Polat (2017) compared simple mean, 20% trimmed mean, median, LS weights, MSE
  weights and MSE ranks on ten weekly retail series, and found the simple
  methods matched or beat the elaborate ones, with LS weights worst of all -
  worse than the single models. `combination.py` therefore implements the three
  simple rules and deliberately does not implement LS weights.
* **Friedman's test followed by Bonferroni-corrected multiple comparison.**
  That is exactly the procedure Aras et al. used to decide whether the ranking
  of methods was real; `significance.py` reproduces it.
* **Seasonal adjustment before fitting.** Chu & Zhang found prior seasonal
  adjustment significantly improved neural-network accuracy, and that the best
  model overall was a neural network on deseasonalised data. Phase 4 already
  produces that series.

**What it does not support, and must not be presented as grounded:**

* **MASE.** It appears in none of the supplied papers. It is implemented here
  because it is well defined on zero-valued weeks where MAPE is not, but the
  standard reference for it (Hyndman & Koehler 2006) is outside the supplied
  set - find and read it yourself before citing it, or present MASE as a
  measurement choice of your own with the reasoning given in `metrics.py`.
* **WAPE in its usual form.** Auppakorn & Phumchusri (2022) do use the name,
  but they define it as a *revenue-weighted average of per-product MAPEs*, not
  as sum|e| / sum|y|. Both are implemented here under separate names, and the
  distinction is spelled out in `metrics.py`. Do not cite that paper for the
  aggregate formula.
* **Fourier / trigonometric seasonality.** Chu & Zhang tested trigonometric
  regression on aggregate retail sales and concluded it was *not* useful there.
  Model 4 is kept in the ladder because it is transparent and handles m = 52
  without 51 dummy parameters, but the honest framing is that the one paper in
  the set that tested this approach found against it - which makes it a
  hypothesis to test, not a method to assume.
"""

from __future__ import annotations

from app.forecasting.base import ForecastResult, Forecaster, available_models, get_model
from app.forecasting.splits import Split, holdout_split, rolling_origin_splits

# Importing the model modules is what registers them. Without this, `get_model`
# and `available_models` would depend on whatever the caller happened to have
# imported first, and a research config naming a model would fail or not
# depending on import order elsewhere in the program.
from app.forecasting import baselines as _baselines  # noqa: E402,F401
from app.forecasting import ets as _ets              # noqa: E402,F401
from app.forecasting import fourier as _fourier      # noqa: E402,F401
from app.forecasting import trees as _trees          # noqa: E402,F401

__all__ = [
    "ForecastResult",
    "Forecaster",
    "Split",
    "available_models",
    "get_model",
    "holdout_split",
    "rolling_origin_splits",
]
