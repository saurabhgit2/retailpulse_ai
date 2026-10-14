"""How the data is divided. Written first, and locked before any model exists.

A model comparison is worth exactly as much as its protocol, so this module is
small, strict and heavily tested. Three rules it enforces:

1. **Chronological only.** Every fold satisfies `max(train) < min(test)`. There
   is no shuffling anywhere in this package.
2. **The hold-out is locked.** `holdout_split` carves off the final `horizon`
   periods once. Model selection, hyper-parameters and any decision made after
   looking at a number use the CV folds *inside* the training part only. The
   hold-out is scored once, at the end.
3. **Folds are reproducible.** Nothing random happens here; the same series and
   the same arguments always give the same folds, so a result can be re-derived
   from the config alone.

**Why multiple folds rather than one split.** Chu & Zhang (2003), the aggregate
retail sales study, used a five-fold moving validation scheme with five
out-of-sample periods and rebuilt every model for each one, because "it is
critical to employ multiple out-of-samples to ensure that the results obtained
for one particular sample are not due to chance or sampling variations". One
hold-out measures one draw from the error distribution. Four measure four.

**Expanding or sliding.** Chu & Zhang held the in-sample length *fixed* at ten
years and moved the window forward. The default here is `expanding`, which uses
all history available at each origin, because Online Retail II is short (about
two years of weekly data) and discarding the start would leave too little to
estimate a yearly cycle. `sliding` reproduces their design and is worth running
as a robustness check if the series turns out to be non-stationary - state in
the report which one produced the reported numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

WindowStyle = Literal["expanding", "sliding"]

# Below this many training observations a fold is not worth scoring: the models
# in the ladder that estimate a seasonal component need at least two cycles,
# and the rest produce something meaningless rather than nothing.
MIN_TRAIN_OBSERVATIONS = 8


class SplitError(ValueError):
    """The requested protocol does not fit the data. Raised, never worked around."""


@dataclass(frozen=True)
class Split:
    """One train/test pair. Positions index the series the split came from."""

    fold: int
    train_positions: np.ndarray
    test_positions: np.ndarray
    train_index: pd.Index
    test_index: pd.Index
    style: WindowStyle = "expanding"

    @property
    def horizon(self) -> int:
        return int(len(self.test_positions))

    @property
    def train_size(self) -> int:
        return int(len(self.train_positions))

    def take(self, series: pd.Series) -> tuple[pd.Series, pd.Series]:
        """Slice a series aligned to this split's parent index."""
        return series.iloc[self.train_positions], series.iloc[self.test_positions]

    def as_dict(self) -> dict[str, object]:
        """A record for the run log, so the protocol is auditable after the fact."""
        return {
            "fold": self.fold,
            "style": self.style,
            "train_size": self.train_size,
            "horizon": self.horizon,
            "train_start": _label(self.train_index[0]),
            "train_end": _label(self.train_index[-1]),
            "test_start": _label(self.test_index[0]),
            "test_end": _label(self.test_index[-1]),
        }


@dataclass(frozen=True)
class Protocol:
    """A complete, declared evaluation protocol: the folds plus the hold-out."""

    folds: list[Split]
    holdout: Split
    horizon: int
    style: WindowStyle
    observations: int
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "horizon": self.horizon,
            "style": self.style,
            "observations": self.observations,
            "folds": [split.as_dict() for split in self.folds],
            "holdout": self.holdout.as_dict(),
            "notes": self.notes,
        }


def _label(value: object) -> str:
    if isinstance(value, pd.Timestamp):
        return str(value.date())
    return str(value)


def _ordered_index(series_or_index: pd.Series | pd.Index) -> pd.Index:
    index = (
        series_or_index.index
        if isinstance(series_or_index, pd.Series)
        else pd.Index(series_or_index)
    )
    if len(index) and isinstance(index, pd.DatetimeIndex) and not index.is_monotonic_increasing:
        raise SplitError(
            "The series must be sorted in time before it is split. Sorting it here "
            "would hide the fact that it arrived out of order, which is usually a "
            "bug upstream."
        )
    return index


def holdout_split(
    series_or_index: pd.Series | pd.Index,
    horizon: int,
) -> Split:
    """Carve the final `horizon` observations off as the locked hold-out.

    Everything before them is the training region, and `rolling_origin_splits`
    subdivides *that* for model selection. The hold-out is never part of a CV
    fold, which is the property the leakage tests check.
    """
    index = _ordered_index(series_or_index)
    observations = len(index)
    if horizon < 1:
        raise SplitError(f"Horizon must be at least 1; got {horizon}.")
    if observations < horizon + MIN_TRAIN_OBSERVATIONS:
        raise SplitError(
            f"A hold-out of {horizon} periods needs at least "
            f"{horizon + MIN_TRAIN_OBSERVATIONS} observations; this series has "
            f"{observations}."
        )

    cut = observations - horizon
    train = np.arange(cut)
    test = np.arange(cut, observations)
    return Split(
        fold=0,
        train_positions=train,
        test_positions=test,
        train_index=index[train],
        test_index=index[test],
        style="expanding",
    )


def rolling_origin_splits(
    series_or_index: pd.Series | pd.Index,
    horizon: int,
    folds: int = 4,
    *,
    style: WindowStyle = "expanding",
    min_train: int | None = None,
    step: int | None = None,
) -> list[Split]:
    """Rolling-origin folds, oldest origin first.

    With `horizon=h`, `folds=k` and the default `step=h`, the test windows are
    the last `k*h` observations in consecutive, non-overlapping blocks:

        fold 1: [train.............][test h]
        fold 2: [train...................][test h]
        fold 3: [train.........................][test h]
        fold 4: [train...............................][test h]

    Non-overlapping test windows matter for `significance.py`: Friedman's test
    treats the folds as repeated measures, and overlapping test sets would make
    those measurements share actuals and overstate the evidence.
    """
    index = _ordered_index(series_or_index)
    observations = len(index)
    if horizon < 1:
        raise SplitError(f"Horizon must be at least 1; got {horizon}.")
    if folds < 1:
        raise SplitError(f"At least one fold is required; got {folds}.")

    stride = horizon if step is None else step
    if stride < 1:
        raise SplitError(f"Step must be at least 1; got {stride}.")

    floor = MIN_TRAIN_OBSERVATIONS if min_train is None else min_train
    if floor < 1:
        raise SplitError(f"min_train must be at least 1; got {floor}.")

    # The earliest origin: the first fold trains on `floor` observations, and
    # each later fold starts `stride` further on.
    needed = floor + horizon + stride * (folds - 1)
    if observations < needed:
        raise SplitError(
            f"{folds} folds at horizon {horizon} (step {stride}) need at least "
            f"{needed} observations after the minimum training length of {floor}; "
            f"this series has {observations}. Reduce the folds or the horizon."
        )

    # Anchor the *last* fold's test window at the end of the series, so the most
    # recent data is always used and the earlier folds step backwards from there.
    last_origin = observations - horizon
    first_origin = last_origin - stride * (folds - 1)

    # For a sliding window the training length is constant across folds, which
    # is the whole point of Chu & Zhang's design: if the window also grew, a
    # difference in accuracy between folds could be either the moved origin or
    # the larger sample, and the comparison would not separate them. The
    # constant length is everything available before the earliest origin.
    window = first_origin

    splits: list[Split] = []
    for fold in range(folds):
        origin = first_origin + stride * fold
        start = 0 if style == "expanding" else max(0, origin - window)
        train = np.arange(start, origin)
        test = np.arange(origin, origin + horizon)
        splits.append(
            Split(
                fold=fold + 1,
                train_positions=train,
                test_positions=test,
                train_index=index[train],
                test_index=index[test],
                style=style,
            )
        )
    return splits


def build_protocol(
    series_or_index: pd.Series | pd.Index,
    horizon: int,
    folds: int = 4,
    *,
    style: WindowStyle = "expanding",
    min_train: int | None = None,
) -> Protocol:
    """The declared protocol: CV folds inside the training region, then the hold-out.

    This is the function the research config calls. It is deliberately the only
    place the two are put together, so there is exactly one definition of "the
    CV folds never touch the hold-out" to test.
    """
    index = _ordered_index(series_or_index)
    holdout = holdout_split(index, horizon)
    inner = index[holdout.train_positions]

    notes: list[str] = []
    inner_folds = rolling_origin_splits(
        inner, horizon=horizon, folds=folds, style=style, min_train=min_train
    )
    if style == "expanding":
        notes.append(
            "Training windows expand: each fold uses all history before its origin. "
            "Chu & Zhang (2003) instead held the in-sample length fixed; with about "
            "two years of weekly data here, discarding early history would leave too "
            "little to estimate a yearly cycle."
        )
    return Protocol(
        folds=inner_folds,
        holdout=holdout,
        horizon=horizon,
        style=style,
        observations=len(index),
        notes=notes,
    )


def assert_no_leakage(splits: list[Split], holdout: Split | None = None) -> None:
    """Raise unless every fold is chronological and clear of the hold-out.

    Called by the harness before anything is fitted. A protocol bug found here
    costs a second; found after the results are written up, it costs the chapter.
    """
    for split in splits:
        if split.train_positions.size == 0:
            raise SplitError(f"Fold {split.fold} has an empty training window.")
        if split.test_positions.size == 0:
            raise SplitError(f"Fold {split.fold} has an empty test window.")
        if split.train_positions.max() >= split.test_positions.min():
            raise SplitError(
                f"Fold {split.fold} trains on position "
                f"{int(split.train_positions.max())} and tests from "
                f"{int(split.test_positions.min())}: the training window reaches "
                f"into the test window."
            )
        overlap = np.intersect1d(split.train_positions, split.test_positions)
        if overlap.size:
            raise SplitError(f"Fold {split.fold} shares {overlap.size} observations.")

    if holdout is not None:
        locked = set(holdout.test_positions.tolist())
        for split in splits:
            touched = locked.intersection(split.train_positions.tolist())
            if touched:
                raise SplitError(
                    f"Fold {split.fold} trains on {len(touched)} observations that "
                    f"belong to the locked hold-out."
                )
            touched = locked.intersection(split.test_positions.tolist())
            if touched:
                raise SplitError(
                    f"Fold {split.fold} validates on {len(touched)} observations "
                    f"that belong to the locked hold-out."
                )
