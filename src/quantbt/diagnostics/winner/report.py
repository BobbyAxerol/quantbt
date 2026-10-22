"""Immutable, bounded winner dossier on the existing completed-result path."""

from dataclasses import asdict, dataclass
import json

from quantbt.mode5.decision_report import DecisionReport
from quantbt.mode5.dossier.records import Record, require_text

from ..access import AccessPolicy, AccessWitness
from .accounts import profile_selected_account
from .contracts import WinnerQualificationRequest, selected_row, winner_subject
from .explanation import compare_rows, environment_summary, explain


def _baseline(request, decision, *, access, profile):
    if request.current is not None:
        request.current.authorize(access)
        if request.current.decision != decision:
            raise ValueError('current baseline context does not belong to this actual decision')
    if request.baseline is None:
        return dict(status='NOT_SUPPLIED', reason='No original source-bound baseline supplied')
    current, baseline = request.current, request.baseline.authorize(access)
    a, b = current.dossier.record.data['context'], baseline.dossier.record.data['context']
    if any(a[key] != b[key] for key in ('alpha', 'data', 'economics', 'schema', 'roles', 'metrics')):
        raise ValueError('baseline alpha/market/economics/schema/roles/metric context differs')
    x, y = current.pack.record.data, baseline.pack.record.data
    # Warm starts and sampler may differ. Financial and measurement semantics may not.
    for key in ('geometry', 'source', 'execution', 'witness', 'start_ns', 'stop_ns',
                'quality_floor_comparison', 'eligibility_policy'):
        if x['binding']['continuous'].get(key) != y['binding']['continuous'].get(key):
            raise ValueError('baseline financial/measurement contract differs: ' + key)
    if any(x['binding'][key] != y['binding'][key] for key in ('metrics', 'windows')):
        raise ValueError('baseline metric/window contract differs')
    same_objective = (x['plan']['recipe']['objective'] == y['plan']['recipe']['objective']
        and x['plan']['recipe']['selector'] == y['plan']['recipe']['selector']
        and x['binding']['reference'] == y['binding']['reference']
        and x['binding']['selection'] == y['binding']['selection'])
    winner, control = selected_row(decision), selected_row(baseline.decision)
    if winner is None or control is None:
        return dict(status='NO_PAIRED_SELECTION', baseline_source_ref=baseline.source_ref,
            baseline_decision=baseline.decision.record.data)
    baseline_activity = dict(status='NOT_SUPPLIED', reason='Original baseline account not supplied')
    activity_delta = None
    if baseline.result is not None:
        baseline_profile = profile_selected_account(baseline.result, control['whole_observation'],
            access=access, witness=AccessWitness(**y['binding']['continuous']['witness']),
            source_ref=baseline.source_ref)
        baseline_activity = dict(status='MATCHED_ORIGINAL_ACCOUNT', profile=baseline_profile)
        if profile['status'] == 'MATCHED_ORIGINAL_ACCOUNT':
            winner_activity = profile['profile']['activity']
            other = baseline_profile['activity']
            activity_delta = {key: dict(winner=winner_activity.get(key), baseline=other.get(key),
                delta=winner_activity[key] - other[key]
                    if winner_activity.get(key) is not None and other.get(key) is not None else None,
                unit=unit) for key, unit in (
                    ('exposure_fraction', 'occupied_close_mark_fraction'), ('net_pnl', 'account_currency'),
                    ('fees', 'account_currency'), ('funding', 'account_currency'),
                    ('engine_closed_records', 'engine_closed_records'))}
    return dict(status='SOURCE_BOUND_SELECTED_PATHS', baseline_source_ref=baseline.source_ref,
        baseline_decision=baseline.decision.record.data,
        current_pack_id=current.pack.identity, baseline_pack_id=baseline.pack.identity,
        comparison=compare_rows(winner, control, name='registered_completed_baseline',
            objective_comparable=same_objective),
        current_sampler=x['binding']['sampler'], baseline_sampler=y['binding']['sampler'],
        same_trial_budget=x['plan']['search_budget'] == y['plan']['search_budget'],
        current_seed=x['plan']['recipe']['sampler']['seeds'][0],
        baseline_seed=y['plan']['recipe']['sampler']['seeds'][0],
        same_seed=x['plan']['recipe']['sampler']['seeds'] == y['plan']['recipe']['sampler']['seeds'],
        current_warm_start_count=len(x['binding']['warm_start']),
        baseline_warm_start_count=len(y['binding']['warm_start']),
        baseline_activity=baseline_activity, measured_activity_comparison=activity_delta,
        causal_sampler_effect='NOT_IDENTIFIED_BY_ONE_SELECTED_PAIR')


def _coverage(decision, profile, attachments, baseline):
    row = selected_row(decision)
    present = {a['evidence']['kind'] for a in attachments}
    states = profile.get('state_families', [])
    return [dict(section=name, status='RECORDED' if ok else 'NOT_SUPPLIED',
        support=support, limitation=limit) for name, ok, support, limit in (
        ('whole', row is not None and row.get('whole_observation') is not None,
            1 if row is not None and row.get('whole_observation') else 0, 'Whole path is development calibration, not independent OOS'),
        ('annual', row is not None, len(row['observations']) if row else 0,
            'Dependent calendar views, not market-regime classification'),
        ('activity_exposure', profile.get('status') == 'MATCHED_ORIGINAL_ACCOUNT',
            profile.get('status'), 'Close-mark exposure is not fills, campaigns or opportunity-normalized activity'),
        ('regime', bool(states), len(states), 'Caller supplies state families with their own source/fit/availability rights; no labels inferred'),
        ('tail_drawdown', row is not None, 1 if row else 0, 'Copy original ES/DD convention; no new estimator'),
        ('local_probes', 'local_probes' in present,
            [a['evidence']['support'] for a in attachments if a['evidence']['kind'] == 'local_probes'],
            'Observed finite neighbors do not by themselves certify an entire basin'),
        ('execution_stress', 'execution_stress' in present,
            [a['evidence']['support'] for a in attachments if a['evidence']['kind'] == 'execution_stress'],
            'Only the recorded exact-winner scenarios are covered'),
        ('registered_baseline', baseline['status'] == 'SOURCE_BOUND_SELECTED_PATHS',
            baseline['status'], 'Same-pool raw-best and score runner-up are reported separately'))]


@dataclass(frozen=True)
class WinnerQualificationReport:
    record: Record

    @classmethod
    def build(cls, decision, *, access, witness, source_ref, request=None, result=None):
        request = WinnerQualificationRequest() if request is None else request
        if not isinstance(request, WinnerQualificationRequest) or not isinstance(decision, DecisionReport):
            raise TypeError('typed original decision and qualification request required')
        if not isinstance(access, AccessPolicy) or access.purpose != 'diagnostic' or not isinstance(witness, AccessWitness):
            raise PermissionError('current diagnostic rights and original full-development witness required')
        access.require(witness)
        require_text(source_ref)
        runtime = decision.record.data['runtime']
        if runtime.get('environment_account_policy') != 'CONTINUOUS_PATH_ATTRIBUTION':
            raise ValueError('winner qualification requires original continuous Mode5 account attribution')
        if result is not None:
            wf = getattr(result, 'metadata', {}).get('walk_forward', {})
            actual = DecisionReport.read(wf.get('mode5_diagnostics_first', {}),
                selected_params=wf.get('best_trial', {}).get('params'))
            if actual != decision:
                raise ValueError('current result is not the original completed decision')
        scope = runtime.get('account_scope')
        if scope is not None and (witness.start_ns > scope['scored_start_ns'] or witness.end_ns < scope['scored_stop_ns']):
            raise PermissionError('witness must cover the original scored account scope')
        row = selected_row(decision)
        if row is None and (request.evidence or request.state_views):
            raise ValueError('NO_SELECTION cannot have winner checks or regime attribution')
        attachments = [e.read(decision=decision, catalog=request.catalog, access=access) for e in request.evidence]
        refs = [Record.of(a['ref']).identity for a in attachments]
        if len(refs) != len(set(refs)):
            raise ValueError('duplicate winner evidence reference')
        profile = dict(status='NOT_SUPPLIED', reason='Original account not supplied or account profiling not requested')
        if row is not None and request.include_account and result is not None:
            if row.get('whole_observation') is None:
                raise ValueError('continuous original whole_observation required for account profiling')
            profile = profile_selected_account(result, row['whole_observation'], access=access,
                witness=witness, source_ref=source_ref, state_views=request.state_views)
            profile = dict(status='MATCHED_ORIGINAL_ACCOUNT', profile=profile,
                state_families=profile.get('states', {}).get('families', []))
        baseline = _baseline(request, decision, access=access, profile=profile)
        data = dict(schema='quantbt.mode5.winner_qualification.v1',
            original_decision=decision.record.data, subject=winner_subject(decision) if row else None,
            source_ref=source_ref, access=asdict(access), witness=asdict(witness),
            account=profile, checks=attachments, baseline=baseline,
            explanation=explain(decision),
            annual_summary=environment_summary(row),
            coverage=_coverage(decision, profile, attachments, baseline),
            authority=dict(opt_in=True, automatic_routing=False, default_changed=False,
                deployment_authorized=False, independent_oos_claim=False),
            limits=['No universal claim that a sampler, selector or cross-mode assistance wins',
                'Diagnostic rights do not authorize backdated Mode4 selection',
                'Missing evidence remains missing; reporting never executes missing probes or stress'])
        report = cls(Record.of(data))
        if len(report.record.payload.encode()) > request.max_report_bytes:
            raise ValueError('winner report byte budget exceeded; evidence is not silently truncated')
        return report

    def __post_init__(self):
        data = self.record.data
        expected = {'schema', 'original_decision', 'subject', 'source_ref', 'access', 'witness',
            'account', 'checks', 'baseline', 'explanation', 'annual_summary', 'coverage', 'authority', 'limits'}
        if set(data) != expected or data['schema'] != 'quantbt.mode5.winner_qualification.v1':
            raise ValueError('complete immutable winner qualification report required')
        decision = DecisionReport(Record.of(data['original_decision']))
        if decision.record.data['runtime'].get('environment_account_policy') != 'CONTINUOUS_PATH_ATTRIBUTION':
            raise ValueError('original continuous Mode5 attribution required')
        row = selected_row(decision)
        if (data['subject'] != (winner_subject(decision) if row else None)
                or data['explanation'] != explain(decision)
                or data['annual_summary'] != environment_summary(row)):
            raise ValueError('winner identity/explanation differs from original decision')
        access = AccessPolicy(**{**data['access'], 'roles': tuple(data['access']['roles']),
            'manifests': tuple(data['access']['manifests'])})
        if access.purpose != 'diagnostic':
            raise PermissionError('diagnostic rights required')
        access.require(AccessWitness(**data['witness']))
        for check in data['checks']:
            if check['evidence']['subject'] != data['subject'] or check['basin_certified'] is not False:
                raise ValueError('retained checks must bind the exact winner without basin certification')
            access.require(AccessWitness(**check['source_witness']))
        if data['coverage'] != _coverage(decision, data['account'], data['checks'], data['baseline']):
            raise ValueError('coverage does not reconcile with retained evidence')
        if data['authority'] != dict(opt_in=True, automatic_routing=False, default_changed=False,
                deployment_authorized=False, independent_oos_claim=False):
            raise ValueError('winner report cannot change execution authority')
        if len(self.record.payload.encode()) > 16 * 1024 * 1024:
            raise ValueError('winner report exceeds bounded snapshot')

    @property
    def identity(self):
        return self.record.identity

    @classmethod
    def from_json(cls, payload, *, expected_identity):
        """A retained snapshot is not renewed source access; verify by rebuilding."""
        if type(payload) is not str or len(payload.encode()) > 16 * 1024 * 1024:
            raise ValueError('bounded complete private winner snapshot required')
        def unique(pairs):
            result = {}
            for name, value in pairs:
                if name in result:
                    raise ValueError('duplicate winner report JSON key')
                result[name] = value
            return result
        report = cls(Record.of(json.loads(payload, object_pairs_hook=unique)))
        if report.identity != expected_identity:
            raise ValueError('winner report differs from independently retained expected identity')
        return report

    def verify(self, decision, **inputs):
        if self != type(self).build(decision, **inputs):
            raise ValueError('winner snapshot differs from current source-bound evidence')
        return self

    def to_dict(self, *, private=False):
        if type(private) is not bool:
            raise ValueError('private disclosure requires an explicit boolean')
        data = self.record.data
        if private:
            return data
        return dict(schema='quantbt.mode5.winner_qualification.public.v1',
            original_decision=DecisionReport(Record.of(data['original_decision'])).to_dict(),
            coverage=[dict(section=r['section'], status=r['status']) for r in data['coverage']],
            registered_baseline_supplied=data['baseline']['status'] != 'NOT_SUPPLIED',
            exact_winner_check_count=len(data['checks']), authority=data['authority'])

    def to_json(self, *, private=False):
        return Record.of(self.to_dict(private=private)).payload

    def to_markdown(self, *, private=False):
        from .render import render
        return render(self, private=private)
