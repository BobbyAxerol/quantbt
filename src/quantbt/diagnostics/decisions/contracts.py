"""Read-only reporting inputs; financial/ML objects keep their existing owners."""

from dataclasses import dataclass
import math

from quantbt.mode5.dossier.records import Record, require_text
from quantbt.optimization.meta_selection.common import digest
from quantbt.optimization.meta_selection.history import SealedTaskRevision
from quantbt.optimization.meta_selection.selection import MetaSelectionDecision

from ..access import AccessWitness


@dataclass(frozen=True)
class FoldSlot:
    fold_id: str
    start_ns: int
    stop_ns: int

    def __post_init__(self):
        require_text(self.fold_id)
        if any(type(v) is not int for v in (self.start_ns,self.stop_ns)) or self.start_ns>=self.stop_ns:
            raise ValueError('exact half-open forward calendar required')


@dataclass(frozen=True)
class ReportCohort:
    name: str
    fold_ids: tuple[str, ...]
    source_ref: str

    def __post_init__(self):
        require_text(self.name)
        require_text(self.source_ref)
        if (type(self.fold_ids) is not tuple or len(set(self.fold_ids))!=len(self.fold_ids)
                or any(not isinstance(k,str) or not k for k in self.fold_ids)):
            raise ValueError('explicit distinct cohort mask required; empty is allowed')


@dataclass(frozen=True)
class MetricSupplement:
    """Exact retained scalar metrics, never recomputed from a target/signal."""

    evaluation_id: str
    observation_identity: str
    source_ref: str
    values: Record
    units: Record

    def __post_init__(self):
        for value in (self.evaluation_id,self.observation_identity,self.source_ref):
            require_text(value)
        if not isinstance(self.values,Record) or not isinstance(self.units,Record):
            raise ValueError('immutable retained metrics and explicit units required')
        allowed={'net_return':'fraction','max_drawdown':'fraction','exposure_fraction':'fraction',
                 'fees':None,'funding':None,'fill_count':'executed_fill_count',
                 'closed_action_count':'closed_action_count','closed_campaign_count':'closed_campaign_count'}
        values,units=self.values.data,self.units.data
        if set(values)!=set(units) or not set(values)<=allowed.keys():
            raise ValueError('explicit supported metric names/units required')
        for name,value in values.items():
            if allowed[name] is not None and units[name]!=allowed[name]:
                raise ValueError('metric unit mismatch: '+name)
            require_text(units[name])
            if value is None:
                continue
            if type(value) not in {int,float} or not math.isfinite(value):
                raise ValueError('finite original metric or null required')
            if name in {'max_drawdown','exposure_fraction'} and not 0<=value<=1:
                raise ValueError('fraction outside declared range')
            if name.endswith('_count') and (type(value) is not int or value<0):
                raise ValueError('exact nonnegative named count required')


@dataclass(frozen=True)
class FoldDecisionEvidence:
    fold_id: str
    revision: SealedTaskRevision
    decision: MetaSelectionDecision | None
    witness: AccessWitness
    source_ref: str
    model_support: Record | None = None
    metrics: tuple[MetricSupplement, ...] = ()
    state_labels: tuple[str, ...] = ()
    state_witness: AccessWitness | None = None
    state_source_ref: str | None = None
    state_label_purpose: str = 'decision_vintage'
    execution_comparison: Record | None = None

    def __post_init__(self):
        require_text(self.fold_id)
        require_text(self.source_ref)
        if (not isinstance(self.revision,SealedTaskRevision) or self.revision.verification=='unverified'
                or not isinstance(self.witness,AccessWitness)):
            raise ValueError('verified original typed revision and availability witness required')
        revision,task=self.revision,self.revision.task
        if (self.witness.manifest_id!=task.corpus_id or self.witness.start_ns>task.is_start.value
                or self.witness.end_ns<=task.forward_end.value
                or self.witness.ready_ns<revision.revision_available_at.value):
            raise ValueError('witness does not cover exact original task/revision availability')
        byid={c.evaluation_id:c for c in task.candidates}
        if self.decision is not None:
            d=self.decision
            if (not isinstance(d,MetaSelectionDecision) or d.task_id!=task.task_id
                    or d.anchor_evaluation_id!=task.anchor_candidate_evaluation_id
                    or d.proposed_evaluation_id not in byid or d.raw_best_evaluation_id not in byid
                    or d.information_as_of>task.data_cutoff or d.clock_mode!=task.clock_mode
                    or d.decision_sealed_at!=task.decision_sealed_at
                    or d.ready_at>task.first_forward_action_at
                    or dict(d.proposed_params)!=dict(byid[d.proposed_evaluation_id].effective_params)):
                raise ValueError('decision does not bind the original pool, params, cutoff and action clock')
            for p in d.predictions:
                c=byid.get(p['evaluation_id'])
                expected=c.observation.raw_sharpe if c else None
                if c is None or p.get('raw_is')!=expected or p.get('candidate_id')!=c.candidate_id:
                    raise ValueError('prediction raw IS/candidate differs from original observation')
                if p.get('yhat') is not None and not math.isclose(
                        p['qhat'],c.observation.raw_sharpe-task.anchor.observation.raw_sharpe-p['yhat'],
                        rel_tol=1e-10,abs_tol=1e-10):
                    raise ValueError('prediction Q/Y differs from the existing structural identity')
            if d.numeric.get('current_forward_inputs') is True:
                raise ValueError('current forward inputs cannot be certified as an IS-only decision')
        for value in (self.model_support,self.execution_comparison):
            if value is not None and not isinstance(value,Record):
                raise ValueError('source-bound immutable support/execution details or null required')
        if self.execution_comparison is not None:
            comparison=self.execution_comparison.data
            actual=self.decision.actual_evaluation_id if self.decision else task.anchor_candidate_evaluation_id
            if (comparison.get('anchor_evaluation_id')!=task.anchor_candidate_evaluation_id
                    or comparison.get('applied_evaluation_id')!=actual):
                raise ValueError('execution comparison belongs to different decisions')
        if type(self.metrics) is not tuple or any(not isinstance(m,MetricSupplement) for m in self.metrics):
            raise ValueError('typed immutable supplemental observations required')
        if len({m.evaluation_id for m in self.metrics})!=len(self.metrics):
            raise ValueError('duplicate supplemental candidate metrics')
        outcomes={o.evaluation_id:o.observation for o in revision.outcomes}
        for m in self.metrics:
            if m.evaluation_id not in outcomes or m.observation_identity!=digest(outcomes[m.evaluation_id]):
                raise ValueError('supplement differs from exact forward observation')
        if type(self.state_labels) is not tuple or len(set(self.state_labels))!=len(self.state_labels):
            raise ValueError('immutable source state labels required')
        for state in self.state_labels:
            require_text(state)
        if self.state_labels:
            if (not isinstance(self.state_witness,AccessWitness)
                    or self.state_witness.start_ns>task.forward_start.value
                    or self.state_witness.end_ns<=task.forward_end.value
                    or self.state_label_purpose not in {'decision_vintage','asof_calibration_descriptive'}):
                raise ValueError('source states require their own scope, availability and declared purpose')
            require_text(self.state_source_ref)
        elif self.state_witness is not None or self.state_source_ref is not None:
            raise ValueError('absent states cannot claim a source-labelled partition')


@dataclass(frozen=True)
class RetainedAccountReport:
    """A qualified original carried account, not concatenated diagnostic equity."""

    family_id: str
    policy: str
    source_ref: str
    witness: AccessWitness
    metrics: Record
    units: Record
    contract_id: str
    result_identity: str
    start_ns: int
    stop_ns: int
    account_policy: str = 'continuous_original_account'

    def __post_init__(self):
        for value in (self.family_id,self.policy,self.source_ref,self.contract_id,self.result_identity):
            require_text(value)
        if (not isinstance(self.witness,AccessWitness) or not isinstance(self.metrics,Record)
                or not isinstance(self.units,Record) or self.account_policy!='continuous_original_account'
                or set(self.metrics.data)!=set(self.units.data)):
            raise ValueError('qualified continuous-account metrics with exact units required')
        if (any(type(v) is not int for v in (self.start_ns,self.stop_ns))
                or not self.witness.start_ns<=self.start_ns<self.stop_ns<=self.witness.end_ns):
            raise ValueError('actual account scope must be covered by its own witness')
        for name,value in self.metrics.data.items():
            require_text(name)
            require_text(self.units.data[name])
            if value is not None and (type(value) not in {int,float,bool} or not math.isfinite(value)):
                raise ValueError('retained metric must be scalar finite or null')


@dataclass(frozen=True)
class RetainedInterval:
    cohort: str
    comparison: str
    metric: str
    fold_ids: tuple[str, ...]
    source_ref: str
    policy_ref: str
    witness: AccessWitness
    status: str
    estimate: float | None = None
    lower: float | None = None
    upper: float | None = None
    reason: str | None = None

    def __post_init__(self):
        for value in (self.cohort,self.comparison,self.source_ref,self.policy_ref,self.status):
            require_text(value)
        if (self.metric not in {'R','Q'} or type(self.fold_ids) is not tuple
                or len(set(self.fold_ids))!=len(self.fold_ids) or not isinstance(self.witness,AccessWitness)):
            raise ValueError('original interval coordinate, ordered mask and witness required')
        for value in self.fold_ids:
            require_text(value)
        if self.status=='DEFINED_EXPLORATORY':
            values=(self.estimate,self.lower,self.upper)
            if (not self.fold_ids or any(type(v) not in {int,float} or not math.isfinite(v) for v in values)
                    or self.lower>self.upper):
                raise ValueError('finite original interval bounds/estimate required')
        elif any(v is not None for v in (self.estimate,self.lower,self.upper)) or not self.reason:
            raise ValueError('unsupported intervals retain a reason, never invented numeric bounds')
