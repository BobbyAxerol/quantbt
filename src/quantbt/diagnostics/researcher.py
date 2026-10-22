"""Optional shared pre-search view; no execution, training, selection or RNG."""

from dataclasses import asdict

from quantbt.mode5.dossier.evidence import KINDS

from .account_profile import account_profile
from .analysis_profile import analysis_profiles
from .identity import digest
from .interpretation import explanations, recipe_cards
from .research_contracts import DiagnosticResearch
from .search_profile import search_profile


def require_research(owner, rows, research):
    if not isinstance(research, DiagnosticResearch) or research.context_id != owner.context.identity:
        raise ValueError('matching typed research context required')
    owner.access.require(research.witness)
    byid = {row.evaluation_id:row for row in rows}
    if len(research.trials)>owner.budget.max_observations or len(research.accounts)>owner.budget.max_observations:
        raise ValueError('research input budget exceeded; no ledger truncation')
    for row in rows:
        if (row.witness.start_ns<research.witness.start_ns or row.witness.end_ns>research.witness.end_ns
                or row.witness.manifest_id!=research.witness.manifest_id
                or row.witness.role!=research.witness.role):
            raise ValueError('observations outside declared research window/manifest')
    for trial in research.trials:
        if trial.evaluation_id is not None and trial.evaluation_id not in byid:
            raise ValueError('attempt references an unknown observation')
        if trial.status=='COMPLETE' and byid[trial.evaluation_id].status not in {'COMPLETE','NO_TRADE'}:
            raise ValueError('complete trial cannot reference a failed financial observation')
    used = 0
    for account in research.accounts:
        row=byid.get(account.evaluation_id)
        if row is None or account.observation_identity!=digest(asdict(row)):
            raise ValueError('account bound to a different observation/schema/metric/window')
        if row.status not in {'COMPLETE','NO_TRADE'}:
            raise ValueError('failed or infeasible observations cannot supply qualified account profiles')
        owner.access.require(account.evidence.witness)
        if account.evidence.witness!=row.witness:
            raise ValueError('account and observation require the exact same role/window/manifest')
        if account.labels is not None:
            owner.access.require(account.label_witness)
            if account.label_witness.start_ns>row.witness.start_ns or account.label_witness.end_ns<row.witness.end_ns:
                raise ValueError('label witness does not cover actual account window')
            if research.view=='prefix' and account.label_purpose!='decision_vintage':
                raise PermissionError('full-development fitted labels cannot advise a prefix decision')
        used += account.evidence.size_bytes + (len(account.labels.data) if account.labels is not None else 0)
    if used>owner.budget.max_account_bytes:
        raise ValueError('retained account byte budget exceeded; no paths dropped')


def assemble_research(owner, rows, research, optional, compatibility, advice, associations):
    search=search_profile(owner,rows,research)
    accounts=[account_profile(a,owner.access) for a in research.accounts]
    matrices={kind:dict(status='NOT_SUPPLIED',row_count=None,
        reason='No compatible source-bound dossier supplied; no missing experiment is executed.') for kind in KINDS}
    matrices['parameter_representation']=dict(status='OBSERVED_SCHEMA_AND_POINTS',
        row_count=len(search['axes']),reason='Schema/support only; no behavioral or sensitivity claim.')
    if research.dossier is not None:
        dossier=research.dossier.record.data
        matrices={kind:dict(status='VERIFIED_RETAINED_MATRIX',
            row_count=len(dossier['matrices'][kind]['rows']),
            roster_id=dossier['matrices'][kind]['roster_id'],
            dossier_id=research.dossier.record.identity,
            reason='Existing Dossier/Matrix owner reverified; not recomputed.') for kind in KINDS}
    return dict(schema='quantbt.presearch_researcher.v1',view=research.view,
        decision_use='PERMITTED_PREFIX_ONLY' if research.view=='prefix' else 'NOT_BACKDATABLE',
        input_identity=research.identity,
        provenance=dict(context_id=owner.context.identity,geometry_id=owner.geometry.identity,
            route_id=owner.context.route_id,economics_id=owner.context.economics_id,
            metric_units=dict(owner.context.metric_units),cutoff_ns=owner.access.cutoff_ns,
            witness=asdict(research.witness),source_ref=research.source_ref,
            scope_unit='one declared context/window; not independent origins'),
        dossier_geometry_binding=research.dossier_geometry_ref.data if research.dossier_geometry_ref is not None else None,
        search=search,accounts=accounts,matrices=matrices,
        findings=explanations(search,accounts,optional,associations),
        analysis_profiles=analysis_profiles(owner,rows,optional),
        recipe_options=recipe_cards(compatibility,advice,optional,search),
        additional_source_witnesses=[asdict(a.label_witness) for a in research.accounts if a.label_witness is not None],
        limitations=['Full-development and retrospective reports cannot be used as earlier causal decision inputs.',
            'A report is producer-bound metadata, not authentication against a malicious producer.',
            'No alpha-name classifier, auto recipe router, parameter deletion, objective/metric change or financial approval.',
            'Sparse/flat, adverse, bankrupt and missing states are retained, not mapped to a favorable or unfavorable sentinel.'])
