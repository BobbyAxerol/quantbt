"""MLR03-T01..04: bounded synthetic math, clocks, grouping and denied rights."""

from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from tools.meta_model_research.feasibility import (
    HEAD_VERSION,
    MAX_PAIRS,
    MAX_ROWS,
    VERSION,
    Diagnostic,
    FeasibilityError,
    Pair,
    PrefixRequest,
    Query,
    RankScores,
    SourceVersions,
    SyntheticMagnitudeHead,
    SyntheticRow,
    authorize_use,
    fit_preprocessing,
    magnitudes,
    pair_accuracy,
    pair_roster,
    permitted_rows,
    run_feasibility,
)


def rectangle(family="A", group="train", origin=0, *, role="train", scale=1.0):
    query = Query(family, group, origin, f"{family}:{origin}")
    return tuple(
        SyntheticRow(
            query, str(i), (x * scale, z * scale), x, origin, origin, origin, role
        )
        for i, (x, z) in enumerate(
            ((-1.0, -10.0), (-1.0, 10.0), (1.0, -10.0), (1.0, 10.0))
        )
    )


@pytest.fixture
def request_data():
    rows = rectangle() + rectangle("B", "held", scale=2.0)
    rows += rectangle(origin=3, role="evaluation", scale=3.0)
    return PrefixRequest(rows, 2, ("held",))


def test_compact_callable_has_no_economic_claim_or_activation():
    result = run_feasibility()
    assert result == run_feasibility()
    assert result["version"] == VERSION and result["status"] == "PASS"
    assert result["scope"] == "synthetic-only" and all(result["controls"].values())
    assert result["disposition"] == "DEFER_NEW_FAMILY"
    assert result["financial_calls"] == result["private_outcomes_read"] == 0
    assert result["model_screen"] is result["auto_activation"] is False
    assert result["economic_improvement"] is None
    assert result["fit_rows"] == result["pairs"] == 4
    assert result["numeric_threads"] == 1
    assert len(json.dumps(result, allow_nan=False)) < 3000


def test_preprocessing_has_independent_rectangle_oracle(request_data):
    fit = fit_preprocessing(request_data)
    # E[x]=E[z]=0; population covariance diag(1,100), no cross moment.
    assert fit.mean == (0.0, 0.0)
    np.testing.assert_allclose(np.abs(fit.axis), (0.0, 1.0), atol=1e-14)
    assert fit.variance_ratio == pytest.approx(100 / 101, abs=1e-14)
    np.testing.assert_allclose(fit.cluster_centers, (-10.0, 10.0), atol=1e-13)
    assert fit.fit_refs == tuple(("A:0", str(i)) for i in range(4))
    projected = fit.transform(rectangle())
    assert projected.clusters[0] == projected.clusters[2]
    assert projected.clusters[1] == projected.clusters[3]
    assert projected.clusters[0] != projected.clusters[1]
    assert deepcopy(fit) == fit
    assert deepcopy(fit).transform(rectangle()) == projected


def test_future_and_heldout_mutations_cannot_change_fit(request_data):
    first = fit_preprocessing(request_data)
    rows = tuple(
        replace(r, features=(999.0, -888.0), relevance=777.0)
        if r.query.related_group == "held" or r.role == "evaluation"
        else r
        for r in request_data.rows
    )
    other = fit_preprocessing(replace(request_data, rows=rows))
    assert first == other
    assert first.transform(rectangle()) == other.transform(rectangle())
    # Transforming hostile future data must not mutate a learned object.
    first.transform(rows[-4:])
    assert first == fit_preprocessing(request_data)


def test_allowed_past_positive_control_and_target_independence(request_data):
    first = fit_preprocessing(request_data)
    rows = (replace(request_data.rows[0], features=(3.0, -10.0)),) + request_data.rows[
        1:
    ]
    changed = fit_preprocessing(replace(request_data, rows=rows))
    assert changed.mean == (1.0, 0.0)
    assert changed.fit_id != first.fit_id
    relabeled = tuple(replace(r, relevance=-r.relevance) for r in request_data.rows)
    assert fit_preprocessing(replace(request_data, rows=relabeled)) == first


@pytest.mark.parametrize(
    "field", ["feature_available_at", "label_available_at", "revision_available_at"]
)
def test_exact_prefix_availability_and_revisions(request_data, field):
    train = rectangle()
    fields = {field: 2}
    if field == "label_available_at":
        fields["revision_available_at"] = 2
    delayed = tuple(replace(r, **fields) for r in rectangle("late", "train", 1))
    request = replace(request_data, rows=train + delayed)
    assert permitted_rows(request) == train
    assert fit_preprocessing(request).fit_refs == tuple(
        ("A:0", str(i)) for i in range(4)
    )
    earlier = tuple(replace(r, **{field: 1}) for r in delayed)
    if field == "label_available_at":
        earlier = tuple(replace(r, revision_available_at=1) for r in earlier)
    assert len(permitted_rows(replace(request, rows=train + earlier))) == 8


def test_future_train_role_and_past_evaluation_role_are_not_fit(request_data):
    rows = rectangle() + rectangle("future", "train", 2)
    rows += rectangle("past-eval", "train", 0, role="evaluation")
    assert permitted_rows(replace(request_data, rows=rows)) == rectangle()


def test_sibling_group_exclusion_not_family_name_exclusion(request_data):
    sibling = rectangle("sibling", "held", 0)
    request = replace(request_data, rows=request_data.rows + sibling)
    assert permitted_rows(request) == rectangle()
    first = fit_preprocessing(request)
    other = fit_preprocessing(replace(request, rows=tuple(reversed(request.rows))))
    assert first == other
    assert first.fit_id != fit_preprocessing(replace(request, cutoff=3)).fit_id


def test_query_pairs_are_exact_and_expected_not_cross_origin():
    rows = rectangle() + rectangle(origin=1)
    pairs = pair_roster(rows, cap=MAX_PAIRS)
    expected_ids = (("2", "0"), ("3", "0"), ("2", "1"), ("3", "1"))
    assert [
        (p.better.query.origin, p.better.candidate_id, p.worse.candidate_id)
        for p in pairs
    ] == [(origin, a, b) for origin in (0, 1) for a, b in expected_ids]
    assert all(p.better.query == p.worse.query for p in pairs)
    assert pair_roster(tuple(reversed(rows)), cap=MAX_PAIRS) == pairs
    assert pair_accuracy(pairs, (1.0, 0.0)) == 1.0
    assert pair_accuracy(pairs, (-1.0, 0.0)) == 0.0
    assert pair_accuracy(pairs, (0.0, 1.0)) == 0.5


def test_tiny_pair_direction_transfers_and_balanced_noise_is_no_skill():
    train = pair_roster(rectangle())
    matrix = [
        [a - b for a, b in zip(p.better.features, p.worse.features)] for p in train
    ]
    target = [p.better.relevance - p.worse.relevance for p in train]
    # These are fixed algebraic controls, not a model/configuration tournament.
    from threadpoolctl import threadpool_limits

    with threadpool_limits(limits=1):
        fitted = tuple(map(float, np.linalg.lstsq(matrix, target, rcond=None)[0]))
    np.testing.assert_allclose(fitted, (1.0, 0.0), atol=1e-14)
    held = pair_roster(rectangle("new-synthetic-family", "held", 3, scale=7.0))
    assert pair_accuracy(held, fitted) == 1.0
    assert pair_accuracy(held, (0.0, 1.0)) == 0.5
    assert pair_accuracy(held, (0.0, 0.0)) == 0.5


def test_balanced_uninformative_labels_cannot_be_predicted_from_features():
    noise = tuple(
        replace(r, candidate_id=f"{r.candidate_id}:{label}", relevance=float(label))
        for r in rectangle()
        for label in (-1, 1)
    )
    pairs = pair_roster(noise, cap=MAX_PAIRS)
    assert len(pairs) == MAX_PAIRS
    for direction in ((1.0, 0.0), (0.0, 1.0), (3.0, -7.0), (0.0, 0.0)):
        assert pair_accuracy(pairs, direction) == 0.5


def test_served_transform_preserves_both_centering_steps(request_data):
    from sklearn.cluster import KMeans
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler
    from threadpoolctl import threadpool_limits

    rows = tuple(
        replace(r, features=xy)
        for r, xy in zip(
            rectangle(),
            ((12345.11, 0.7), (12346.02, 0.3), (12347.31, 0.13), (12349.27, 0.51)),
        )
    )
    fit = fit_preprocessing(replace(request_data, rows=rows))
    # Exercise the actual served boundary against independent library owners.
    with threadpool_limits(limits=1):
        center = StandardScaler(with_std=False).fit([r.features for r in rows])
        x = center.transform([r.features for r in rows])
        pca = PCA(n_components=1, svd_solver="full").fit(x)
        expected = pca.transform(x).ravel()
        cluster = KMeans(
            n_clusters=2,
            init=np.array([[expected.min()], [expected.max()]]),
            n_init=1,
            max_iter=20,
            random_state=731,
            algorithm="lloyd",
        ).fit(expected[:, None])
    actual = fit.transform(rows)
    np.testing.assert_allclose(actual.projections, expected, rtol=0, atol=1e-14)
    for i in range(4):
        for j in range(4):
            assert (actual.clusters[i] == actual.clusters[j]) == (
                cluster.labels_[i] == cluster.labels_[j]
            )


def test_pair_cap_is_applied_before_full_pair_materialization(monkeypatch):
    import tools.meta_model_research.feasibility as module

    query = Query("A", "train", 0, "A:0")
    rows = tuple(
        SyntheticRow(query, f"{i:02}", (float(i), 1.0), float(i), 0, 0, 0)
        for i in range(MAX_ROWS)
    )
    original = module.combinations
    visited = []

    def bounded(values, count):
        for pair in original(values, count):
            visited.append(1)
            assert len(visited) <= 3
            yield pair

    monkeypatch.setattr(module, "combinations", bounded)
    assert len(pair_roster(rows, cap=3)) == len(visited) == 3


@pytest.mark.parametrize("cap", [0, -1, MAX_PAIRS + 1, True, 1.5])
def test_pair_limits_fail_closed(cap):
    with pytest.raises(FeasibilityError, match="PAIR_LIMIT"):
        pair_roster(rectangle(), cap=cap)


def test_tied_relevance_is_not_an_invented_preference():
    rows = tuple(replace(r, relevance=0.0) for r in rectangle())
    assert pair_roster(rows) == ()
    assert pair_accuracy((), (1.0, 0.0)) is None


@pytest.mark.parametrize(
    "case",
    ["duplicate", "split-origin", "merged-origins", "sibling-drift", "mixed-role"],
)
def test_invalid_query_and_duplicate_groups_fail_closed(case):
    rows = rectangle()
    if case == "duplicate":
        rows += (rows[0],)
    elif case == "split-origin":
        rows = (
            replace(rows[0], query=replace(rows[0].query, query_id="split")),
        ) + rows[1:]
    elif case == "merged-origins":
        rows += tuple(
            replace(r, query=replace(r.query, query_id="A:0"))
            for r in rectangle(origin=1)
        )
    elif case == "sibling-drift":
        rows += rectangle(origin=1, group="other")
    else:
        rows = (replace(rows[0], role="evaluation"),) + rows[1:]
    with pytest.raises(FeasibilityError, match="DUPLICATE|QUERY_ORIGIN_GROUP"):
        pair_roster(rows)
    with pytest.raises(FeasibilityError, match="DUPLICATE|QUERY_ORIGIN_GROUP"):
        PrefixRequest(rows, 2, ())


def test_pairs_cannot_cross_queries_even_when_candidate_ids_match():
    with pytest.raises(FeasibilityError, match="PAIR_QUERY"):
        Pair(rectangle()[2], rectangle(origin=1)[0])


@pytest.mark.parametrize(
    "factory,kwargs",
    [
        (SourceVersions, dict(version="unknown")),
        (SourceVersions, dict(features="synthetic.xy.v2")),
        (SourceVersions, dict(relevance="economic.sharpe.v1")),
        (SourceVersions, dict(source_id="")),
        (
            Query,
            dict(
                family="A",
                related_group="G",
                origin=0,
                query_id="",
                version="m4.ml03.query.v1",
            ),
        ),
        (Query, dict(family="A", related_group="G", origin=True, query_id="A:0")),
    ],
)
def test_unknown_versions_or_invalid_source_query_are_rejected(factory, kwargs):
    with pytest.raises(FeasibilityError):
        factory(**kwargs)


def test_source_identity_is_bound_to_fit_transform_and_magnitude(request_data):
    fit = fit_preprocessing(request_data)
    source = SourceVersions(source_id="another-synthetic-source")
    rows = tuple(
        replace(r, query=replace(r.query, source=source)) for r in request_data.rows
    )
    with pytest.raises(FeasibilityError, match="SOURCE_MISMATCH"):
        replace(request_data, rows=rows)
    with pytest.raises(FeasibilityError, match="SOURCE_MISMATCH"):
        pair_roster(request_data.rows[:1] + rows[1:])
    with pytest.raises(FeasibilityError, match="SOURCE_MISMATCH"):
        fit.transform(rows)
    assert (
        fit_preprocessing(replace(request_data, rows=rows, source=source)).fit_id
        != fit.fit_id
    )
    scores = RankScores(rectangle()[0].query, ("0", "2"), (10.0, 20.0))
    head = SyntheticMagnitudeHead(source, scores.ranker_id, -0.5)
    with pytest.raises(FeasibilityError, match="HEAD_SOURCE_MISMATCH"):
        magnitudes(scores, delta_is=(0.0, 1.0), anchor_id="0", head=head)


@pytest.mark.parametrize(
    "changes",
    [
        dict(version="unknown"),
        dict(target="sharpe.v1"),
        dict(slope=0.0),
        dict(slope=float("nan")),
    ],
)
def test_unknown_or_invalid_magnitude_heads_fail_closed(changes):
    with pytest.raises(FeasibilityError):
        SyntheticMagnitudeHead(
            SourceVersions(), "ranker", **(dict(slope=-0.5) | changes)
        )


def test_arbitrary_ordinal_scores_have_no_y_or_q_units():
    query = rectangle()[0].query
    for values in ((1.0, 2.0, 4.0), (100.0, 200.0, 400.0), (-7.0, -6.0, -4.0)):
        scores = RankScores(query, ("anchor", "a", "b"), values)
        with pytest.raises(FeasibilityError, match="VERSIONED_MAGNITUDE_HEAD_REQUIRED"):
            magnitudes(scores, delta_is=(0.0, 0.2, 0.5), anchor_id="anchor")
        with pytest.raises(FeasibilityError, match="VERSIONED_MAGNITUDE_HEAD_REQUIRED"):
            magnitudes(
                scores, delta_is=(0.0, 0.2, 0.5), anchor_id="anchor", head=object()
            )


def test_versioned_toy_head_has_exact_anchor_and_magnitude_identity():
    scores = RankScores(rectangle()[0].query, ("anchor", "a", "b"), (10.0, 12.0, 8.0))
    head = SyntheticMagnitudeHead(scores.query.source, scores.ranker_id, -0.25)
    result = magnitudes(
        scores, delta_is=(0.0, 0.2, -0.1), anchor_id="anchor", head=head
    )
    assert result.head_version == HEAD_VERSION
    assert result.yhat == (0.0, -0.5, 0.5)
    np.testing.assert_allclose(result.qhat, (0.0, 0.7, -0.6), rtol=0, atol=1e-15)
    shifted = replace(scores, scores=(110.0, 112.0, 108.0))
    assert (
        magnitudes(shifted, delta_is=(0.0, 0.2, -0.1), anchor_id="anchor", head=head)
        == result
    )
    with pytest.raises(FeasibilityError, match="HEAD_SOURCE_MISMATCH"):
        magnitudes(
            replace(scores, ranker_id="other-model"),
            delta_is=(0.0, 0.2, -0.1),
            anchor_id="anchor",
            head=head,
        )
    for delta, anchor in (
        ((1.0, 0.2, -0.1), "anchor"),
        ((0.0, 0.2), "anchor"),
        ((0.0, 0.2, -0.1), "absent"),
    ):
        with pytest.raises(FeasibilityError, match="MAGNITUDE_ANCHOR|MAGNITUDE_QUERY"):
            magnitudes(scores, delta_is=delta, anchor_id=anchor, head=head)
    for action in ("select", "veto"):
        with pytest.raises(FeasibilityError, match="ECONOMIC_RIGHTS_DENIED"):
            authorize_use(result, action=action)


@pytest.mark.parametrize("action", ["select", "veto"])
def test_high_variance_clusters_alone_never_authorize_economics(request_data, action):
    fit = fit_preprocessing(request_data)
    rows = rectangle()
    result = fit.transform(rows)
    for cluster in (0, 1):
        relevance = [r.relevance for r, c in zip(rows, result.clusters) if c == cluster]
        assert sorted(relevance) == [-1.0, 1.0]
    authorize_use(result, action="diagnose")
    with pytest.raises(FeasibilityError, match="ECONOMIC_RIGHTS_DENIED"):
        authorize_use(result, action=action)
    with pytest.raises(FeasibilityError, match="ECONOMIC_ACTION_INVALID"):
        authorize_use(result, action="activate")
    with pytest.raises(FeasibilityError, match="VERSION_INVALID"):
        authorize_use(Diagnostic((), (), version="unknown"), action="diagnose")


def test_invalid_support_rows_and_clock_inputs_fail_closed(request_data):
    for changes in (
        dict(version="unknown"),
        dict(cutoff=True),
        dict(excluded_groups=("held", "held")),
    ):
        with pytest.raises(FeasibilityError):
            replace(request_data, **changes)
    with pytest.raises(FeasibilityError, match="SUPPORT_INSUFFICIENT"):
        fit_preprocessing(replace(request_data, excluded_groups=("train", "held")))
    with pytest.raises(FeasibilityError, match="NO_VARIANCE"):
        fit_preprocessing(
            replace(
                request_data,
                rows=tuple(replace(r, features=(1.0, 1.0)) for r in rectangle()),
            )
        )
    with pytest.raises(FeasibilityError, match="ROW_LIMIT"):
        pair_roster(rectangle() * (MAX_ROWS // 4 + 1))
    for changes in (
        dict(features=(float("nan"), 0.0)),
        dict(role="forward"),
        dict(revision_available_at=-1),
        dict(label_available_at=True),
        dict(version="unknown"),
    ):
        with pytest.raises(FeasibilityError):
            replace(rectangle()[0], **changes)
    with pytest.raises(FeasibilityError, match="RANK_QUERY_OR_SCORE"):
        RankScores(rectangle()[0].query, ("a", "a"), (1.0, 2.0))


def test_numeric_fit_limits_all_loaded_threadpools_to_one(request_data, monkeypatch):
    from sklearn.cluster import KMeans
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler
    from threadpoolctl import threadpool_info

    calls = []
    for cls in (StandardScaler, PCA, KMeans):
        original = cls.fit

        def checked(self, *args, _original=original, _name=cls.__name__, **kwargs):
            assert all(p["num_threads"] == 1 for p in threadpool_info())
            calls.append(_name)
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(cls, "fit", checked)
    fit_preprocessing(request_data)
    assert calls == ["StandardScaler", "PCA", "KMeans"]


def test_unqualified_sklearn_version_is_not_silently_used(request_data, monkeypatch):
    import sklearn

    monkeypatch.setattr(sklearn, "__version__", "1.9.0")
    with pytest.raises(FeasibilityError, match="SKLEARN_VERSION_INVALID"):
        fit_preprocessing(request_data)


def test_fresh_optional_absence_keeps_ridge_imports_working():
    root = Path(__file__).resolve().parents[2]
    code = """
import importlib.abc
import sys
class BlockOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'sklearn', 'xgboost', 'lightgbm', 'catboost', 'threadpoolctl'}:
            raise ModuleNotFoundError('synthetic optional absence: ' + fullname)
sys.meta_path.insert(0, BlockOptional())
from tools.meta_model_research.feasibility import FeasibilityError, run_feasibility
from quantbt.optimization.meta_selection.model import RidgeLearner, RidgeSettings
from tools.meta_model_research.linear import LinearResearch
assert RidgeLearner and LinearResearch and RidgeSettings().lambda_reg == 10.
assert 'sklearn' not in sys.modules
try:
    run_feasibility()
except FeasibilityError as exc:
    assert str(exc) == 'MLR03_OPTIONAL_DEPENDENCY_UNAVAILABLE'
else:
    raise AssertionError('missing optional dependency did not fail closed')
print('ridge-imports-intact; optional-feasibility-failed-closed')
"""
    env = dict(
        os.environ,
        PYTHONPATH=os.pathsep.join((str(root / "src"), str(root))),
        PYTHONDONTWRITEBYTECODE="1",
        OMP_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
        NUMEXPR_NUM_THREADS="1",
    )
    completed = subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert (
        completed.stdout.strip()
        == "ridge-imports-intact; optional-feasibility-failed-closed"
    )
