"""Arithmetic explanations of recorded selection, not a second selector."""

import math

from .contracts import selected_row


MEASURES = dict(raw_sharpe='retained_sharpe_ratio', net_return='decimal_return',
    max_drawdown='decimal_drawdown', daily_loss_es='daily_loss_decimal',
    final_equity='account_currency', daily_count='daily_observations', closed_records='engine_closed_records')


def differences(winner, comparator):
    rows = []
    contract = winner.get('metric_contract')
    same = isinstance(contract, str) and bool(contract.strip()) and contract == comparator.get('metric_contract')
    for metric, unit in MEASURES.items():
        a, b = winner.get(metric), comparator.get(metric)
        valid = same and all(type(v) in {int, float} and math.isfinite(v) for v in (a, b))
        rows.append(dict(metric=metric, unit=unit, winner=a, comparator=b,
            delta=a - b if valid else None,
            reason=None if valid else 'Missing/nonfinite measure or different metric contract; no fabricated delta'))
    return rows


def compare_rows(winner, comparator, *, name, objective_comparable=True):
    if comparator is None:
        return dict(name=name, status='NOT_SUPPLIED', reason='No matching completed comparator retained')
    a, b = winner.get('objective'), comparator.get('objective')
    scores = objective_comparable and all(type(v) in {int, float} and math.isfinite(v) for v in (a, b))
    wb = {r['environment_id']: r for r in comparator['observations']}
    annual = []
    for row in winner['observations']:
        other = wb.get(row['environment_id'])
        if other is not None:
            annual.append(dict(environment_id=row['environment_id'], measures=differences(row, other),
                winner_utility=row.get('utility'), comparator_utility=other.get('utility')))
    return dict(name=name, status='RECORDED_COMPARISON', candidate_id=comparator['candidate_id'],
        same_candidate=winner['candidate_id'] == comparator['candidate_id'],
        objective_delta=a - b if scores else None,
        objective_comparable=bool(scores),
        whole=differences(winner.get('whole_observation', {}), comparator.get('whole_observation', {})),
        annual=annual, components=dict(winner=winner.get('components'), comparator=comparator.get('components')),
        limits=['Recorded selected paths are not a causal sampler or risk-allocation experiment',
                'Annual observations are dependent account attribution, not independent regimes'])


def environment_summary(row):
    if row is None:
        return dict(status='NO_SELECTION')
    result = dict(status='RECORDED_DEPENDENT_ENVIRONMENTS', environments=len(row['observations']),
        independent_replications=None, measures={})
    for metric in ('net_return', 'raw_sharpe', 'daily_loss_es', 'max_drawdown'):
        items = [(r['environment_id'], r.get(metric)) for r in row['observations']]
        valid = [(k, v) for k, v in items if type(v) in {int, float} and math.isfinite(v)]
        result['measures'][metric] = dict(unit=MEASURES[metric], supported=len(valid),
            missing=[k for k, v in items if type(v) not in {int, float} or not math.isfinite(v)],
            positive=sum(v > 0 for _, v in valid), minimum=min((v for _, v in valid), default=None),
            maximum=max((v for _, v in valid), default=None))
    utilities = [r.get('utility', {}) for r in row['observations']]
    contracts = {(m.get('metric_id'), m.get('unit')) for m in utilities}
    values = [m.get('value') for m in utilities]
    valid = [v for v in values if type(v) in {int, float} and math.isfinite(v)]
    comparable = len(contracts) == 1
    result['utility'] = dict(status='COMPARABLE_RETAINED_UNITS' if comparable else 'NOT_COMPARABLE',
        contracts=[dict(metric_id=k, unit=u) for k, u in sorted(contracts, key=str)],
        supported=len(valid), positive=sum(v > 0 for v in valid) if comparable else None,
        minimum=min(valid, default=None) if comparable else None,
        maximum=max(valid, default=None) if comparable else None,
        interpretation='Utility after registered risk preferences, not raw return or a gate requiring every year positive')
    return result


def explain(decision):
    data = decision.record.data
    row = selected_row(decision)
    choice = data['runtime'].get('decision')
    if row is None:
        return dict(status='NO_SELECTION', comparisons=[], original_decision=choice,
            sampler_effect='NOT_IDENTIFIED', inactivity_effect='NOT_IDENTIFIED')
    eligible_ids = {r['candidate_id'] for r in choice['component_rows'] if r.get('eligible') is True}
    eligible = [r for r in data['runtime']['trial_ledger'] if r['state'] == 'COMPLETE'
                and r.get('candidate_id') in eligible_ids and type(r.get('raw_sharpe')) in {int, float}]
    raw = min(eligible, key=lambda r: (-r['raw_sharpe'], r['candidate_id'])) if eligible else None
    return dict(status='RECORDED_DECISION', original_decision=choice,
        comparisons=[compare_rows(row, selected_row(decision, data['summary']['runner_up_candidate'])
            if data['summary']['runner_up_candidate'] is not None else None,
            name='recorded_score_runner_up'), compare_rows(row, raw, name='same_pool_eligible_raw_sharpe_best')],
        sampler_effect='NOT_IDENTIFIED', risk_allocation_effect='NOT_IDENTIFIED',
        inactivity_effect='MEASURE_ACCOUNT_EXPOSURE_NOT_RAW_SHARPE',
        limits=['Same-pool raw-best is not the old legacy plateau policy or a new optimizer baseline',
                'Keep original incumbent guard, tie-break, objective/reference and eligibility; do not rerank here'])
