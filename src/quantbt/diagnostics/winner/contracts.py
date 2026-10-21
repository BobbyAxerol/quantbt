"""Explicit, source-bound evidence requests for an already selected winner."""

from dataclasses import dataclass
import math

from quantbt.mode5.decision_report import DecisionReport
from quantbt.mode5.dossier.records import Record, require_text

from ..access import AccessWitness
from ..calibration.worksheet import verify_sources


def selected_row(decision, candidate_id=None):
    data = decision.record.data
    candidate_id = candidate_id or data['summary']['chosen_candidate']
    return next((row for row in data['runtime']['trial_ledger']
        if candidate_id is not None and row.get('candidate_id') == candidate_id
        and row['state'] == 'COMPLETE'), None)


def winner_subject(decision):
    """Bind external checks to this run, exact winner, scope and original marks."""
    if not isinstance(decision, DecisionReport):
        raise TypeError('original validated DecisionReport required')
    data = decision.record.data
    row = selected_row(decision)
    if row is None:
        raise ValueError('NO_SELECTION has no winner evidence subject')
    runtime = data['runtime']
    return dict(decision_id=runtime['selection_decision_id'],
        dossier_id=runtime['dossier_id'], plan_id=runtime['calibration_plan_id'],
        binding_id=runtime['runtime_binding_identity'], candidate_id=row['candidate_id'],
        params_digest=runtime['selected_params_digest'],
        account_scope=runtime.get('account_scope'),
        whole_observation_id=Record.of(row.get('whole_observation', {})).identity,
        annual_observations_id=Record.of(dict(rows=row['observations'])).identity)


@dataclass(frozen=True)
class WinnerEvidence:
    """An exact catalog ref, not an unverified claim or permission to execute."""

    ref: Record

    @classmethod
    def at(cls, ref):
        return cls(Record.of(ref))

    def read(self, *, decision, catalog, access):
        verify_sources(catalog, access)
        ref = self.ref.data
        source = next(s for s in catalog.manifest.data['sources'] if s['source_id'] == ref['source'])
        access.require(AccessWitness(**source['witness']))
        value = catalog.require_ref(ref)
        if (set(value) != {'schema', 'subject', 'kind', 'measurements', 'support', 'design', 'limitations'}
                or value['schema'] != 'quantbt.mode5.winner_evidence.v1'
                or value['subject'] != winner_subject(decision)
                or value['kind'] not in {'local_probes', 'execution_stress'}):
            raise ValueError('exact original winner/run subject and typed evidence kind required')
        if not isinstance(value['support'], dict) or not isinstance(value['design'], dict):
            raise ValueError('explicit support and probe/stress design required')
        design = value['design']
        if design.get('center_candidate_id') != value['subject']['candidate_id']:
            raise ValueError('diagnostic centers do not certify another formal winner')
        if value['kind'] == 'local_probes':
            if design.get('role') not in {'selection_probes', 'held_validation_probes'}:
                raise ValueError('selection/held probe role must remain explicit')
            for key in ('expected_probes', 'observed_probes'):
                if type(value['support'].get(key)) is not int or value['support'][key] < 0:
                    raise ValueError('exact registered/observed probe support required')
            if value['support']['observed_probes'] > value['support']['expected_probes']:
                raise ValueError('probe support exceeds registered design')
            for key in ('requested_radius', 'observed_radius'):
                if type(design.get(key)) not in {int, float} or not math.isfinite(design[key]) or design[key] < 0:
                    raise ValueError('finite explicit requested/observed probe radius required')
        else:
            require_text(design.get('execution_ref'))
            require_text(design.get('scenario'))
        if not isinstance(value['measurements'], list) or not value['measurements']:
            raise ValueError('recorded winner measurements required')
        for measure in value['measurements']:
            if set(measure) != {'metric', 'unit', 'value', 'sample_count', 'reason'}:
                raise ValueError('metric unit, support and undefined reason required')
            for key in ('metric', 'unit'):
                require_text(measure[key])
            if type(measure['sample_count']) is not int or measure['sample_count'] < 0:
                raise ValueError('nonnegative exact measurement support required')
            if measure['value'] is None:
                require_text(measure['reason'])
            elif (type(measure['value']) not in {int, float}
                    or not math.isfinite(measure['value']) or measure['reason'] is not None):
                raise ValueError('finite measurement or explicit undefined reason required')
        if not isinstance(value['limitations'], list):
            raise ValueError('evidence limitations required')
        for limitation in value['limitations']:
            require_text(limitation)
        return dict(ref=ref, source_witness=source['witness'], evidence=value,
            status='RECORDED_WINNER_CHECK', basin_certified=False)


@dataclass(frozen=True)
class WinnerBaseline:
    """Original completed baseline plus the current source-bound run pack."""

    decision: DecisionReport
    pack: object
    dossier: object
    catalog: object
    access: object
    source_ref: str
    archive_access: object = None
    result: object = None

    def verify(self):
        require_text(self.source_ref)
        self.pack.verify(dossier=self.dossier, catalog=self.catalog, access=self.access,
            archive_access=self.archive_access)
        runtime = self.decision.record.data['runtime']
        if (runtime['calibration_plan_id'] != self.pack.record.data['plan_id']
                or runtime['runtime_binding_identity'] != self.pack.record.data['binding_id']
                or runtime['dossier_id'] != self.dossier.record.identity):
            raise ValueError('baseline must belong to its original source-bound pack')
        if self.result is not None:
            wf = getattr(self.result, 'metadata', {}).get('walk_forward', {})
            actual = DecisionReport.read(wf.get('mode5_diagnostics_first', {}),
                selected_params=wf.get('best_trial', {}).get('params'))
            if actual != self.decision:
                raise ValueError('baseline result is not its original completed decision')
        return self


@dataclass(frozen=True)
class WinnerQualificationRequest:
    """Opt-in cold work; no search, replay, model fit or automatic recipe choice."""

    evidence: tuple[WinnerEvidence, ...] = ()
    catalog: object = None
    state_views: tuple = ()
    include_account: bool = True
    baseline: WinnerBaseline | None = None
    current: WinnerBaseline | None = None
    max_report_bytes: int = 16 * 1024 * 1024

    def __post_init__(self):
        if (type(self.include_account) is not bool or type(self.evidence) is not tuple
                or any(not isinstance(e, WinnerEvidence) for e in self.evidence)
                or len(self.evidence) > 32 or type(self.state_views) is not tuple
                or type(self.max_report_bytes) is not int or not 1 <= self.max_report_bytes <= 16 * 1024 * 1024):
            raise ValueError('typed bounded explicit winner qualification request required')
        if self.evidence and self.catalog is None:
            raise ValueError('evidence requires its verified catalog')
        if self.state_views and not self.include_account:
            raise ValueError('state attribution requires the original selected account')
        if self.baseline is not None and self.current is None:
            raise ValueError('matched baseline needs the current original pack/context too')
        if any(value is not None and not isinstance(value, WinnerBaseline) for value in (self.current, self.baseline)):
            raise TypeError('typed original baseline/current contexts required')
