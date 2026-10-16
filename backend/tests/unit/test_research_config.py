"""The research config is the experiment, so a mistake in it is a mistake in
the experiment.

These tests load `research/run_experiment.py` by path rather than importing it
as a package, because it deliberately lives outside `backend/` - the research
workstream is separate from the application (architecture §4.5), and that
separation is worth keeping even though it costs three lines here.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CLI_PATH = REPO_ROOT / "research" / "run_experiment.py"
CONFIG_PATH = REPO_ROOT / "research" / "configs" / "rq1_forecasting.toml"

pytestmark = pytest.mark.skipif(
    not CLI_PATH.exists(),
    reason="research/ is not present (the backend was copied without it)",
)


def _load_cli():
    spec = importlib.util.spec_from_file_location("rp_run_experiment", CLI_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["rp_run_experiment"] = module
    spec.loader.exec_module(module)
    return module


def _valid_config() -> dict:
    return {
        "meta": {"name": "test"},
        "data": {"source": "csv", "csv_path": "x.csv"},
        "protocol": {
            "horizon": 12, "folds": 3, "season_length": 52,
            "window_style": "expanding", "primary_metric": "WAPE",
        },
        "models": {"include": ["naive", "seasonal_naive", "ets"]},
        "combination": {"rule": "median", "members": ["seasonal_naive", "ets"]},
    }


def test_the_shipped_rq1_config_is_valid():
    """If the config committed to the repository does not validate, nobody can
    reproduce the headline experiment."""
    cli = _load_cli()
    config, digest = cli.load_config(CONFIG_PATH)

    assert len(digest) == 64
    assert config["meta"]["research_question"] == "RQ1"
    assert config["protocol"]["primary_metric"] == "WAPE"


def test_the_config_hash_is_of_the_file_not_the_parsed_values():
    """A comment explaining why a parameter was chosen is part of the declared
    protocol; changing it should be visible."""
    cli = _load_cli()
    _, first = cli.load_config(CONFIG_PATH)
    _, second = cli.load_config(CONFIG_PATH)
    assert first == second


def test_a_valid_config_passes():
    _load_cli().validate_config(_valid_config())


def test_every_problem_is_reported_at_once():
    """One error per run turns a five-minute fix into five rounds of editing."""
    cli = _load_cli()
    broken = _valid_config()
    broken["protocol"]["horizon"] = 0
    broken["protocol"]["window_style"] = "sideways"
    broken["models"]["include"] = ["naive", "prophet"]

    with pytest.raises(cli.ConfigError) as error:
        cli.validate_config(broken)

    message = str(error.value)
    assert "horizon" in message
    assert "window_style" in message
    assert "prophet" in message


def test_a_combination_cannot_average_a_model_that_was_never_fitted():
    cli = _load_cli()
    broken = _valid_config()
    broken["combination"]["members"] = ["seasonal_naive", "fourier"]   # fourier not included

    with pytest.raises(cli.ConfigError) as error:
        cli.validate_config(broken)
    assert "fourier" in str(error.value)
    assert "never fitted" in str(error.value)


def test_a_csv_source_without_a_path_is_refused():
    cli = _load_cli()
    broken = _valid_config()
    broken["data"]["csv_path"] = ""

    with pytest.raises(cli.ConfigError) as error:
        cli.validate_config(broken)
    assert "csv_path" in str(error.value)


def test_an_empty_model_list_is_refused():
    cli = _load_cli()
    broken = _valid_config()
    broken["models"]["include"] = []

    with pytest.raises(cli.ConfigError) as error:
        cli.validate_config(broken)
    assert "nothing to compare" in str(error.value)


def test_a_missing_section_is_named():
    cli = _load_cli()
    broken = _valid_config()
    del broken["protocol"]

    with pytest.raises(cli.ConfigError) as error:
        cli.validate_config(broken)
    assert "[protocol]" in str(error.value)


def test_seasonal_models_get_the_season_length_from_the_protocol():
    """Set in one place. A fourier model fitted with the default 52 while the
    protocol declared 26 would be a silent mismatch."""
    cli = _load_cli()
    config = _valid_config()
    config["models"]["include"] = ["fourier", "naive"]
    config["protocol"]["season_length"] = 26
    config["combination"]["members"] = ["fourier"]

    factories = cli.build_factories(config)

    assert factories["fourier"]().season_length == 26


def test_per_model_params_from_the_config_reach_the_model():
    cli = _load_cli()
    config = _valid_config()
    config["models"]["include"] = ["moving_average"]
    config["models"]["params"] = {"moving_average": {"window": 7}}
    config["combination"]["members"] = []

    assert cli.build_factories(config)["moving_average"]().window == 7
