"""Adapt completed public results without reading market data or executing work."""

from collections.abc import Mapping

from quantbt.mode5.decision_report import DecisionReport

from ..access import AccessWitness


def from_result(result, *, access, source_ref, role='diagnostic_development', **options):
    from .report import ResearchDecisionReport

    if not isinstance(source_ref, str) or not source_ref.strip():
        raise ValueError('explicit original completed-result source reference required')
    metadata = getattr(result, 'metadata', None)
    if not isinstance(metadata, Mapping) or not isinstance(metadata.get('walk_forward'), Mapping):
        raise ValueError('completed public WFO result metadata required; reporting never runs a strategy')
    wf = metadata['walk_forward']
    mode = wf.get('optimization_mode')
    if mode == 'mode_4_is_only_robust':
        return ResearchDecisionReport.from_walk_forward(
            wf, access=access, source_ref=source_ref, role=role, **options)
    if mode != 'mode_5_full_robust' or not isinstance(wf.get('mode5_diagnostics_first'), Mapping):
        raise ValueError('reader supports observed Mode4/per_fold_causal or diagnostics-first Mode5 only; legacy/missing evidence is not synthesized')
    witness = options.pop('witness', None)
    if not isinstance(witness, AccessWitness):
        raise ValueError('explicit full-development AccessWitness required for Mode5; no inferred cutoff')
    if role != witness.role:
        raise ValueError('declared Mode5 reporting role differs from source witness')
    if set(options) - {'accounts', 'max_report_bytes'}:
        raise ValueError('Mode5 accepts original accounts/byte budget, not causal cohorts or prefix views')
    best = wf.get('best_trial')
    params = best.get('params') if isinstance(best, Mapping) else None
    decision = DecisionReport.read(wf['mode5_diagnostics_first'], selected_params=params)
    return ResearchDecisionReport.mode5(decision, access=access, witness=witness,
        source_ref=source_ref, **options)
