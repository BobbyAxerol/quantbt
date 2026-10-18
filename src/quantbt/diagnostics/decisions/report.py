"""Versioned additive fold/meta and Mode 5 views; no financial side effects."""

from dataclasses import asdict, dataclass
from itertools import islice
import json
import math

from quantbt.mode5.decision_report import DecisionReport
from quantbt.mode5.dossier.records import Record
from quantbt.optimization.meta_selection.common import wire

from ..access import AccessPolicy, AccessWitness
from .contracts import FoldDecisionEvidence, FoldSlot, ReportCohort, RetainedAccountReport, RetainedInterval
from .reduction import reduce_views
from .snapshots import snapshot
from .validation import validate_rows

SCHEMA='quantbt.research_decision_report.v1'
LIMITS=(
    'Cold descriptive reporting; not a selector, model, causal recipe router or deployment permission.',
    'Source-labelled provenance is not authentication against a malicious producer.',
    'Raw Sharpe differences are not clustering objectives; mean fold metrics are not a continuous account.',
    'Missing/undefined outcomes remain explicit; no positive-every-fold or OOS-greater-than-IS rule.',
    'No inference is drawn from unobserved full-pool labels or unexecuted optimizer budgets.',
    'No new confidence interval or scientific estimator is generated; retained intervals keep their original registration.',
)


def _scope(access):
    if not isinstance(access,AccessPolicy) or access.purpose not in {'diagnostic','independent_validation'}:
        raise ValueError('explicit diagnostic/validation reporting policy required; reports grant no selection rights')


def _summary(mode,payload):
    if mode=='mode4':
        validate_rows(payload)
        summary=reduce_views(payload['rows'],payload['cohorts'])
        intervals=[]
        for value in payload['intervals']:
            source=RetainedInterval(**dict(value,witness=AccessWitness(**value['witness']),fold_ids=tuple(value['fold_ids'])))
            if source.cohort not in summary['cohorts']:
                raise ValueError('interval references unknown cohort')
            comparison=summary['cohorts'][source.cohort]['comparisons'].get(source.comparison)
            if comparison is None:
                raise ValueError('unknown interval comparison')
            metric=comparison['differences'][source.metric]
            if list(source.fold_ids)!=metric['fold_ids']:
                raise ValueError('interval must bind the exact observed ordered mask')
            if source.estimate is not None and not math.isclose(source.estimate,metric['mean'],rel_tol=1e-10,abs_tol=1e-10):
                raise ValueError('retained interval point differs from current matched report mean')
            intervals.append(value)
        summary['uncertainty']=dict(status='RETAINED_ONLY' if intervals else 'NOT_SUPPLIED',coordinates=intervals,
            reason='No bootstrap/RNG/inference run by reporting; missing original registration stays unavailable.')
        summary['continuous_accounts']=payload['accounts'] or [dict(status='NOT_SUPPLIED',
            reason='No original carried account supplied. Diagnostic equity and fold Sharpe/DD are never stitched.')]
        return summary
    if payload['view']!='full_development' or payload['decision_use']!='NOT_BACKDATABLE':
        raise ValueError('full-development Mode5 evidence cannot become causal prefix evidence')
    decision=DecisionReport(Record.of(payload['mode5_snapshot']))
    value=decision.to_dict(private=True)
    runtime=value['runtime']; selected=runtime.get('decision') or {}
    witness=AccessWitness(**payload['witness'])
    first_trial=(runtime.get('chronology') or {}).get('first_trial_ns')
    if first_trial is not None and witness.ready_ns<first_trial:
        raise PermissionError('Mode5 result witness predates its original first trial')
    scope=runtime.get('account_scope')
    if scope and 'full_start_ns' in scope and 'full_stop_ns' in scope and (
            witness.start_ns>scope['full_start_ns'] or witness.end_ns<scope['full_stop_ns']):
        raise ValueError('Mode5 witness omits original full/preload scope')
    observations=[o for t in runtime['trial_ledger'] for o in t.get('observations',[])]+(runtime.get('selected_audit') or [])
    observations += [t['whole_observation'] for t in runtime['trial_ledger'] if t.get('whole_observation') is not None]
    if any(witness.start_ns>o['start_ns'] or witness.end_ns<o['stop_ns'] for o in observations if 'start_ns' in o and 'stop_ns' in o):
        raise ValueError('Mode5 source witness omits original observations')
    candidate=selected.get('chosen_candidate')
    trial=next((t for t in runtime['trial_ledger'] if t.get('candidate_id')==candidate and t.get('components') is not None),None)
    return dict(mode5_summary=value['summary'],selected_params=value['selected_params'],
        selection=dict(status=selected.get('status'),candidate_id=candidate,
            requested_selector=selected.get('requested_selector'),resolved_selector=selected.get('resolved_selector'),
            formula_version=selected.get('formula_version'),formula_identity=selected.get('formula_identity'),
            formula_coefficients=selected.get('formula_coefficients'),incumbent_guard=selected.get('incumbent_guard'),
            component_rows=selected.get('component_rows'),
            selected_components=next((r for r in selected.get('component_rows',[]) if r['candidate_id']==candidate),None)),
        selected_observation=trial.get('whole_observation') if trial else None,
        environments=trial.get('observations',[]) if trial else [],selected_audit=runtime.get('selected_audit'),
        environment_account_policy=runtime.get('environment_account_policy'),
        account_scope=runtime.get('account_scope'),annual_account_resets=runtime.get('annual_account_resets'),
        scope_availability=dict(status='OBSERVED_FULL_SCOPE' if scope and 'full_start_ns' in scope and 'full_stop_ns' in scope else 'PARTIAL_OR_NOT_SUPPLIED',
            missing_fields=[k for k in ('full_start_ns','full_stop_ns','scored_start_ns','scored_stop_ns') if k not in (scope or {})]),
        sampler=runtime['sampler'],compute_bill=runtime.get('compute_bill'),
        continuous_accounts=payload['accounts'] or [dict(status='NOT_SUPPLIED',reason='No separate original continuous MET/account report supplied; inspect original whole_observation and its contract.')],
        local_evidence=dict(status='RETAINED_COMPONENTS_ONLY',reason='Only original selector components are projected; absent winner-specific held probes remain NOT_SUPPLIED.'),
        validation_claim=runtime['validation_claim'],
        interpretation='One fixed full-development dictionary; annual attribution is dependent, not causal WFO or independent OOS.')


@dataclass(frozen=True)
class ResearchDecisionReport:
    record: Record

    @classmethod
    def from_walk_forward(cls,metadata,*,access,source_ref,role='diagnostic_development',**options):
        from .adapters import from_walk_forward
        return from_walk_forward(metadata,access=access,source_ref=source_ref,role=role,**options)

    @classmethod
    def mode4(cls,folds,*,roster,access,cohorts=(),accounts=(),intervals=(),view='post_wfo',
              max_folds=2048,max_candidates=250000,max_report_bytes=4*1024**2):
        _scope(access)
        if view=='prefix' and access.purpose!='diagnostic':
            raise PermissionError('independent validation rights cannot be converted into prefix advice')
        if (view not in {'post_wfo','prefix'} or type(max_folds) is not int or max_folds<1
                or type(max_candidates) is not int or max_candidates<1):
            raise ValueError('explicit bounded post-WFO or mature historical prefix view required')
        folds=tuple(islice(folds,max_folds+1)); roster=tuple(islice(roster,max_folds+1))
        if (len(folds)>max_folds or len(roster)>max_folds or not roster
                or any(not isinstance(f,FoldDecisionEvidence) for f in folds)
                or any(not isinstance(s,FoldSlot) for s in roster)):
            raise ValueError('typed bounded fold evidence/calendar required; no truncation')
        if not folds:
            raise ValueError('at least one original fold is required for contract identity')
        if len({s.fold_id for s in roster})!=len(roster) or any(a.stop_ns>b.start_ns for a,b in zip(roster,roster[1:])):
            raise ValueError('distinct chronological nonoverlapping forward roster required')
        byid={f.fold_id:f for f in folds}
        if len(byid)!=len(folds) or not set(byid)<={s.fold_id for s in roster}:
            raise ValueError('duplicate/unknown fold identity')
        if sum(len(f.revision.task.candidates) for f in folds)>max_candidates:
            raise ValueError('candidate input budget exceeded; no pool truncation')
        family=folds[0].revision.task.family
        if any(f.revision.task.family!=family for f in folds):
            raise ValueError('different route/schema/economics/sampler/window/metric families cannot be pooled')
        witnesses=[]; rows=[]
        for slot in roster:
            evidence=byid.get(slot.fold_id)
            if evidence is None:
                rows.append(dict(**asdict(slot),status='MISSING_FOLD_RECORD'))
                continue
            access.require(evidence.witness); witnesses.append(asdict(evidence.witness))
            if evidence.state_witness is not None:
                access.require(evidence.state_witness)
                if view=='prefix' and evidence.state_label_purpose!='decision_vintage':
                    raise PermissionError('full-development/descriptive states cannot advise a prefix')
                witnesses.append(asdict(evidence.state_witness))
            row=snapshot(evidence)
            if (row['start_ns'],row['stop_ns'])!=(slot.start_ns,slot.stop_ns):
                raise ValueError('fold/task differs from exact declared forward slot')
            rows.append(dict(row,status='OBSERVED'))
        cohorts=tuple(islice(cohorts,65))
        if len(cohorts)>64 or any(not isinstance(c,ReportCohort) for c in cohorts) or len({c.name for c in cohorts})!=len(cohorts):
            raise ValueError('distinct typed registered cohorts required')
        for cohort in cohorts:
            if not set(cohort.fold_ids)<={s.fold_id for s in roster}:
                raise ValueError('cohort references unknown calendar slots')
            if cohort.fold_ids!=tuple(s.fold_id for s in roster if s.fold_id in set(cohort.fold_ids)):
                raise ValueError('cohort mask must preserve declared calendar order')
        account_rows=cls._accounts(accounts,access,witnesses,family.family_id,
            (roster[0].start_ns,roster[-1].stop_ns))
        interval_rows=[]
        intervals=tuple(islice(intervals,385))
        if len(intervals)>384:
            raise ValueError('retained interval-coordinate budget exceeded')
        for interval in intervals:
            if not isinstance(interval,RetainedInterval):
                raise ValueError('typed original interval evidence required')
            access.require(interval.witness); witnesses.append(asdict(interval.witness))
            interval_rows.append(asdict(interval))
        payload=dict(view=view,decision_use='MATURE_HISTORICAL_ONLY' if view=='prefix' else 'NOT_BACKDATABLE',
            family=wire(family),family_id=family.family_id,rows=rows,roster=[asdict(s) for s in roster],
            cohorts=[asdict(c) for c in cohorts],accounts=account_rows,intervals=interval_rows)
        return cls._make('mode4',payload,access,witnesses,max_report_bytes)

    @classmethod
    def mode5(cls,decision,*,access,witness,source_ref,accounts=(),max_report_bytes=4*1024**2):
        _scope(access)
        if not isinstance(decision,DecisionReport) or not isinstance(witness,AccessWitness) or not isinstance(source_ref,str) or not source_ref:
            raise ValueError('original DecisionReport, source and full-development witness required')
        access.require(witness)
        original=decision.to_dict(private=True)
        runtime=original['runtime']
        observations=[o for t in runtime['trial_ledger'] for o in t.get('observations',[])]+(runtime.get('selected_audit') or [])
        observations += [t['whole_observation'] for t in runtime['trial_ledger'] if t.get('whole_observation') is not None]
        if any(witness.start_ns>o['start_ns'] or witness.end_ns<o['stop_ns'] for o in observations if 'start_ns' in o and 'stop_ns' in o):
            raise ValueError('full-development witness does not cover original Mode5 observations')
        witnesses=[asdict(witness)]
        scope=runtime.get('account_scope')
        if accounts and scope is None:
            raise ValueError('original continuous account scope required before adding Mode5 account reports')
        account_rows=cls._accounts(accounts,access,witnesses,runtime.get('runtime_binding_identity'),
            (scope['scored_start_ns'],scope['scored_stop_ns']) if scope else None)
        return cls._make('mode5',dict(view='full_development',decision_use='NOT_BACKDATABLE',
            source_ref=source_ref,witness=asdict(witness),mode5_snapshot=original,accounts=account_rows),access,witnesses,max_report_bytes)

    @staticmethod
    def _accounts(accounts,access,witnesses,family_id,scope):
        accounts=tuple(islice(accounts,5))
        if len(accounts)>4:
            raise ValueError('continuous account-report budget exceeded')
        result=[]
        for account in accounts:
            if not isinstance(account,RetainedAccountReport) or family_id is not None and account.family_id!=family_id:
                raise ValueError('original account/family mismatch')
            if scope is None or (account.start_ns,account.stop_ns)!=scope:
                raise ValueError('original continuous account scope differs from reported full calendar')
            access.require(account.witness); witnesses.append(asdict(account.witness))
            result.append(dict(family_id=account.family_id,policy=account.policy,source_ref=account.source_ref,
                witness=asdict(account.witness),metrics=account.metrics.data,units=account.units.data,
                contract_id=account.contract_id,result_identity=account.result_identity,account_policy=account.account_policy,
                start_ns=account.start_ns,stop_ns=account.stop_ns))
        if len({r['policy'] for r in result})!=len(result):
            raise ValueError('one original continuous account per declared policy required')
        return result

    @classmethod
    def _make(cls,mode,payload,access,witnesses,cap):
        if type(cap) is not int or cap<1:
            raise ValueError('positive report byte budget required')
        record=Record.of(dict(schema=SCHEMA,mode=mode,payload=payload,access_policy=asdict(access),
            source_witnesses=witnesses,summary=_summary(mode,payload),limits=list(LIMITS)))
        if len(record.payload.encode())>cap:
            raise ValueError('report byte budget exceeded; no rows truncated')
        return cls(record)

    def __post_init__(self):
        if not isinstance(self.record,Record):
            raise ValueError('immutable report Record required')
        data=self.record.data
        if (set(data)!={'schema','mode','payload','access_policy','source_witnesses','summary','limits'}
                or data['schema']!=SCHEMA or data['mode'] not in {'mode4','mode5'} or data['limits']!=list(LIMITS)):
            raise ValueError('versioned complete private decision report required')
        policy=data['access_policy']
        access=AccessPolicy(**dict(policy,roles=tuple(policy['roles']),manifests=tuple(policy['manifests'])))
        self.authorize(access)
        payload=data['payload']
        expected=([w for r in payload['rows'] if r['status']=='OBSERVED'
                   for w in ([r['witness']]+([r['state_witness']] if r['state_witness'] is not None else []))]
            if data['mode']=='mode4' else [payload['witness']])
        expected += [r['witness'] for r in payload['accounts']]
        if data['mode']=='mode4':
            expected += [r['witness'] for r in payload['intervals']]
        if expected!=data['source_witnesses']:
            raise ValueError('source witnesses cannot be removed or relabelled on reload')
        if Record.of(data['summary'])!=Record.of(_summary(data['mode'],data['payload'])):
            raise ValueError('altered report summary, masks or numeric values')

    @property
    def identity(self):
        return self.record.identity

    @classmethod
    def from_json(cls,payload,*,max_bytes=16*1024**2):
        if type(max_bytes) is not int or max_bytes<1 or not isinstance(payload,str) or len(payload.encode())>max_bytes:
            raise ValueError('bounded complete private JSON snapshot required')
        try:
            return cls(Record.of(json.loads(payload)))
        except (KeyError,TypeError,AttributeError) as exc:
            raise ValueError('complete private detail snapshot required; public/compact views are not reloadable') from exc

    def authorize(self,access):
        _scope(access)
        data=self.record.data
        if wire(asdict(access))!=data['access_policy']:
            raise PermissionError('changed access policy requires fresh report assembly')
        for witness in data['source_witnesses']:
            access.require(AccessWitness(**witness))
        return self

    def to_dict(self,*,private=False,detail=False):
        if type(private) is not bool or type(detail) is not bool:
            raise ValueError('explicit disclosure/detail booleans required')
        from .render import public_view
        data=self.record.data
        if not private:
            return public_view(data,detail=detail)
        if not detail:
            data['payload']={k:v for k,v in data['payload'].items() if k not in {'rows','mode5_snapshot'}}
        return data

    def to_json(self,*,private=False,detail=False):
        return Record.of(self.to_dict(private=private,detail=detail)).payload

    def to_markdown(self,*,private=False,detail=False):
        from .render import markdown
        return markdown(self.to_dict(private=private,detail=detail))
