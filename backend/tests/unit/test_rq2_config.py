"""The RQ2 config is the experiment, so a mistake in it is a mistake in the
experiment. Loaded by path because the research workstream lives outside
`backend/` deliberately (architecture §4.5)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CLI_PATH = REPO_ROOT / "research" / "run_segmentation.py"
CONFIG_PATH = REPO_ROOT / "research" / "configs" / "rq2_segmentation.toml"

pytestmark = pytest.mark.skipif(
    not CLI_PATH.exists(), reason="research/ is not present"
)


def _load():
    spec = importlib.util.spec_from_file_location("rp_run_segmentation", CLI_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["rp_run_segmentation"] = module
    spec.loader.exec_module(module)
    return module


def _valid() -> dict:
    return {
        "meta": {"name": "test"},
        "data": {"source": "database", "dataset_id": ""},
        "windows": {"count": 4, "style": "expanding", "min_history_days": 365},
        "clustering": {"algorithms": ["kmeans"], "k_min": 2, "k_max": 8, "k": 4},
    }


def test_the_shipped_rq2_config_is_valid():
    cli = _load()
    config, digest = cli.load_config(CONFIG_PATH)
    assert len(digest) == 64
    assert config["meta"]["research_question"] == "RQ2"
    assert config["clustering"]["k"] >= 2


def test_a_valid_config_passes():
    _load().validate_config(_valid())


def test_a_k_outside_the_fitted_range_is_refused():
    """Otherwise the quality indices say nothing about the k actually used."""
    cli = _load()
    broken = _valid()
    broken["clustering"]["k"] = 12
    with pytest.raises(cli.ConfigError) as error:
        cli.validate_config(broken)
    assert "outside the fitted range" in str(error.value)


def test_one_window_is_refused():
    cli = _load()
    broken = _valid()
    broken["windows"]["count"] = 1
    with pytest.raises(cli.ConfigError) as error:
        cli.validate_config(broken)
    assert "stability needs a comparison" in str(error.value)


def test_an_unknown_algorithm_lists_the_real_ones():
    cli = _load()
    broken = _valid()
    broken["clustering"]["algorithms"] = ["dbscan"]
    with pytest.raises(cli.ConfigError) as error:
        cli.validate_config(broken)
    assert "kmeans" in str(error.value)


def test_a_csv_source_is_refused_with_the_reason():
    """Customer identity depends on the pipeline's cleaning rules, so there is
    no shortcut around the stored dataset."""
    cli = _load()
    broken = _valid()
    broken["data"]["source"] = "csv"
    with pytest.raises(cli.ConfigError) as error:
        cli.validate_config(broken)
    assert "cleaning rules" in str(error.value)


def test_every_problem_is_reported_at_once():
    cli = _load()
    broken = _valid()
    broken["windows"]["count"] = 1
    broken["windows"]["style"] = "sideways"
    broken["clustering"]["algorithms"] = ["dbscan"]

    with pytest.raises(cli.ConfigError) as error:
        cli.validate_config(broken)
    message = str(error.value)
    assert "count" in message and "style" in message and "dbscan" in message
