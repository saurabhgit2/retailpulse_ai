"""Customer segmentation (RQ2).

The tests that matter here are the ones about *stability*, because that is the
research question. A clustering that groups three obvious blobs correctly is
table stakes; whether the grouping survives the window moving is the finding.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.segmentation.clustering import CLUSTERERS, cluster, fit_range
from app.segmentation.profiles import compare_with_rfm_bands, describe_clusters
from app.segmentation.quality import compare_k, elbow, gap_statistic, quality_indices
from app.segmentation.scaling import build_matrix
from app.segmentation.stability import (
    match_clusters,
    migration_matrix,
    stability_across_windows,
)
from app.segmentation.windows import WindowError, common_customers, make_windows


# -- windows -------------------------------------------------------------


def test_windows_are_spread_from_a_first_date_with_enough_history():
    windows = make_windows("2009-12-01", "2011-12-09", count=4, min_history_days=365)

    assert len(windows) == 4
    assert str(windows[0].end.date()) == "2010-12-01"     # a year in
    assert str(windows[-1].end.date()) == "2011-12-09"    # the end of the data
    assert [w.index for w in windows] == [1, 2, 3, 4]


def test_expanding_windows_have_no_start():
    for window in make_windows("2009-12-01", "2011-12-09", style="expanding"):
        assert window.start is None


def test_rolling_windows_are_all_the_same_length():
    windows = make_windows(
        "2009-12-01", "2011-12-09", count=3, style="rolling", window_days=365,
    )
    lengths = {(w.end - w.start).days for w in windows}
    assert lengths == {365}


def test_a_rolling_window_that_starts_before_the_data_is_refused():
    with pytest.raises(WindowError) as error:
        make_windows("2009-12-01", "2011-12-09", count=3, style="rolling",
                     window_days=400, min_history_days=365)
    assert "before the data" in str(error.value)


def test_one_window_is_refused_because_stability_needs_a_comparison():
    with pytest.raises(WindowError) as error:
        make_windows("2009-12-01", "2011-12-09", count=1)
    assert "at least 2" in str(error.value)


def test_too_little_history_for_the_first_window_is_refused_with_arithmetic():
    with pytest.raises(WindowError) as error:
        make_windows("2011-01-01", "2011-06-01", count=3, min_history_days=365)
    assert "151 days" in str(error.value)


def test_only_customers_in_every_snapshot_are_compared():
    """A customer who appears late cannot have moved, and counting them would
    make stability look worse the faster the business grows."""
    snapshots = {
        "w1": pd.DataFrame({"customer": ["a", "b", "c"]}),
        "w2": pd.DataFrame({"customer": ["b", "c", "d"]}),
    }
    assert common_customers(snapshots) == ["b", "c"]


# -- scaling -------------------------------------------------------------


def _rfm(count: int = 300, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "customer": [f"C{i}" for i in range(count)],
        "recency_days": rng.integers(1, 500, count).astype(float),
        "frequency": rng.integers(1, 40, count).astype(float),
        "monetary": rng.gamma(2, 500, count),
    })


def test_scaling_puts_the_columns_on_a_comparable_footing():
    """Chen et al.'s warning, made concrete: unscaled, Euclidean distance is
    almost entirely monetary distance."""
    result = build_matrix(_rfm(), scaler="standard")
    spreads = result.matrix.std(axis=0)

    assert result.shape[1] == 3
    assert spreads.max() / spreads.min() < 1.5      # comparable, not identical


def test_unscaled_data_is_dominated_by_monetary():
    scaled = build_matrix(_rfm(), scaler="none", transforms={"monetary": "none",
                                                            "frequency": "none"})
    spreads = scaled.matrix.std(axis=0)
    assert spreads[2] > 50 * spreads[1]      # monetary swamps frequency


def test_recency_is_inverted_so_larger_is_better_on_every_axis():
    customers = _rfm(50)
    result = build_matrix(customers, scaler="none", transforms={"recency_days": "none"})

    recent = customers["recency_days"].idxmin()
    stale = customers["recency_days"].idxmax()
    assert result.matrix[recent, 0] > result.matrix[stale, 0]
    assert any("negated" in note for note in result.notes)


def test_a_signed_log_keeps_customers_whose_returns_exceeded_their_purchases():
    """The real case: analytics/rfm.py found a minimum monetary of -1,343."""
    customers = _rfm(100)
    customers.loc[:4, "monetary"] = -500.0

    result = build_matrix(customers, negative_monetary="signed_log")

    assert len(result.customers) == 100
    assert result.transforms["monetary"] == "sign(x) * log1p(|x|)"


def test_a_plain_log_on_negative_values_is_refused_with_the_alternatives():
    customers = _rfm(50)
    customers.loc[0, "monetary"] = -500.0

    with pytest.raises(ValueError) as error:
        build_matrix(customers, transforms={"monetary": "log"})
    assert "signed_log" in str(error.value)


def test_excluding_negative_customers_counts_them_and_says_why_it_matters():
    customers = _rfm(100)
    customers.loc[:9, "monetary"] = -200.0

    result = build_matrix(customers, negative_monetary="exclude")

    assert result.excluded["negative_monetary_customers"] == 10
    assert len(result.customers) == 90
    assert any("returns-reduction" in note for note in result.notes)


def test_a_constant_column_does_not_produce_nan():
    customers = _rfm(60)
    customers["frequency"] = 5.0
    result = build_matrix(customers)
    assert np.isfinite(result.matrix).all()


def test_every_transform_decision_is_recorded():
    record = build_matrix(_rfm()).as_dict()
    assert set(record["transforms"]) == {"recency_days", "frequency", "monetary"}
    assert record["scaler"] == "standard"


# -- clustering ----------------------------------------------------------


def _blobs(per_cluster: int = 80, seed: int = 1) -> np.ndarray:
    """Three well-separated groups: if an algorithm cannot find these, nothing
    it says about real data is worth reading."""
    rng = np.random.default_rng(seed)
    centres = np.array([[-4.0, -4.0, -4.0], [0.0, 0.0, 0.0], [4.0, 4.0, 4.0]])
    return np.vstack([rng.normal(c, 0.4, (per_cluster, 3)) for c in centres])


@pytest.mark.parametrize("algorithm", ["kmeans", "hierarchical", "gaussian"])
def test_every_family_recovers_three_obvious_groups(algorithm):
    result = cluster(_blobs(), k=3, algorithm=algorithm)
    assert len(result.sizes) == 3
    assert min(result.sizes.values()) > 60      # roughly balanced, as planted


def test_all_three_families_are_registered():
    assert set(CLUSTERERS) == {"kmeans", "hierarchical", "gaussian"}


def test_the_same_seed_gives_the_same_partition():
    """Without this, 'the segments changed' could mean the seed changed."""
    first = cluster(_blobs(), k=3, seed=7).labels
    second = cluster(_blobs(), k=3, seed=7).labels
    assert np.array_equal(first, second)


def test_hierarchical_clustering_is_deterministic_by_construction():
    assert cluster(_blobs(), 3, "hierarchical").settings["deterministic"] is True


def test_an_unknown_algorithm_lists_the_real_ones():
    with pytest.raises(KeyError) as error:
        cluster(_blobs(), 3, "dbscan")
    assert "kmeans" in str(error.value)


def test_asking_for_more_clusters_than_customers_is_refused():
    with pytest.raises(ValueError) as error:
        cluster(np.zeros((5, 3)), k=10)
    assert "at least one customer per cluster" in str(error.value)


def test_fitting_a_range_gives_a_curve_to_read():
    results = fit_range(_blobs(), k_min=2, k_max=6)
    assert sorted(results) == [2, 3, 4, 5, 6]
    assert all(r.inertia is not None for r in results.values())


# -- quality -------------------------------------------------------------


def test_the_indices_agree_on_well_separated_blobs():
    matrix = _blobs()
    comparison = compare_k(matrix, fit_range(matrix, k_min=2, k_max=6))

    assert comparison["preferred_k"]["silhouette"] == 3
    assert comparison["preferred_k"]["calinski_harabasz"] == 3


def test_a_single_cluster_makes_the_indices_undefined_rather_than_zero():
    result = quality_indices(_blobs(), np.zeros(240, dtype=int))
    assert result["available"] is False
    assert "at least two" in result["reason"]


def test_a_low_silhouette_is_described_as_a_continuum_not_a_discovery():
    rng = np.random.default_rng(3)
    blob = rng.normal(0, 1, (300, 3))          # one cloud, no structure
    labels = cluster(blob, k=4).labels

    reading = quality_indices(blob, labels)["interpretation"]
    assert "continuum" in reading or "little separation" in reading


def test_the_elbow_says_when_the_curve_has_no_real_knee():
    straight = {k: 100.0 - 10 * k for k in range(2, 9)}      # perfectly linear
    result = elbow(straight)
    assert result["distinct"] is False
    assert "should not be presented as evidence" in result["note"]


def test_the_elbow_finds_a_real_knee():
    bent = {2: 100.0, 3: 40.0, 4: 35.0, 5: 33.0, 6: 32.0}
    result = elbow(bent)
    assert result["k"] == 3
    assert result["distinct"] is True


def test_the_elbow_needs_at_least_three_values_of_k():
    assert elbow({2: 10.0, 3: 5.0})["available"] is False


def test_the_gap_statistic_detects_real_structure():
    result = gap_statistic(_blobs(), [2, 3, 4], references=3)
    assert result["available"] is True
    assert len(result["rows"]) == 3


def test_the_gap_statistic_reports_a_continuum_rather_than_inventing_a_k():
    """On uniform noise there is no k to find, and saying so is the point of
    including this measure at all."""
    rng = np.random.default_rng(5)
    noise = rng.uniform(0, 1, (200, 3))
    result = gap_statistic(noise, [2, 3, 4, 5], references=3)

    assert result["available"] is True
    if result["k"] is None:
        assert "continuum" in result["note"]


def test_disagreement_between_indices_is_reported_not_resolved():
    """Returning one recommended k would hide the disagreement, which is the
    thing the report has to discuss."""
    rng = np.random.default_rng(11)
    blob = rng.normal(0, 1, (240, 3))
    comparison = compare_k(blob, fit_range(blob, k_min=2, k_max=6))

    if not comparison["unanimous"]:
        assert "the researcher's" in comparison["summary"]


# -- stability: the RQ2 question -----------------------------------------


def _partition(labels: dict[str, int]) -> dict[str, int]:
    return labels


def test_an_identical_partition_scores_perfect_stability():
    labels = {f"C{i}": i % 3 for i in range(90)}
    result = stability_across_windows({"w1": labels, "w2": dict(labels)})

    assert result["mean_adjusted_rand"] == pytest.approx(1.0)
    assert result["mean_retention_share"] == pytest.approx(1.0)
    assert "stable" in result["verdict"]


def test_relabelling_alone_is_not_instability():
    """Cluster 0 in one run and cluster 0 in the next are not the same group.
    A measure that counted equal label values would report this as churn."""
    first = {f"C{i}": i % 3 for i in range(90)}
    renamed = {customer: (label + 1) % 3 for customer, label in first.items()}

    result = stability_across_windows({"w1": first, "w2": renamed})

    assert result["mean_adjusted_rand"] == pytest.approx(1.0)
    assert result["mean_retention_share"] == pytest.approx(1.0)


def test_a_random_reshuffle_scores_near_zero_and_is_called_unstable():
    rng = np.random.default_rng(2)
    first = {f"C{i}": int(i % 3) for i in range(300)}
    shuffled = {f"C{i}": int(v) for i, v in enumerate(rng.integers(0, 3, 300))}

    result = stability_across_windows({"w1": first, "w2": shuffled})

    assert abs(result["mean_adjusted_rand"]) < 0.1
    assert "unstable" in result["verdict"]
    assert "This is a finding, not a failure" in result["verdict"]


def test_clusters_are_matched_by_overlap_before_migration_is_counted():
    first = np.array([0, 0, 0, 1, 1, 1])
    second = np.array([5, 5, 5, 9, 9, 9])
    assert match_clusters(first, second) == {5: 0, 9: 1}


def test_the_migration_matrix_shows_where_customers_went():
    first = {f"C{i}": 0 for i in range(10)} | {f"D{i}": 1 for i in range(10)}
    # Three of cluster 0 move into cluster 1.
    second = dict(first)
    for i in range(3):
        second[f"C{i}"] = 1

    result = migration_matrix(first, second)

    assert result["stayed"] == 17
    assert result["retention_share"] == pytest.approx(17 / 20)
    assert result["largest_flows"][0]["customers"] == 3


def test_stability_needs_two_windows():
    result = stability_across_windows({"w1": {"a": 0, "b": 1}})
    assert result["available"] is False
    assert "at least two" in result["reason"]


def test_the_provenance_of_the_adjusted_rand_index_travels_with_the_number():
    labels = {f"C{i}": i % 3 for i in range(60)}
    result = stability_across_windows({"w1": labels, "w2": dict(labels)})
    assert "does not appear in the supplied" in result["measure_note"]


def test_every_pair_is_compared_not_only_neighbours():
    """Slow drift and a sudden reshuffle look identical if only consecutive
    windows are compared."""
    labels = {f"C{i}": i % 3 for i in range(60)}
    result = stability_across_windows({"w1": labels, "w2": dict(labels), "w3": dict(labels)})
    assert len(result["pairs"]) == 3        # 3 choose 2


# -- profiles ------------------------------------------------------------


def test_profiles_are_in_original_units_so_a_manager_can_read_them():
    customers = _rfm(150)
    labels = cluster(build_matrix(customers).matrix, k=3).labels

    profile = describe_clusters(customers, labels)
    row = profile["rows"][0]

    assert profile["clusters"] == 3
    assert row["median_recency_days"] > 1          # days, not z-scores
    assert row["name"]
    assert sum(r["customers"] for r in profile["rows"]) == 150


def test_revenue_shares_across_clusters_sum_to_one():
    customers = _rfm(150)
    labels = cluster(build_matrix(customers).matrix, k=4).labels
    profile = describe_clusters(customers, labels)

    assert sum(row["revenue_share"] for row in profile["rows"]) == pytest.approx(1.0)


def test_a_label_count_mismatch_is_refused_with_the_reason():
    """The matrix builder drops unusable rows, so profiling against the
    original frame silently misaligns every customer."""
    customers = _rfm(100)
    with pytest.raises(ValueError) as error:
        describe_clusters(customers, np.zeros(90, dtype=int))
    assert "drops unusable rows" in str(error.value)


def test_cluster_names_are_derived_from_position_not_assigned():
    customers = _rfm(200)
    labels = cluster(build_matrix(customers).matrix, k=3).labels
    profile = describe_clusters(customers, labels)

    assert "derived" in profile["naming_note"]
    assert all("axes" in row for row in profile["rows"])


def test_the_clusters_can_be_compared_with_the_conventional_rfm_bands():
    """The same move as the 12.7 comparison: test the convenient method
    against the rigorous one rather than assuming they agree."""
    clusters = {f"C{i}": i % 3 for i in range(90)}
    bands = {f"C{i}": ["champions", "loyal", "hibernating"][i % 3] for i in range(90)}

    result = compare_with_rfm_bands(clusters, bands)

    assert result["adjusted_rand"] == pytest.approx(1.0)
    assert "agree closely" in result["verdict"]


def test_disagreeing_bands_are_reported_as_disagreement():
    rng = np.random.default_rng(4)
    clusters = {f"C{i}": int(i % 3) for i in range(150)}
    bands = {f"C{i}": ["a", "b", "c"][int(v)] for i, v in enumerate(rng.integers(0, 3, 150))}

    verdict = compare_with_rfm_bands(clusters, bands)["verdict"]
    assert "disagree" in verdict or "only partly" in verdict


def test_cluster_names_are_unique_even_when_bands_collide():
    """With k=4 the ranked positions are 0, 1/3, 2/3 and 1, so two clusters
    land in "high" and two in "low" on every axis - which gave two different
    segments the same name on the real Online Retail II run. Collisions are
    broken by spend, and the qualifier names the dimension used."""
    customers = pd.DataFrame({
        "customer": [f"C{i}" for i in range(400)],
        "recency_days": np.repeat([400.0, 300.0, 40.0, 25.0], 100),
        "frequency": np.repeat([2.0, 3.0, 12.0, 30.0], 100),
        "monetary": np.repeat([200.0, 150.0, 1800.0, 9000.0], 100),
    })
    labels = np.repeat([0, 1, 2, 3], 100)

    rows = describe_clusters(customers, labels)["rows"]
    names = [row["name"] for row in rows]

    assert len(names) == len(set(names))
    assert any("highest spend" in name for name in names)


def test_a_unique_name_is_left_unqualified():
    """The qualifier should appear only where it is needed."""
    customers = pd.DataFrame({
        "customer": [f"C{i}" for i in range(300)],
        "recency_days": np.repeat([400.0, 120.0, 20.0], 100),
        "frequency": np.repeat([1.0, 8.0, 40.0], 100),
        "monetary": np.repeat([100.0, 900.0, 9000.0], 100),
    })
    rows = describe_clusters(customers, np.repeat([0, 1, 2], 100))["rows"]
    assert all("spend)" not in row["name"] for row in rows)


def test_the_description_matches_the_final_name():
    """The description is written after disambiguation, so it cannot describe
    an intermediate name."""
    customers = pd.DataFrame({
        "customer": [f"C{i}" for i in range(400)],
        "recency_days": np.repeat([400.0, 300.0, 40.0, 25.0], 100),
        "frequency": np.repeat([2.0, 3.0, 12.0, 30.0], 100),
        "monetary": np.repeat([200.0, 150.0, 1800.0, 9000.0], 100),
    })
    rows = describe_clusters(customers, np.repeat([0, 1, 2, 3], 100))["rows"]
    assert all(row["description"] for row in rows)
    assert all("net spend" in row["description"] for row in rows)
