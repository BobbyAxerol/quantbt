"""Tiny synthetic MLR-03 contracts, not model screening or economic admission.

All clocks are synthetic integer ticks. The two coordinates have shared toy
semantics across groups; this is not permission to pool real family schemas.
Optional sklearn/threadpoolctl imports occur only at the numeric fit boundary.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
from itertools import combinations
import json
import math
from typing import Literal

import numpy as np


VERSION = "m4.ml03.feasibility.v1"
HEAD_VERSION = "m4.ml03.synthetic-affine-y-head.v1"
MAX_ROWS = 64
MAX_PAIRS = 16


class FeasibilityError(ValueError):
    """An unsupported synthetic contract must not acquire implicit rights."""


def _version(actual: str, expected: str) -> None:
    if actual != expected:
        raise FeasibilityError("MLR03_VERSION_INVALID:" + expected)


def _token(value: str) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _finite(value: float) -> bool:
    return type(value) in {int, float} and math.isfinite(value)


@dataclass(frozen=True, slots=True)
class SourceVersions:
    source_id: str = "synthetic-rectangle"
    features: str = "synthetic.xy.v1"
    relevance: str = "synthetic.higher-is-better.v1"
    version: str = "m4.ml03.source.v1"

    def __post_init__(self) -> None:
        _version(self.version, "m4.ml03.source.v1")
        _version(self.features, "synthetic.xy.v1")
        _version(self.relevance, "synthetic.higher-is-better.v1")
        if not _token(self.source_id):
            raise FeasibilityError("MLR03_SOURCE_INVALID")


@dataclass(frozen=True, slots=True)
class Query:
    family: str
    related_group: str
    origin: int
    query_id: str
    source: SourceVersions = SourceVersions()
    version: str = "m4.ml03.query.v1"

    def __post_init__(self) -> None:
        _version(self.version, "m4.ml03.query.v1")
        if (
            not all(_token(x) for x in (self.family, self.related_group, self.query_id))
            or type(self.origin) is not int
            or self.origin < 0
            or type(self.source) is not SourceVersions
        ):
            raise FeasibilityError("MLR03_QUERY_INVALID")


@dataclass(frozen=True, slots=True)
class SyntheticRow:
    query: Query
    candidate_id: str
    features: tuple[float, float]
    relevance: float
    feature_available_at: int
    label_available_at: int
    revision_available_at: int
    role: Literal["train", "evaluation"] = "train"
    version: str = "m4.ml03.row.v1"

    def __post_init__(self) -> None:
        _version(self.version, "m4.ml03.row.v1")
        if (
            type(self.query) is not Query
            or not _token(self.candidate_id)
            or type(self.features) is not tuple
            or len(self.features) != 2
            or not all(_finite(x) and abs(x) <= 1e6 for x in self.features)
            or not _finite(self.relevance)
            or abs(self.relevance) > 1e6
            or self.role not in ("train", "evaluation")
        ):
            raise FeasibilityError("MLR03_ROW_INVALID")
        clocks = (
            self.feature_available_at,
            self.label_available_at,
            self.revision_available_at,
        )
        if (
            not all(type(x) is int and x >= self.query.origin for x in clocks)
            or self.revision_available_at < self.label_available_at
        ):
            raise FeasibilityError("MLR03_AVAILABILITY_INVALID")


def _rows(rows: tuple[SyntheticRow, ...]) -> None:
    if (
        type(rows) is not tuple
        or not 1 <= len(rows) <= MAX_ROWS
        or any(type(r) is not SyntheticRow for r in rows)
    ):
        raise FeasibilityError("MLR03_ROW_LIMIT_OR_TYPE_INVALID")
    sources = {r.query.source for r in rows}
    if len(sources) != 1:
        raise FeasibilityError("MLR03_SOURCE_MISMATCH")
    by_query, by_origin, families, seen = {}, {}, {}, set()
    for row in rows:
        q = row.query
        origin = (q.family, q.origin)
        # One exact query per family/origin, including role and sibling group.
        witness = (q.family, q.related_group, q.origin, row.role)
        if (
            by_query.setdefault(q.query_id, witness) != witness
            or by_origin.setdefault(origin, q.query_id) != q.query_id
            or families.setdefault(q.family, q.related_group) != q.related_group
        ):
            raise FeasibilityError("MLR03_QUERY_ORIGIN_GROUP_MISMATCH")
        key = (origin, row.candidate_id)
        if key in seen:
            raise FeasibilityError("MLR03_DUPLICATE_QUERY_CANDIDATE")
        seen.add(key)


@dataclass(frozen=True, slots=True)
class PrefixRequest:
    rows: tuple[SyntheticRow, ...]
    cutoff: int
    excluded_groups: tuple[str, ...]
    source: SourceVersions = SourceVersions()
    version: str = "m4.ml03.prefix.v1"

    def __post_init__(self) -> None:
        _version(self.version, "m4.ml03.prefix.v1")
        _rows(self.rows)
        if (
            type(self.cutoff) is not int
            or self.cutoff <= 0
            or type(self.excluded_groups) is not tuple
            or not all(_token(g) for g in self.excluded_groups)
            or len(set(self.excluded_groups)) != len(self.excluded_groups)
        ):
            raise FeasibilityError("MLR03_PREFIX_INVALID")
        if (
            type(self.source) is not SourceVersions
            or self.rows[0].query.source != self.source
        ):
            raise FeasibilityError("MLR03_SOURCE_MISMATCH")


def permitted_rows(request: PrefixRequest) -> tuple[SyntheticRow, ...]:
    if type(request) is not PrefixRequest:
        raise FeasibilityError("MLR03_PREFIX_TYPE_INVALID")
    allowed = (
        r
        for r in request.rows
        if r.role == "train"
        and r.query.related_group not in request.excluded_groups
        and max(
            r.query.origin,
            r.feature_available_at,
            r.label_available_at,
            r.revision_available_at,
        )
        < request.cutoff
    )
    return tuple(
        sorted(
            allowed,
            key=lambda r: (
                r.query.family,
                r.query.origin,
                r.query.query_id,
                r.candidate_id,
            ),
        )
    )


@dataclass(frozen=True, slots=True)
class Pair:
    better: SyntheticRow
    worse: SyntheticRow

    def __post_init__(self) -> None:
        if (
            self.better.query != self.worse.query
            or self.better.role != self.worse.role
            or self.better.candidate_id == self.worse.candidate_id
            or self.better.relevance <= self.worse.relevance
        ):
            raise FeasibilityError("MLR03_PAIR_QUERY_OR_ORDER_INVALID")


def pair_roster(rows: tuple[SyntheticRow, ...], *, cap: int = 8) -> tuple[Pair, ...]:
    """A deterministic capped witness roster, not a full pairwise training set."""
    _rows(rows)
    if type(cap) is not int or not 1 <= cap <= MAX_PAIRS:
        raise FeasibilityError("MLR03_PAIR_LIMIT_INVALID")
    groups: dict[str, list[SyntheticRow]] = {}
    for row in sorted(rows, key=lambda r: (r.query.query_id, r.candidate_id)):
        groups.setdefault(row.query.query_id, []).append(row)
    pairs = []
    for group in groups.values():
        # combinations is lazy; no candidate-by-candidate matrix/list is built.
        for a, b in combinations(group, 2):
            if a.relevance == b.relevance:
                continue
            better, worse = (a, b) if a.relevance > b.relevance else (b, a)
            pairs.append(Pair(better, worse))
            if len(pairs) == cap:
                return tuple(pairs)
    return tuple(pairs)


def pair_accuracy(
    pairs: tuple[Pair, ...], direction: tuple[float, float]
) -> float | None:
    """Synthetic relevance only; ties receive half credit, no pairs means null."""
    if (
        type(pairs) is not tuple
        or len(pairs) > MAX_PAIRS
        or any(type(p) is not Pair for p in pairs)
        or type(direction) is not tuple
        or len(direction) != 2
        or not all(_finite(x) for x in direction)
    ):
        raise FeasibilityError("MLR03_PAIR_SCORE_INVALID")
    margins = [
        math.fsum(
            w * (a - b)
            for w, a, b in zip(direction, p.better.features, p.worse.features)
        )
        for p in pairs
    ]
    return (
        None
        if not pairs
        else math.fsum(1 if m > 0 else 0.5 if m == 0 else 0 for m in margins)
        / len(pairs)
    )


def _dependencies():
    try:
        import sklearn
        from sklearn.cluster import KMeans
        from sklearn.decomposition import PCA
        from sklearn.preprocessing import StandardScaler
        from threadpoolctl import threadpool_limits
    except ImportError as exc:
        raise FeasibilityError("MLR03_OPTIONAL_DEPENDENCY_UNAVAILABLE") from exc
    if sklearn.__version__.split(".")[:2] != ["1", "8"]:
        raise FeasibilityError("MLR03_SKLEARN_VERSION_INVALID: require 1.8.x")
    return sklearn.__version__, KMeans, PCA, StandardScaler, threadpool_limits


@dataclass(frozen=True, slots=True)
class Diagnostic:
    projections: tuple[float, ...]
    clusters: tuple[int, ...]
    version: str = "m4.ml03.unsupervised.v1"


@dataclass(frozen=True, slots=True)
class PreprocessingFit:
    fit_id: str
    source: SourceVersions
    cutoff: int
    fit_refs: tuple[tuple[str, str], ...]
    mean: tuple[float, float]
    axis: tuple[float, float]
    projection_offset: float
    variance_ratio: float
    cluster_centers: tuple[float, float]
    backend_versions: tuple[str, str]
    version: str = "m4.ml03.center-pca-kmeans.v1"

    def transform(self, rows: tuple[SyntheticRow, ...]) -> Diagnostic:
        _version(self.version, "m4.ml03.center-pca-kmeans.v1")
        _rows(rows)
        if rows[0].query.source != self.source:
            raise FeasibilityError("MLR03_SOURCE_MISMATCH")
        projections = tuple(
            math.fsum((x - m) * a for x, m, a in zip(r.features, self.mean, self.axis))
            - self.projection_offset
            for r in rows
        )
        clusters = tuple(
            min(range(2), key=lambda i: (abs(x - self.cluster_centers[i]), i))
            for x in projections
        )
        return Diagnostic(projections, clusters)


def fit_preprocessing(request: PrefixRequest) -> PreprocessingFit:
    """Fit centering, raw-variance PCA and two clusters on the allowed prefix."""
    rows = permitted_rows(request)
    if len(rows) < 4:
        raise FeasibilityError("MLR03_PREFIX_SUPPORT_INSUFFICIENT")
    sklearn_version, KMeans, PCA, StandardScaler, threadpool_limits = _dependencies()
    x = np.asarray([r.features for r in rows], dtype=np.float64)
    if np.max(np.var(x, axis=0)) == 0:
        raise FeasibilityError("MLR03_PREFIX_NO_VARIANCE")
    with threadpool_limits(limits=1):
        center = StandardScaler(with_std=False).fit(x)
        pca = PCA(n_components=1, svd_solver="full").fit(center.transform(x))
        z = pca.transform(center.transform(x))
        initial = np.array([[z.min()], [z.max()]])
        clusters = KMeans(
            n_clusters=2,
            init=initial,
            n_init=1,
            max_iter=20,
            random_state=731,
            algorithm="lloyd",
        ).fit(z)
    # Only fit-eligible data enters identity; relevance values are not features.
    identity = dict(
        version="m4.ml03.center-pca-kmeans.v1",
        source=asdict(request.source),
        cutoff=request.cutoff,
        excluded_groups=sorted(request.excluded_groups),
        backend_versions=(np.__version__, sklearn_version),
        settings=dict(
            center_only=True,
            components=1,
            solver="full",
            clusters=2,
            init="prefix_extrema",
            n_init=1,
            max_iter=20,
            seed=731,
            algorithm="lloyd",
            threads=1,
        ),
        rows=[{k: v for k, v in asdict(r).items() if k != "relevance"} for r in rows],
    )
    fit_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()
    return PreprocessingFit(
        fit_id,
        request.source,
        request.cutoff,
        tuple((r.query.query_id, r.candidate_id) for r in rows),
        tuple(map(float, center.mean_)),
        tuple(map(float, pca.components_[0])),
        float(pca.mean_ @ pca.components_[0]),
        float(pca.explained_variance_ratio_[0]),
        tuple(sorted(map(float, clusters.cluster_centers_[:, 0]))),
        (np.__version__, sklearn_version),
    )


@dataclass(frozen=True, slots=True)
class RankScores:
    query: Query
    candidate_ids: tuple[str, ...]
    scores: tuple[float, ...]
    ranker_id: str = "synthetic-pair-direction.v1"
    version: str = "m4.ml03.ordinal.v1"

    def __post_init__(self) -> None:
        _version(self.version, "m4.ml03.ordinal.v1")
        if (
            type(self.query) is not Query
            or not _token(self.ranker_id)
            or type(self.candidate_ids) is not tuple
            or type(self.scores) is not tuple
            or not 1 <= len(self.scores) == len(self.candidate_ids) <= MAX_ROWS
            or not all(_token(c) for c in self.candidate_ids)
            or len(set(self.candidate_ids)) != len(self.candidate_ids)
            or not all(_finite(s) for s in self.scores)
        ):
            raise FeasibilityError("MLR03_RANK_QUERY_OR_SCORE_INVALID")


@dataclass(frozen=True, slots=True)
class SyntheticMagnitudeHead:
    source: SourceVersions
    ranker_id: str
    slope: float
    target: str = "synthetic.relative-y.v1"
    version: str = HEAD_VERSION

    def __post_init__(self) -> None:
        _version(self.version, HEAD_VERSION)
        _version(self.target, "synthetic.relative-y.v1")
        if (
            type(self.source) is not SourceVersions
            or not _token(self.ranker_id)
            or not _finite(self.slope)
            or self.slope == 0
        ):
            raise FeasibilityError("MLR03_MAGNITUDE_HEAD_INVALID")


@dataclass(frozen=True, slots=True)
class SyntheticMagnitudes:
    yhat: tuple[float, ...]
    qhat: tuple[float, ...]
    head_version: str = HEAD_VERSION
    version: str = "m4.ml03.synthetic-magnitudes.v1"


def magnitudes(
    scores: RankScores,
    *,
    delta_is: tuple[float, ...],
    anchor_id: str,
    head: SyntheticMagnitudeHead | None = None,
) -> SyntheticMagnitudes:
    """A toy affine head tests units/anchor algebra, never economic calibration."""
    if type(scores) is not RankScores:
        raise FeasibilityError("MLR03_RANK_QUERY_OR_SCORE_INVALID")
    if type(head) is not SyntheticMagnitudeHead:
        raise FeasibilityError("MLR03_VERSIONED_MAGNITUDE_HEAD_REQUIRED")
    if head.source != scores.query.source or head.ranker_id != scores.ranker_id:
        raise FeasibilityError("MLR03_MAGNITUDE_HEAD_SOURCE_MISMATCH")
    if (
        type(delta_is) is not tuple
        or len(delta_is) != len(scores.scores)
        or not all(_finite(x) for x in delta_is)
        or anchor_id not in scores.candidate_ids
    ):
        raise FeasibilityError("MLR03_MAGNITUDE_QUERY_INVALID")
    anchor = scores.candidate_ids.index(anchor_id)
    if delta_is[anchor] != 0:
        raise FeasibilityError("MLR03_MAGNITUDE_ANCHOR_INVALID")
    yhat = tuple(head.slope * (s - scores.scores[anchor]) for s in scores.scores)
    qhat = tuple(d - y for d, y in zip(delta_is, yhat))
    if not all(math.isfinite(x) for x in yhat + qhat):
        raise FeasibilityError("MLR03_MAGNITUDE_NONFINITE")
    return SyntheticMagnitudes(yhat, qhat)


def authorize_use(
    evidence: Diagnostic | RankScores | SyntheticMagnitudes,
    *,
    action: Literal["diagnose", "select", "veto"],
) -> None:
    versions = {
        Diagnostic: "m4.ml03.unsupervised.v1",
        RankScores: "m4.ml03.ordinal.v1",
        SyntheticMagnitudes: "m4.ml03.synthetic-magnitudes.v1",
    }
    if type(evidence) not in versions:
        raise FeasibilityError("MLR03_ECONOMIC_EVIDENCE_INVALID")
    _version(evidence.version, versions[type(evidence)])
    if action in ("select", "veto"):
        raise FeasibilityError(
            "MLR03_ECONOMIC_RIGHTS_DENIED: synthetic diagnostics only"
        )
    if action != "diagnose":
        raise FeasibilityError("MLR03_ECONOMIC_ACTION_INVALID")


def _rectangle(family: str, group: str, origin: int, *, role="train", scale=1.0):
    q = Query(family, group, origin, f"{family}:{origin}")
    return tuple(
        SyntheticRow(q, str(i), (scale * x, scale * z), x, origin, origin, origin, role)
        for i, (x, z) in enumerate(
            ((-1.0, -10.0), (-1.0, 10.0), (1.0, -10.0), (1.0, 10.0))
        )
    )


def run_feasibility() -> dict[str, object]:
    """Run fixed tiny mathematical controls; no files, outcomes or activation."""
    train = _rectangle("A", "train", 0)
    held = _rectangle("B", "held", 0, scale=2.0)
    future = _rectangle("A", "train", 3, role="evaluation", scale=3.0)
    request = PrefixRequest(train + held + future, 2, ("held",))
    fit = fit_preprocessing(request)
    mutated = tuple(
        replace(r, features=(900.0, -700.0), relevance=123.0) if r not in train else r
        for r in request.rows
    )
    future_fit = fit_preprocessing(replace(request, rows=mutated))
    past = (replace(train[0], features=(3.0, -10.0)),) + request.rows[1:]
    past_fit = fit_preprocessing(replace(request, rows=past))
    pairs = pair_roster(permitted_rows(request))
    # Bounded linear pair-difference recovery: relevance=x, nuisance=z.
    _, _, _, _, threadpool_limits = _dependencies()
    with threadpool_limits(limits=1):
        direction = tuple(
            map(
                float,
                np.linalg.lstsq(
                    np.array(
                        [
                            np.subtract(p.better.features, p.worse.features)
                            for p in pairs
                        ]
                    ),
                    np.array([p.better.relevance - p.worse.relevance for p in pairs]),
                    rcond=None,
                )[0],
            )
        )
    transfer = pair_roster(held)
    # Each feature vector has both labels: no feature-based ordering has skill.
    noise = tuple(
        replace(r, candidate_id=f"{r.candidate_id}:{label}", relevance=float(label))
        for r in train
        for label in (-1, 1)
    )
    noise_pairs = pair_roster(noise, cap=MAX_PAIRS)
    diagnostic = fit.transform(train)
    cluster_balanced = all(
        sum(r.relevance for r, c in zip(train, diagnostic.clusters) if c == cluster)
        == 0
        for cluster in (0, 1)
    )
    scores = RankScores(train[0].query, ("0", "2"), (0.0, 2.0))
    blocked = []
    for evidence in (diagnostic, scores):
        for action in ("select", "veto"):
            try:
                authorize_use(evidence, action=action)
            except FeasibilityError as exc:
                blocked.append(str(exc).startswith("MLR03_ECONOMIC_RIGHTS_DENIED"))
    try:
        magnitudes(scores, delta_is=(0.0, 0.5), anchor_id="0")
    except FeasibilityError as exc:
        head_required = str(exc) == "MLR03_VERSIONED_MAGNITUDE_HEAD_REQUIRED"
    else:
        head_required = False
    toy = magnitudes(
        scores,
        delta_is=(0.0, 0.5),
        anchor_id="0",
        head=SyntheticMagnitudeHead(scores.query.source, scores.ranker_id, -0.25),
    )
    controls = dict(
        prefix_mean=fit.mean == (0.0, 0.0),
        future_and_heldout_invariant=fit == future_fit,
        allowed_past_changes_fit=fit.fit_id != past_fit.fit_id
        and fit.mean != past_fit.mean,
        pca_variance=math.isclose(fit.variance_ratio, 100 / 101, abs_tol=1e-12),
        transfer=pair_accuracy(transfer, direction) == 1.0,
        nuisance_no_skill=pair_accuracy(transfer, (0.0, 1.0)) == 0.5,
        balanced_noise_no_skill=pair_accuracy(noise_pairs, direction) == 0.5,
        clusters_not_quality=cluster_balanced,
        magnitude_head_required=head_required,
        magnitude_algebra=toy.yhat == (0.0, -0.5) and toy.qhat == (0.0, 1.0),
        economic_rights_denied=len(blocked) == 4 and all(blocked),
    )
    if not all(controls.values()):
        raise FeasibilityError("MLR03_INDEPENDENT_CONTROL_FAILED:" + repr(controls))
    return dict(
        version=VERSION,
        status="PASS",
        scope="synthetic-only",
        disposition="DEFER_NEW_FAMILY",
        controls=controls,
        fit_id=fit.fit_id,
        fit_rows=len(fit.fit_refs),
        pairs=len(pairs),
        preprocessing_fits=3,
        pair_direction_fits=1,
        numeric_threads=1,
        backend_versions=fit.backend_versions,
        financial_calls=0,
        private_outcomes_read=0,
        model_screen=False,
        auto_activation=False,
        economic_improvement=None,
        limits=dict(rows=MAX_ROWS, pairs=MAX_PAIRS, dimensions=2),
        limitations=(
            "Toy relevance transfer is not economic or external OOS evidence.",
            "Affine head is synthetic algebra, not qualified Y/Q calibration.",
            "PCA/clusters confer no economic selection or veto rights.",
        ),
    )
