"""Bounded quarterly research binding over the existing QMS record owners.

The caller owns capture, both IS selectors, clocks and qualified observations.
No optimizer, financial evaluation, metric reduction or persistence lives here.
MetaTask windows use actual hourly bar endpoints, not the calendar's exclusive
ends. Fresh 2022 histories with the registered one-second publication lag first
permit twelve mature origins at 2025Q2, leaving at most six learned decisions.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace

import pandas as pd

from quantbt.optimization.meta_selection.common import MetaRecordError, digest, token, utc
from quantbt.optimization.meta_selection.config import MetaHistoryContext, MetaSelectionConfig
from quantbt.optimization.meta_selection.descriptors import DescriptorSchema
from quantbt.optimization.meta_selection.history import HistorySnapshot, SealedTaskRevision
from quantbt.optimization.meta_selection.model import FitOutcome, RidgeLearner, RidgeSettings
from quantbt.optimization.meta_selection.panel import FrozenLabelPanel, freeze_panel
from quantbt.optimization.meta_selection.records import (
    CandidateForwardRecord, CandidateISRecord, CandidateRoleRef, CompatibilityFamily, MetaTask,
)
from quantbt.optimization.meta_selection.selection import MetaSelectionDecision, MetaSelector

from .contracts import PROFILE_ID, quarterly_calendar


SCOPE_ID = "m5_11_6_1_shared_pool_quarterly_v1"


def rebase_task(base_task: MetaTask, *, family: CompatibilityFamily,
                anchor_evaluation_id: str) -> MetaTask:
    """Rewrite only family/anchor references; retain the entire captured IS pool.

    Window-policy namespacing and anchor methodology may differ. Physical
    strategy/schema/sampler/account/metric/economic identities may not. This
    never copies a trained model or a candidate-minus-anchor label.
    """
    expected = replace(base_task.family, anchor_policy_id=family.anchor_policy_id,
                       window_policy_id=family.window_policy_id)
    if expected != family:
        raise MetaRecordError("research rebase cannot change physical compatibility")
    if anchor_evaluation_id not in {c.evaluation_id for c in base_task.candidates}:
        raise MetaRecordError("research anchor must reference the captured IS pool")
    roles = tuple(r for r in base_task.roles if r.role != "native_anchor")
    return replace(
        base_task, family=family, anchor_candidate_evaluation_id=anchor_evaluation_id,
        roles=roles + (CandidateRoleRef("native_anchor", family.anchor_policy_id,
                                        anchor_evaluation_id),),
    )


def _quarterly_task(task: MetaTask) -> None:
    # QMS records use inclusive observed bars; the calendar uses exclusive ends.
    hour = pd.Timedelta(hours=1)
    fold = next((f for f in quarterly_calendar()
                 if pd.Timestamp(f.oos_start) == task.forward_start), None)
    if (fold is None or task.family.timeframe != "1h"
            or task.is_start != pd.Timestamp(fold.is_start)
            or task.is_end != pd.Timestamp(fold.is_end) - hour
            or task.data_cutoff != task.is_end or task.origin != task.data_cutoff
            or task.forward_end != pd.Timestamp(fold.oos_end) - hour):
        raise MetaRecordError("research requires registered rolling365D/19-quarter hourly tasks")


@dataclass(frozen=True, slots=True)
class PolicyFamilyDecision:
    """Sealed research decision; native is also the meta-OFF comparison arm."""

    task: MetaTask
    snapshot: HistorySnapshot | None
    fit: FitOutcome | None
    decision: MetaSelectionDecision | None
    panel: FrozenLabelPanel

    @property
    def native(self) -> CandidateISRecord:
        return self.task.anchor

    @property
    def selected(self) -> CandidateISRecord:
        eid = (self.decision.actual_evaluation_id if self.decision is not None
               else self.task.anchor_candidate_evaluation_id)
        return next(c for c in self.task.candidates if c.evaluation_id == eid)


@dataclass(frozen=True, slots=True)
class ResearchPolicyTask:
    """Native then optional alternate family, and one original-task query union.

    Pass base_task/query_panel to the existing PostDecisionObserver. It can
    evaluate each evaluation ID once. Only per-family panels enter training;
    the larger physical query union is not a replacement label-panel policy.
    """

    base_task: MetaTask
    families: tuple[PolicyFamilyDecision, ...]
    query_panel: FrozenLabelPanel

    @property
    def native(self) -> PolicyFamilyDecision:
        return self.families[0]

    @property
    def alternate(self) -> PolicyFamilyDecision | None:
        return self.families[1] if len(self.families) == 2 else None


@dataclass(frozen=True, slots=True)
class PolicyFamilyRuntime:
    """One compatible anchor history, using caller-owned bounded MetaHistory.

    No model is reused across anchors or snapshots. OFF performs no history,
    numeric-runtime or learner calls; SHADOW fits/ranks but applies the anchor.
    Panel construction itself never opens forward observations.
    """

    family: CompatibilityFamily
    context: MetaHistoryContext
    schema: DescriptorSchema
    config: MetaSelectionConfig

    def __post_init__(self) -> None:
        if (self.config.ridge_settings() != RidgeSettings()
                or self.config.reporting_lag_seconds != 1.0):
            raise MetaRecordError("research fixes origin-sum lambda10/min12/Qfloor-.10 and 1s lag")
        if (not self.schema.include_activity
                or self.family.descriptor_schema_id != self.schema.schema_id
                or self.family.parameter_schema_id != self.schema.space.identity
                or self.family.instrument_id != self.context.instrument_id
                or self.family.timeframe != self.context.timeframe):
            raise MetaRecordError("research family/context/original descriptor schema mismatch")

    def process_task(self, base_task: MetaTask, *, anchor_evaluation_id: str,
                     information_as_of: pd.Timestamp,
                     fit_completed_at: pd.Timestamp | None = None,
                     snapshot_order: int | None = None) -> PolicyFamilyDecision:
        """Bind, snapshot, fit, rank the full pool and seal an anchor-first panel.

        Completion times are supplied historical-replay clocks, never inferred
        from wall time. Enabled meta requires an explicit fit completion clock.
        The information frontier must equal the captured task's data cutoff.
        """
        task = rebase_task(base_task, family=self.family,
                           anchor_evaluation_id=anchor_evaluation_id)
        _quarterly_task(task)
        if (task.clock_mode != "historical_replay"
                or utc(information_as_of) != task.data_cutoff
                or task.corpus_id != self.context.corpus_id
                or task.run_id != self.context.run_id
                or task.outcome_origin not in self.context.outcome_origins
                or task.research_exposure not in self.context.research_exposures):
            raise MetaRecordError("research replay context/information frontier mismatch")
        snapshot = fit = decision = None
        winners = (anchor_evaluation_id,)
        if self.config.mode != "off":
            if (fit_completed_at is None
                    or not task.data_cutoff <= utc(fit_completed_at) <= task.decision_sealed_at):
                raise MetaRecordError("research fit completion must precede the supplied decision seal")
            snapshot = self.context.history.snapshot(
                family_id=self.family.family_id,
                authorized_corpora=self.context.authorized_corpora,
                outcome_origins=self.context.outcome_origins,
                research_exposures=self.context.research_exposures,
                information_as_of=information_as_of, snapshot_order=snapshot_order,
            )
            for revision in snapshot.revisions:
                _quarterly_task(revision.task)
            numeric = self.context.numeric_runtime(self.config.native_batch_policy)
            fit = RidgeLearner(settings=self.config.ridge_settings(), runtime=numeric).fit(
                self.schema, snapshot, fit_completed_at=fit_completed_at,
                clock_mode=task.clock_mode,
            )
            proposal = MetaSelector(runtime=numeric).propose(
                task, fit, schema=self.schema,
                mode="shadow" if self.config.mode == "shadow" else "proposal",
                full_ranking=self.config.full_ranking,
            )
            decision = (replace(proposal, mode="active",
                                actual_evaluation_id=proposal.proposed_evaluation_id)
                        if self.config.mode == "active" else proposal)
            winners += (decision.proposed_evaluation_id, decision.actual_evaluation_id)
        panel = freeze_panel(task, self.schema, required_winners=winners,
                             sealed_at=task.decision_sealed_at)
        return PolicyFamilyDecision(task, snapshot, fit, decision, panel)


class ResearchPolicies:
    """One sampler's shared-pool research arms; construct separately per sampler.

    Both families receive a new quarterly scope/window identity even if the
    caller accidentally supplied an old monthly source family. Source histories
    and original-alpha models cannot become this variant's training history.
    Variant/execution/schema identities remain the caller's responsibility.
    Omit alternate_anchor_evaluation_id for the single-anchor reference study.
    """

    def __init__(self, *, base_family: CompatibilityFamily, context: MetaHistoryContext,
                 schema: DescriptorSchema, config: MetaSelectionConfig,
                 alternate_anchor_policy_id: str = PROFILE_ID):
        token(alternate_anchor_policy_id)
        self.base_family, self.context, self.schema, self.config = base_family, context, schema, config
        window = digest(dict(scope=SCOPE_ID, source_window=base_family.window_policy_id))
        native = replace(base_family, window_policy_id=window)
        alternate = replace(native, anchor_policy_id=digest(dict(
            scope=SCOPE_ID, native_policy=base_family.anchor_policy_id,
            alternate_policy=alternate_anchor_policy_id,
        )))
        self.native = PolicyFamilyRuntime(native, context, schema, config)
        self.alternate = PolicyFamilyRuntime(alternate, context, schema, config)

    def process_task(self, base_task: MetaTask, *, information_as_of: pd.Timestamp,
                     alternate_anchor_evaluation_id: str | None = None,
                     fit_completed_at: pd.Timestamp | None = None,
                     snapshot_order: int | None = None) -> ResearchPolicyTask:
        """Process one captured pool, without changing objectives or IS records."""
        if base_task.family != self.base_family:
            raise MetaRecordError("research source family changed within a sampler study")
        anchors = [(self.native, base_task.anchor_candidate_evaluation_id)]
        if alternate_anchor_evaluation_id is not None:
            if alternate_anchor_evaluation_id not in {c.evaluation_id for c in base_task.candidates}:
                raise MetaRecordError("alternate anchor is not in the captured IS pool")
            anchors.append((self.alternate, alternate_anchor_evaluation_id))
        results = tuple(runtime.process_task(
            base_task, anchor_evaluation_id=anchor, information_as_of=information_as_of,
            fit_completed_at=fit_completed_at, snapshot_order=snapshot_order,
        ) for runtime, anchor in anchors)
        winners = {r.native.evaluation_id for r in results}
        winners.update(r.decision.proposed_evaluation_id for r in results if r.decision is not None)
        results = tuple(replace(r, panel=freeze_panel(
            r.task, self.schema, required_winners=winners, sealed_at=r.task.decision_sealed_at,
        )) for r in results)
        union = {eid for r in results for eid in r.panel.members}
        if len(union) > (36 if len(results) == 2 else 18):
            raise MetaRecordError("research physical observer union exceeds registered budget")
        query_panel = freeze_panel(base_task, self.schema, required_winners=union,
                                   sealed_at=base_task.decision_sealed_at)
        return ResearchPolicyTask(base_task, results, query_panel)

    def publish_forward(self, bound: ResearchPolicyTask,
                        outcomes: Iterable[CandidateForwardRecord], *,
                        revision_available_at: pd.Timestamp,
                        publication_order: int | None = None) -> tuple[SealedTaskRevision, ...]:
        """Publish complete, already qualified observations to separate families.

        Outcomes must reference base_task and exactly the sealed physical union.
        Preserve actual per-label availability/order and the raw observation
        object. Existing SealedTaskRevision owns validity, Y/Q and origin weights;
        MetaHistory owns append/correction rules and as-of publication filtering.
        Corrections use those existing owners, not a second history mechanism.
        """
        if not self.config.label_observer:
            raise MetaRecordError("research label observer was not explicitly enabled")
        records = tuple(outcomes)
        by_id = {o.evaluation_id: o for o in records}
        if (bound.base_task.family != self.base_family
                or bound.query_panel.task_id != bound.base_task.task_id
                or len(by_id) != len(records)
                or set(by_id) != set(bound.query_panel.members)
                or any(o.task_id != bound.base_task.task_id
                       or o.reporting_lag_seconds != self.config.reporting_lag_seconds for o in records)):
            raise MetaRecordError("research outcomes must exactly match the sealed source-task query union")
        expected_families = (self.native.family, self.alternate.family)[:len(bound.families)]
        if (not 1 <= len(bound.families) <= 2
                or tuple(r.task.family for r in bound.families) != expected_families):
            raise MetaRecordError("research publication belongs to different anchor families")
        revisions = tuple(SealedTaskRevision(
            r.task, r.panel,
            tuple(replace(by_id[eid], task_id=r.task.task_id) for eid in r.panel.members),
            revision_available_at, publication_order=publication_order,
        ) for r in bound.families)
        for revision in revisions:
            self.context.history.append(revision)
        return revisions
