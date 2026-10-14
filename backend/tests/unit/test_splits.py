"""The evaluation protocol.

These tests exist to make one claim defensible: no model in this project ever
saw the data it was scored on. They are the first thing to point at if anyone
asks how the comparison was controlled.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.forecasting.splits import (
    MIN_TRAIN_OBSERVATIONS,
    SplitError,
    assert_no_leakage,
    build_protocol,
    holdout_split,
    rolling_origin_splits,
)

WEEKS = pd.date_range("2010-01-04", periods=100, freq="W-MON")
SERIES = pd.Series(np.arange(100, dtype=float), index=WEEKS)


def test_the_holdout_is_the_last_h_observations_and_nothing_else():
    split = holdout_split(SERIES, horizon=12)

    assert split.horizon == 12
    assert split.train_size == 88
    assert list(split.test_index) == list(WEEKS[-12:])
    assert split.train_index[-1] < split.test_index[0]


def test_every_fold_trains_strictly_before_it_tests():
    """The one property that makes the whole comparison meaningful."""
    for split in rolling_origin_splits(SERIES, horizon=8, folds=4):
        assert split.train_index[-1] < split.test_index[0]
        assert split.train_positions.max() < split.test_positions.min()


def test_cv_folds_never_touch_the_locked_holdout():
    protocol = build_protocol(SERIES, horizon=10, folds=4)
    locked = set(protocol.holdout.test_positions.tolist())

    for split in protocol.folds:
        assert not locked.intersection(split.train_positions.tolist())
        assert not locked.intersection(split.test_positions.tolist())

    assert_no_leakage(protocol.folds, protocol.holdout)   # raises if not


def test_test_windows_do_not_overlap_each_other():
    """Friedman's test treats the folds as repeated measures. Overlapping test
    windows would share actuals between 'independent' measurements and
    overstate the evidence."""
    splits = rolling_origin_splits(SERIES, horizon=8, folds=4)
    seen: set[int] = set()
    for split in splits:
        positions = set(split.test_positions.tolist())
        assert not seen.intersection(positions)
        seen |= positions


def test_the_last_fold_ends_at_the_end_of_the_series():
    """Otherwise the most recent weeks - the ones most like the future - are
    never used for validation."""
    splits = rolling_origin_splits(SERIES, horizon=8, folds=4)
    assert int(splits[-1].test_positions.max()) == len(SERIES) - 1


def test_folds_are_returned_oldest_origin_first():
    splits = rolling_origin_splits(SERIES, horizon=8, folds=4)
    origins = [int(split.test_positions.min()) for split in splits]
    assert origins == sorted(origins)
    assert [split.fold for split in splits] == [1, 2, 3, 4]


def test_an_expanding_window_grows_and_a_sliding_window_does_not():
    expanding = rolling_origin_splits(SERIES, horizon=8, folds=4, style="expanding")
    sliding = rolling_origin_splits(SERIES, horizon=8, folds=4, style="sliding")

    growing = [split.train_size for split in expanding]
    constant = [split.train_size for split in sliding]

    assert growing == sorted(growing) and growing[0] < growing[-1]
    assert len(set(constant)) == 1          # Chu & Zhang's fixed in-sample length
    assert constant[0] == expanding[0].train_size


def test_a_sliding_window_moves_its_start_forward():
    sliding = rolling_origin_splits(SERIES, horizon=8, folds=4, style="sliding")
    starts = [int(split.train_positions.min()) for split in sliding]
    assert starts == sorted(starts) and starts[0] < starts[-1]


def test_asking_for_more_folds_than_the_data_supports_is_refused_with_arithmetic():
    """A silent reduction to two folds would be a protocol change nobody saw."""
    short = SERIES.iloc[:30]
    with pytest.raises(SplitError) as error:
        rolling_origin_splits(short, horizon=12, folds=4)

    message = str(error.value)
    assert "need at least" in message
    assert "30" in message


def test_a_series_shorter_than_the_holdout_is_refused():
    with pytest.raises(SplitError):
        holdout_split(SERIES.iloc[: MIN_TRAIN_OBSERVATIONS + 2], horizon=12)


def test_an_unsorted_series_is_refused_rather_than_sorted():
    """Sorting it here would hide a bug upstream in the trend query."""
    shuffled = SERIES.iloc[::-1]
    with pytest.raises(SplitError) as error:
        holdout_split(shuffled, horizon=12)
    assert "sorted" in str(error.value)


def test_leakage_is_detected_when_a_fold_is_tampered_with():
    """The guard has to fail on a bad protocol, or it proves nothing about a
    good one."""
    protocol = build_protocol(SERIES, horizon=10, folds=3)
    bad = protocol.folds[0]
    tampered = type(bad)(
        fold=bad.fold,
        train_positions=np.arange(0, int(bad.test_positions.max()) + 1),
        test_positions=bad.test_positions,
        train_index=SERIES.index[: int(bad.test_positions.max()) + 1],
        test_index=bad.test_index,
    )

    with pytest.raises(SplitError) as error:
        assert_no_leakage([tampered])
    assert "reaches into the test window" in str(error.value)


def test_a_cv_fold_that_validates_inside_the_holdout_is_detected():
    """The realistic version of this mistake: the fold is internally sound -
    it trains before it tests - but its test window runs past the start of the
    locked hold-out, so model selection would be scoring itself on the final
    exam. The hold-out positions here are 90-99 and the fold tests 85-94."""
    protocol = build_protocol(SERIES, horizon=10, folds=3)
    overrun = type(protocol.folds[0])(
        fold=99,
        train_positions=np.arange(0, 85),
        test_positions=np.arange(85, 95),
        train_index=SERIES.index[:85],
        test_index=SERIES.index[85:95],
    )

    assert_no_leakage([overrun])       # chronologically fine on its own
    with pytest.raises(SplitError) as error:
        assert_no_leakage([overrun], protocol.holdout)
    assert "locked hold-out" in str(error.value)


def test_the_protocol_records_itself_for_the_run_log():
    """A results table without its protocol cannot be checked by anyone else."""
    record = build_protocol(SERIES, horizon=10, folds=4).as_dict()

    assert record["horizon"] == 10
    assert len(record["folds"]) == 4
    assert record["holdout"]["test_end"] == str(WEEKS[-1].date())
    assert record["folds"][0]["train_start"] == str(WEEKS[0].date())
    assert record["notes"]       # the expanding-window deviation is stated
