"""The RQ4 config is the experiment, so a mistake in it is a mistake in the
experiment. Loaded by path because the research workstream lives outside
`backend/` deliberately (architecture §4.5)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CLI_PATH = REPO_ROOT / "research" / "run_insights.py"
CONFIG_PATH = REPO_ROOT / "research" / "configs" / "rq4_insights.toml"

pytestmark = pytest.mark.skipif(
    not CLI_PATH.exists(), reason="research/ is not present"
)


def _load():
    spec = importlib.util.spec_from_file_location("rp_run_insights", CLI_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["rp_run_insights"] = module
    spec.loader.exec_module(module)
    return module


def _valid() -> dict:
    return {
        "meta": {"name": "test"},
        "inputs": {
            "results_directory": "research/results",
            "forecast": "latest:rq1-forecasting-weekly-total",
            "segmentation": "latest:rq2-segmentation-stability",
            "association": "latest:rq3-association-rules",
        },
        "ranking": {"weights": {
            "revenue_at_stake": 0.4, "evidence_weight": 0.4, "corroboration": 0.2,
        }},
    }


def test_the_shipped_rq4_config_is_valid():
    cli = _load()
    config, digest = cli.load_config(CONFIG_PATH)
    assert len(digest) == 64
    assert config["meta"]["research_question"] == "RQ4"


def test_the_shipped_config_declares_every_ranking_weight():
    """A weight left to a default would not appear in the committed file, so it
    would not be covered by the config hash."""
    config, _ = _load().load_config(CONFIG_PATH)
    weights = config["ranking"]["weights"]
    assert set(weights) == {"revenue_at_stake", "evidence_weight", "corroboration"}


def test_the_shipped_config_fixes_the_session_protocol_before_any_participant():
    config, _ = _load().load_config(CONFIG_PATH)
    session = config["session"]
    assert "counterbalanced" in session["design"]
    assert len(session["measures"]) >= 3


def test_a_valid_config_passes():
    _load().validate_config(_valid())


def test_a_missing_section_is_reported():
    cli = _load()
    broken = _valid()
    del broken["ranking"]
    with pytest.raises(cli.ConfigError, match=r"\[ranking\]"):
        cli.validate_config(broken)


def test_a_single_engine_is_refused():
    """Neither condition means anything with one engine: there is nothing to
    integrate and nothing to isolate."""
    cli = _load()
    broken = _valid()
    broken["inputs"]["segmentation"] = ""
    broken["inputs"]["association"] = ""
    with pytest.raises(cli.ConfigError) as error:
        cli.validate_config(broken)
    assert "Fewer than two engines" in str(error.value)


def test_no_engines_at_all_is_refused():
    cli = _load()
    broken = _valid()
    broken["inputs"] = {"results_directory": "research/results"}
    with pytest.raises(cli.ConfigError, match="No input runs named"):
        cli.validate_config(broken)


def test_an_incomplete_weight_set_is_refused_by_the_config_check():
    cli = _load()
    broken = _valid()
    del broken["ranking"]["weights"]["corroboration"]
    with pytest.raises(cli.ConfigError, match="Missing weight"):
        cli.validate_config(broken)


def test_an_unknown_weight_is_refused():
    """Guards against reintroducing the margin component the dataset cannot
    support without noticing."""
    cli = _load()
    broken = _valid()
    broken["ranking"]["weights"]["margin_contribution"] = 0.3
    with pytest.raises(cli.ConfigError, match="Unknown"):
        cli.validate_config(broken)


def test_every_problem_is_reported_at_once():
    cli = _load()
    broken = _valid()
    broken["inputs"] = {"results_directory": "research/results"}
    broken["ranking"]["weights"] = {"revenue_at_stake": 1.0}
    with pytest.raises(cli.ConfigError) as error:
        cli.validate_config(broken)
    assert str(error.value).count("- ") >= 2
