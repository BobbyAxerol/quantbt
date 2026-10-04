"""Bounded append-only revisions and explicitly authorized as-of views."""

from __future__ import annotations

from bisect import bisect_left, insort
from dataclasses import dataclass
from itertools import islice
import math

import pandas as pd

from .common import MetaRecordError, digest, token, utc
from .panel import FrozenLabelPanel
from .memo import ImmutableMemo, derived_property
from .records import CandidateForwardRecord, MetaTask, OutcomeStatus


@dataclass(frozen=True, slots=True)
class TrainingRow:
    task_id: str
    revision_id: str
    candidate_evaluation_id: str
    anchor_evaluation_id: str
    raw_is: float
    raw_forward: float
    anchor_is: float
    anchor_forward: float
    decay: float
    y: float
    q: float
    origin_weight: float


@dataclass(frozen=True, slots=True)
class SealedTaskRevision(ImmutableMemo):
    task: MetaTask
    panel: FrozenLabelPanel
    outcomes: tuple[CandidateForwardRecord, ...]
    revision_available_at: pd.Timestamp
    parent_revision_id: str | None = None
    correction_reason: str | None = None
    publication_order: int | None = None
    verification: str = "original_result"

    def __post_init__(self):
        object.__setattr__(self, "outcomes", tuple(self.outcomes))
        object.__setattr__(
            self, "revision_available_at", utc(self.revision_available_at)
        )
        if self.panel.task_id != self.task.task_id:
            raise MetaRecordError("panel belongs to a different task")
        if (
            self.panel.base_members[0] != self.task.anchor_candidate_evaluation_id
            or self.task.anchor_candidate_evaluation_id
            not in self.panel.required_members
            or not set(self.panel.members).issubset(
                c.evaluation_id for c in self.task.candidates
            )
        ):
            raise MetaRecordError(
                "panel must include explicit anchor and only sealed task evaluations"
            )
        if not (
            self.task.decision_sealed_at
            <= self.panel.sealed_at
            <= self.task.first_forward_action_at
        ):
            raise MetaRecordError("panel was not frozen before economic action")
        ids = [o.evaluation_id for o in self.outcomes]
        if len(set(ids)) != len(ids) or set(ids) != set(self.panel.members):
            raise MetaRecordError(
                "required panel dispositions must be complete and unique"
            )
        if self.verification not in {
            "original_result",
            "reviewed_import",
            "unverified",
        }:
            raise MetaRecordError("invalid history verification")
        if bool(self.parent_revision_id) != bool(self.correction_reason):
            raise MetaRecordError("corrections require parent revision and reason")
        if self.publication_order is not None and (
            type(self.publication_order) is not int or self.publication_order < 0
        ):
            raise MetaRecordError("invalid revision publication order")
        candidates = {c.evaluation_id: c for c in self.task.candidates}
        for outcome in self.outcomes:
            m, previous = (
                outcome.observation,
                candidates[outcome.evaluation_id].observation,
            )
            if outcome.task_id != self.task.task_id:
                raise MetaRecordError("forward label belongs to a different task")
            if m.status == OutcomeStatus.PENDING:
                raise MetaRecordError(
                    "PENDING is retained separately, not a sealed revision"
                )
            if (
                m.window_start != self.task.forward_start
                or m.window_end != self.task.forward_end
                or m.metric_contract_id != self.task.family.metric_contract_id
                or m.economics_id != self.task.family.economics_id
                or m.initial_capital != previous.initial_capital
            ):
                raise MetaRecordError(
                    "forward window/metric/economics/base-account mismatch"
                )
            if outcome.label_available_at > self.revision_available_at:
                raise MetaRecordError("revision precedes actual label availability")
        capitals = {c.observation.initial_capital for c in self.task.candidates}
        if len(capitals) != 1:
            raise MetaRecordError(
                "diagnostic candidates do not share the same base account"
            )
        if (
            len({c.observation.input_signature for c in self.task.candidates}) != 1
            or len(
                {
                    o.observation.input_signature
                    for o in self.outcomes
                    if o.observation.status == OutcomeStatus.VALID
                }
            )
            > 1
        ):
            raise MetaRecordError(
                "same-task diagnostics must use the same market input witness"
            )

    @derived_property
    def content_digest(self):
        return digest({"schema": "qms-revision-v1", "record": self})

    @property
    def revision_id(self):
        return self.content_digest

    @derived_property
    def training_rows(self):
        if self.verification == "unverified":
            return ()
        candidates = {c.evaluation_id: c for c in self.task.candidates}
        outcomes = {o.evaluation_id: o.observation for o in self.outcomes}
        anchor_id = self.task.anchor_candidate_evaluation_id
        anchor_is, anchor_forward = (
            candidates[anchor_id].observation,
            outcomes[anchor_id],
        )
        if not _valid(anchor_is) or not _valid(anchor_forward):
            return ()
        valid_ids = sorted(
            eid
            for eid, m in outcomes.items()
            if eid != anchor_id and _valid(m) and _valid(candidates[eid].observation)
        )
        rows = []
        for eid in valid_ids:
            i, o = candidates[eid].observation.raw_sharpe, outcomes[eid].raw_sharpe
            ia, oa = anchor_is.raw_sharpe, anchor_forward.raw_sharpe
            d, y = i - o, (i - o) - (ia - oa)
            q = (i - ia) - y
            if not all(math.isfinite(v) for v in (d, y, q)):
                raise MetaRecordError("nonfinite derived label")
            rows.append(
                TrainingRow(
                    self.task.task_id,
                    self.revision_id,
                    eid,
                    anchor_id,
                    i,
                    o,
                    ia,
                    oa,
                    d,
                    y,
                    q,
                    1.0 / len(valid_ids),
                )
            )
        return tuple(rows)


def _valid(observation):
    return (
        observation.status == OutcomeStatus.VALID
        and observation.verification != "unverified"
    )


@dataclass(frozen=True, slots=True)
class HistorySnapshot(ImmutableMemo):
    family_id: str
    authorized_corpora: tuple[str, ...]
    outcome_origins: tuple[str, ...]
    research_exposures: tuple[str, ...]
    information_as_of: pd.Timestamp
    revisions: tuple[SealedTaskRevision, ...]
    snapshot_order: int | None = None

    def __post_init__(self):
        object.__setattr__(self, "information_as_of", utc(self.information_as_of))
        for name in ("authorized_corpora", "outcome_origins", "research_exposures"):
            values = tuple(sorted(set(getattr(self, name))))
            if not values:
                raise MetaRecordError("explicit nonempty history permissions required")
            for value in values:
                token(value)
            object.__setattr__(self, name, values)
        object.__setattr__(self, "revisions", tuple(self.revisions))
        if self.snapshot_order is not None and (
            type(self.snapshot_order) is not int or self.snapshot_order < 0
        ):
            raise MetaRecordError("invalid snapshot event order")
        tasks, origins = set(), set()
        for revision in self.revisions:
            task = revision.task
            origin_key = (task.family.family_id, task.origin)
            if (
                task.family.family_id != self.family_id
                or task.corpus_id not in self.authorized_corpora
                or task.outcome_origin not in self.outcome_origins
                or task.research_exposure not in self.research_exposures
                or revision.verification == "unverified"
                or not _available(
                    revision.revision_available_at,
                    revision.publication_order,
                    self.information_as_of,
                    self.snapshot_order,
                )
                or any(
                    not _available(
                        o.label_available_at,
                        o.publication_order,
                        self.information_as_of,
                        self.snapshot_order,
                    )
                    for o in revision.outcomes
                )
            ):
                raise MetaRecordError(
                    "snapshot contains unauthorized/unavailable history"
                )
            if task.task_id in tasks or origin_key in origins:
                raise MetaRecordError("an origin/task may contribute only once")
            tasks.add(task.task_id)
            origins.add(origin_key)

    @derived_property
    def snapshot_id(self):
        return digest(
            {
                "schema": "qms-training-snapshot-v1",
                "family": self.family_id,
                "corpora": self.authorized_corpora,
                "cohorts": self.outcome_origins,
                "exposures": self.research_exposures,
                "as_of": self.information_as_of,
                "order": self.snapshot_order,
                "references": sorted(
                    (r.task.task_id, r.revision_id, r.content_digest)
                    for r in self.revisions
                ),
            }
        )

    @derived_property
    def origin_count(self):
        return sum(bool(r.training_rows) for r in self.revisions)

    @derived_property
    def training_rows(self):
        return tuple(
            row for revision in self.revisions for row in revision.training_rows
        )


def _available(available, publication_order, cutoff, snapshot_order):
    return available < cutoff or (
        available == cutoff
        and publication_order is not None
        and snapshot_order is not None
        and publication_order < snapshot_order
    )


class MetaHistory:
    """No unrestricted query: every snapshot declares corpus and cohort permissions."""

    def __init__(self, *, max_revisions=10_000):
        if type(max_revisions) is not int or max_revisions <= 0:
            raise MetaRecordError("history requires a positive bounded capacity")
        self.max_revisions = max_revisions
        self._revisions, self._buckets, self._latest = {}, {}, {}
        self._pending = {}

    def retain_pending(self, record: CandidateForwardRecord):
        if record.observation.status != OutcomeStatus.PENDING:
            raise MetaRecordError("pending retention requires PENDING disposition")
        key = (record.task_id, record.evaluation_id)
        if (
            key not in self._pending
            and len(self._pending) + len(self._revisions) >= self.max_revisions
        ):
            raise MetaRecordError("history capacity exceeded")
        self._pending[key] = record

    @property
    def pending(self):
        return tuple(self._pending[k] for k in sorted(self._pending))

    def append(self, revision: SealedTaskRevision):
        rid, tid = revision.revision_id, revision.task.task_id
        if rid in self._revisions:
            return rid
        retiring = sum(
            (tid, o.evaluation_id) in self._pending for o in revision.outcomes
        )
        if len(self._revisions) + len(self._pending) - retiring >= self.max_revisions:
            raise MetaRecordError("history capacity exceeded; no silent eviction")
        previous = self._latest.get(tid)
        if previous != revision.parent_revision_id:
            raise MetaRecordError(
                "correction must extend the latest revision, not branch/replace it"
            )
        if previous:
            parent = self._revisions[previous]
            if (
                digest(parent.task) != digest(revision.task)
                or parent.panel.panel_id != revision.panel.panel_id
                or revision.revision_available_at < parent.revision_available_at
            ):
                raise MetaRecordError(
                    "correction cannot change sealed IS/panel or move availability backwards"
                )
        key = (
            revision.task.family.family_id,
            revision.task.corpus_id,
            revision.task.outcome_origin,
            revision.task.research_exposure,
        )
        insort(
            self._buckets.setdefault(key, []),
            (revision.revision_available_at.value, len(self._revisions), rid),
        )
        self._revisions[rid], self._latest[tid] = revision, rid
        for outcome in revision.outcomes:
            self._pending.pop((tid, outcome.evaluation_id), None)
        return rid

    def snapshot(
        self,
        *,
        family_id,
        authorized_corpora,
        outcome_origins,
        research_exposures,
        information_as_of,
        snapshot_order=None,
    ):
        cutoff = utc(information_as_of)
        latest = {}
        # Exact bucket lookup plus binary availability bound; no all-archive scan.
        for corpus in sorted(set(authorized_corpora)):
            for cohort in sorted(set(outcome_origins)):
                for exposure in sorted(set(research_exposures)):
                    bucket = self._buckets.get(
                        (family_id, corpus, cohort, exposure), ()
                    )
                    stop = bisect_left(bucket, (cutoff.value + 1, -1, ""))
                    for _, sequence, rid in islice(bucket, stop):
                        revision = self._revisions[rid]
                        if (
                            revision.verification != "unverified"
                            and _available(
                                revision.revision_available_at,
                                revision.publication_order,
                                cutoff,
                                snapshot_order,
                            )
                            and all(
                                _available(
                                    o.label_available_at,
                                    o.publication_order,
                                    cutoff,
                                    snapshot_order,
                                )
                                for o in revision.outcomes
                            )
                        ):
                            latest[revision.task.task_id] = (sequence, revision)
        revisions = tuple(pair[1] for _, pair in sorted(latest.items()))
        return HistorySnapshot(
            family_id,
            tuple(authorized_corpora),
            tuple(outcome_origins),
            tuple(research_exposures),
            cutoff,
            revisions,
            snapshot_order,
        )
