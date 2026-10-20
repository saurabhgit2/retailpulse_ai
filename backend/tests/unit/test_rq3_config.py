"""The RQ3 config is the experiment, so a mistake in it is a mistake in the
experiment. Loaded by path because the research workstream lives outside
`backend/` deliberately (architecture §4.5)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CLI_PATH = REPO_ROOT / "research" / "run_association.py"
CONFIG_PATH = REPO_ROOT / "research" / "configs" / "rq3_association.toml"

pytestmark = pytest.mark.skipif(
    not CLI_PATH.exists(), reason="research/ is not present"
)


def _load():
    spec = importlib.util.spec_from_file_location("rp_run_association", CLI_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["rp_run_association"] = module
    spec.loader.exec_module(module)
    return module


def _valid() -> dict:
    return {
        "meta": {"name": "test"},
        "data": {"source": "database", "dataset_id": ""},
        "mining": {
            "min_support": 0.01,
            "min_confidence": 0.2,
            "min_lift": 1.0,
            "max_length": 3,
            "max_consequent_length": 1,
        },
        "validation": {"holdout_fraction": 0.25, "min_support_count": 5},
    }


def test_the_shipped_rq3_config_is_valid():
    cli = _load()
    config, digest = cli.load_config(CONFIG_PATH)
    assert len(digest) == 64
    assert config["meta"]["research_question"] == "RQ3"
    assert 0 < config["mining"]["min_support"] <= 1


def test_the_shipped_config_declares_its_thresholds_before_the_run():
    """Support, confidence and the hold-out fraction must all be present.

    A threshold left to a default would not appear in the committed file, so
    it would not be covered by the config hash and two runs with different
    thresholds could share one hash.
    """
    config, _ = _load().load_config(CONFIG_PATH)
    assert "min_support" in config["mining"]
    assert "min_confidence" in config["mining"]
    assert "holdout_fraction" in config["validation"]
    assert "alpha" in config["significance"]


def test_a_valid_config_passes():
    _load().validate_config(_valid())


def test_a_missing_section_is_reported():
    cli = _load()
    broken = _valid()
    del broken["mining"]
    with pytest.raises(cli.ConfigError, match=r"\[mining\]"):
        cli.validate_config(broken)


def test_an_impossible_support_is_refused():
    cli = _load()
    for value in (0, 1.5, -0.1):
        broken = _valid()
        broken["mining"]["min_support"] = value
        with pytest.raises(cli.ConfigError, match="min_support"):
            cli.validate_config(broken)


def test_a_support_too_high_for_long_tail_retail_is_refused_with_a_reason():
    """0.2 on this data returns nothing, and a run that returns nothing because
    of a typo looks exactly like a finding."""
    cli = _load()
    broken = _valid()
    broken["mining"]["min_support"] = 0.5
    with pytest.raises(cli.ConfigError) as error:
        cli.validate_config(broken)
    assert "long-tail" in str(error.value)


def test_a_max_length_below_two_is_refused():
    """A rule needs an antecedent and a consequent."""
    cli = _load()
    broken = _valid()
    broken["mining"]["max_length"] = 1
    with pytest.raises(cli.ConfigError, match="max_length"):
        cli.validate_config(broken)


def test_a_holdout_larger_than_the_mining_window_is_refused():
    """The rules would be weak for reasons unrelated to whether they generalise."""
    cli = _load()
    broken = _valid()
    broken["validation"]["holdout_fraction"] = 0.8
    with pytest.raises(cli.ConfigError) as error:
        cli.validate_config(broken)
    assert "less data to mine on" in str(error.value)


def test_a_csv_source_is_refused_with_the_reason():
    """Baskets depend on the pipeline's cleaning rules, so a CSV shortcut would
    not give the same answer."""
    cli = _load()
    broken = _valid()
    broken["data"]["source"] = "csv"
    with pytest.raises(cli.ConfigError, match="database"):
        cli.validate_config(broken)


def test_every_problem_is_reported_at_once():
    """One error per run wastes a cycle each time."""
    cli = _load()
    broken = _valid()
    broken["mining"]["min_support"] = 2.0
    broken["mining"]["max_length"] = 1
    broken["validation"]["holdout_fraction"] = 0.9
    with pytest.raises(cli.ConfigError) as error:
        cli.validate_config(broken)
    message = str(error.value)
    assert message.count("- ") >= 3
