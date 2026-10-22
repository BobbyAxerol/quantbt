"""Descriptive fold statistics on explicit masks, not a new scoring objective."""

from collections import Counter
import math

import numpy as np

from .effects import worst_fraction

POLICIES=('native','proposed','applied')
EFFECTS=('R','Q','IS_contribution','anchor_decay','selected_decay')


def describe(values):
    data=np.asarray(values,dtype=float)
    if data.ndim!=1 or not np.isfinite(data).all():
        raise ValueError('finite one-dimensional observed population required')
    n=len(data)
    negative=data[data<0]
    return dict(status='OBSERVED' if n else 'NOT_OBSERVED',count=n,
        mean=float(data.mean()) if n else None,median=float(np.median(data)) if n else None,
        sample_std=float(data.std(ddof=1)) if n>1 else None,
        minimum=float(data.min()) if n else None,maximum=float(data.max()) if n else None,
        q05=float(np.quantile(data,.05)) if n else None,q95=float(np.quantile(data,.95)) if n else None,
        positive=int(np.count_nonzero(data>0)),negative=len(negative),zero=int(np.count_nonzero(data==0)),
        positive_magnitude=float(data[data>0].sum()) if n else None,
        negative_magnitude=float(-negative.sum()) if n else None,
        mean_negative=float(negative.mean()) if len(negative) else None,
        mean_worst_20pct=worst_fraction(data) if n>=10 else None,
        worst_20pct_status='DEFINED' if n>=10 else 'INSUFFICIENT_FOLDS',
        convention='equal observed origin; sample std ddof=1; linear quantiles; fractional empirical worst20% requires n>=10')


def _rate(n,d):
    return n/d if d else None


def policy_summary(rows,policy,mask):
    mask=set(mask)
    selected=[row for row in rows if row['fold_id'] in mask]
    present=[r for r in selected if r['status']=='OBSERVED' and r['policies'][policy]['evaluation_id'] is not None]
    present_ids={r['fold_id'] for r in present}
    valid=[r for r in present if r['policies'][policy]['measurement_status']=='VALID']
    populations={k:[r for r in present if r['policies'][policy]['effect'][k] is not None] for k in EFFECTS}
    metrics={k:dict(describe([r['policies'][policy]['effect'][k] for r in data]),
        fold_ids=[r['fold_id'] for r in data]) for k,data in populations.items()}
    own_forward=[r for r in present if r['policies'][policy]['observations']['selected_forward']['status']=='VALID']
    sharpe=describe([r['policies'][policy]['observations']['selected_forward']['raw_sharpe'] for r in own_forward])
    activity=[r for r in present if r['policies'][policy]['observations']['selected_forward'].get('activity_count') is not None]
    supplemental={}
    keys=set().union(*(set(r['policies'][policy]['extra_metrics']['values'])
        for r in present if r['policies'][policy]['extra_metrics'] is not None))
    for key in sorted(keys):
        source=[r for r in present if r['policies'][policy]['extra_metrics'] is not None
            and r['policies'][policy]['extra_metrics']['values'].get(key) is not None]
        units={r['policies'][policy]['extra_metrics']['units'][key] for r in source}
        if len(units)>1:
            raise ValueError('supplemental metric units cannot be pooled: '+key)
        supplemental[key]=dict(unit=next(iter(units)) if units else None,
            fold_ids=[r['fold_id'] for r in source],statistics=describe([
                r['policies'][policy]['extra_metrics']['values'][key] for r in source]))
    returns=supplemental.get('net_return')
    for key in ('net_return','max_drawdown','exposure_fraction','fees','funding','fill_count',
                'closed_action_count','closed_campaign_count'):
        supplemental.setdefault(key,dict(unit=None,fold_ids=[],statistics=describe([]),reason='No original metric supplied; not inferred from Sharpe or position regimes.'))
    predictions=[r for r in populations['Q'] if r['model_ready'] and r['policies'][policy]['prediction'] is not None
        and r['policies'][policy]['prediction'].get('yhat') is not None]
    y_predictions=[r for r in predictions if r['policies'][policy]['effect']['R'] is not None]
    q_errors=[r['policies'][policy]['prediction']['qhat']-r['policies'][policy]['effect']['Q'] for r in predictions]
    y_errors=[r['policies'][policy]['prediction']['yhat']+r['policies'][policy]['effect']['R'] for r in y_predictions]
    accepted=[r for r in predictions if r['policies'][policy]['prediction'].get('eligible') is True]
    harmed=sum(r['policies'][policy]['effect']['Q']<0 for r in accepted)
    severe=sum(r['policies'][policy]['effect']['Q']<-.1 for r in accepted)
    below=sum(r['policies'][policy]['effect']['Q']<r['policies'][policy]['guard_floor']
        for r in accepted if r['policies'][policy]['guard_floor'] is not None)
    with_floor=sum(r['policies'][policy]['guard_floor'] is not None for r in accepted)
    stats=metrics['Q']
    witnessed=[r['policies'][policy]['opportunity'] for r in present
        if r['policies'][policy]['opportunity'] is not None
        and r['policies'][policy]['opportunity']['status']=='OBSERVED_FIXED_BASE_PANEL'
        and r['policies'][policy]['opportunity']['winner_preexisting_forward'] is not None]
    gaps=[v['best_forward']-v['winner_preexisting_forward'] for v in witnessed]
    return dict(calendar_count=len(selected),observed_decisions=len(present),
        missing_fold_ids=[r['fold_id'] for r in selected if r['status']!='OBSERVED'],
        missing_policy_ids=[r['fold_id'] for r in selected if r['fold_id'] not in present_ids],
        paired_effect_fold_ids=[r['fold_id'] for r in valid],
        missing_or_undefined_effects=len(selected)-len(valid),
        missing_effect_statuses=dict(Counter('|'.join(k+':'+v for k,v in sorted(r['policies'][policy]['missing_operands'].items())) for r in present
            if r['policies'][policy]['measurement_status']!='VALID')),
        model_ready=sum(r['model_ready'] for r in present),
        changed_ids=sum(not r['policies'][policy]['same_id'] for r in present),
        changed_effective=sum(not r['policies'][policy]['same_effective'] for r in present),
        effects=metrics,helped=stats['positive'],harmed=stats['negative'],tied=stats['zero'],
        matched_decomposition=dict(fold_ids=[r['fold_id'] for r in valid],
            means={k:float(np.mean([r['policies'][policy]['effect'][k] for r in valid])) if valid else None
                for k in ('R','Q','IS_contribution')},
            interpretation='Identity checked on this shared four-operand mask only; own-mask means may differ.'),
        q_help_rate=_rate(stats['positive'],stats['count']),r_improvement_rate=_rate(metrics['R']['positive'],metrics['R']['count']),
        help_definition='Q sign; R sign reported separately. Missing/undefined effects are neither help, harm nor tie.',
        positive_forward_sharpe=dict(fold_ids=[r['fold_id'] for r in own_forward],
            positive=sharpe['positive'],defined=sharpe['count'],rate=_rate(sharpe['positive'],sharpe['count']),statistics=sharpe),
        positive_forward_return=dict(positive=returns['statistics']['positive'] if returns else 0,
            defined=returns['statistics']['count'] if returns else 0,
            rate=_rate(returns['statistics']['positive'],returns['statistics']['count']) if returns else None,
            fold_ids=returns['fold_ids'] if returns else [],reason=None if returns else 'No original net account return supplied.'),
        activity=dict(unit='original_metric_contract_activity_count_not_fills_or_closed_actions',
            fold_ids=[r['fold_id'] for r in activity],statistics=describe([
                r['policies'][policy]['observations']['selected_forward']['activity_count'] for r in activity])),
        supplemental=supplemental,
        prediction=dict(fold_ids=[r['fold_id'] for r in predictions],count=len(predictions),
            y_fold_ids=[r['fold_id'] for r in y_predictions],y_count=len(y_predictions),
            q_mse=float(np.mean(np.square(q_errors))) if q_errors else None,
            y_mse=float(np.mean(np.square(y_errors))) if y_errors else None,
            q_mae=float(np.mean(np.abs(q_errors))) if q_errors else None,
            q_signed_bias=float(np.mean(q_errors)) if q_errors else None,
            errors_not_independent=True,definition='Y=-R; Qhat=deltaIS-Yhat. Paired Y/Q errors are algebraically linked, not independent tests.'),
        guard=dict(accepted_defined_count=len(accepted),accepted_negative_q=harmed,
            accepted_negative_q_rate=_rate(harmed,len(accepted)),observed_floor_count=with_floor,
            accepted_q_below_minus_0_1=severe,accepted_q_below_minus_0_1_rate=_rate(severe,len(accepted)),
            accepted_below_original_floor=below,accepted_below_original_floor_rate=_rate(below,with_floor),
            accepted_fold_ids=[r['fold_id'] for r in accepted],
            interpretation='Observed selected accepted predictions; never a guarantee on realized forward outcomes.'),
        witnessed_opportunity=dict(status='OBSERVED_FIXED_PANEL' if witnessed else 'NOT_SUPPLIED_OR_UNDEFINED',
            observed_origins=len(witnessed),members=[v['members'] for v in witnessed],
            valid_members=[v['valid'] for v in witnessed],better_observed_base_candidate=sum(g>0 for g in gaps),
            mean_positive_headroom=float(np.mean(np.maximum(gaps,0))) if gaps else None,
            full_pool_oracle=False,
            interpretation='Only original preexisting acquired base panel plus anchor; missing labels and unqueried full-pool outcomes remain unknown.'),
        interpretation='Fold diagnostic population; mean Sharpe/DD/return is not a continuous account metric.')


def paired_summary(rows,treatment,comparator,mask):
    mask=set(mask)
    selected=[r for r in rows if r['fold_id'] in mask]
    populations={key:[r for r in selected if r['status']=='OBSERVED' and all(
        r['policies'][p]['effect'] is not None and r['policies'][p]['effect'][key] is not None
        for p in (treatment,comparator))] for key in EFFECTS}
    valid=[r for r in selected if r['status']=='OBSERVED' and all(
        r['policies'][p]['measurement_status']=='VALID' for p in (treatment,comparator))]
    valid_ids={r['fold_id'] for r in valid}
    out={key:dict(describe([r['policies'][treatment]['effect'][key]-r['policies'][comparator]['effect'][key]
        for r in data]),fold_ids=[r['fold_id'] for r in data]) for key,data in populations.items()}
    return dict(treatment=treatment,comparator=comparator,calendar_count=len(selected),
        paired_fold_ids=[r['fold_id'] for r in valid],unpaired_fold_ids=[r['fold_id'] for r in selected if r['fold_id'] not in valid_ids],
        differences=out,
        matched_levels={p:{key:describe([r['policies'][p]['effect'][key] for r in valid])
            for key in EFFECTS} for p in (treatment,comparator)},
        helped=out['Q']['positive'],harmed=out['Q']['negative'],tied=out['Q']['zero'],
        interpretation='Same-origin intersection, not subtraction of own-mask means; no fabricated uncertainty.')


def turnover(rows,policy):
    observations=[]
    missing=0
    for a,b in zip(rows,rows[1:]):
        if any(r['status']!='OBSERVED' or r['policies'][policy]['params'] is None for r in (a,b)):
            missing+=1
            continue
        pa,pb=(r['policies'][policy]['params'] for r in (a,b))
        changes=[key for key in sorted(set(pa)|set(pb)) if (key in pa)!=(key in pb) or pa.get(key)!=pb.get(key)]
        observations.append(dict(from_fold=a['fold_id'],to_fold=b['fold_id'],changed=bool(changes),axes=changes))
    return dict(observed_adjacent_transitions=len(observations),missing_adjacent_transitions=missing,
        changed_transitions=sum(x['changed'] for x in observations),rows=observations,
        interpretation='Adjacent calendar slots only; parameter turnover does not establish a fill, closed action or normalized distance.')


def reduce_views(rows,registered):
    complete=[r for r in rows if r['status']=='OBSERVED']
    masks=dict(all_calendar=[r['fold_id'] for r in rows],
        model_ready=[r['fold_id'] for r in complete if r['model_ready']],
        fallback=[r['fold_id'] for r in complete if not r['model_ready'] and r['activation']!='off'],
        meta_disabled=[r['fold_id'] for r in complete if r['activation']=='off'],
        applied_changed=[r['fold_id'] for r in complete if r['policies']['applied']['same_effective'] is False],
        proposed_changed=[r['fold_id'] for r in complete if r['policies']['proposed']['same_effective'] is False])
    for cohort in registered:
        if cohort['name'] in masks:
            raise ValueError('registered cohort cannot override built-in masks')
        masks[cohort['name']]=cohort['fold_ids']
    cohorts={}
    for name,mask in masks.items():
        cohorts[name]=dict(fold_ids=mask,policies={p:policy_summary(rows,p,mask) for p in POLICIES},
            comparisons={a+'_vs_'+b:paired_summary(rows,a,b,mask)
                for a,b in (('applied','native'),('proposed','native'),('applied','proposed'))})
    byyear={}
    bystate={}
    for row in complete:
        byyear.setdefault(row['forward_start'][:4],[]).append(row['fold_id'])
        for label in row['state_labels']:
            bystate.setdefault(label,[]).append(row['fold_id'])
    panel=[r for r in complete if r['acquired_predictions']]
    loss=[]
    for row in panel:
        values=row['acquired_predictions']
        loss.append(dict(fold_id=row['fold_id'],labels=len(values),
            y_mse=float(np.mean([(p['yhat']-p['actual_y'])**2 for p in values])),
            q_mse=float(np.mean([(p['qhat']-p['actual_q'])**2 for p in values])),
            zero_y_mse=float(np.mean([p['actual_y']**2 for p in values])),
            structural_q_zero_y_mse=float(np.mean([(p['delta_is']-p['actual_y'])**2 for p in values])),
            structural_q_zero_q_mse=float(np.mean([p['actual_q']**2 for p in values]))))
    return dict(cohorts=cohorts,model_status_counts=dict(Counter(r['model_status'] for r in complete)),
        parameter_turnover={p:turnover(rows,p) for p in POLICIES},
        time_consistency={year:policy_summary(rows,'applied',mask) for year,mask in sorted(byyear.items())},
        time_coverage={year:dict(fold_ids=mask,origin_count=len(mask),
            first_forward_start=min(r['forward_start'] for r in complete if r['fold_id'] in mask),
            last_forward_end=max(r['forward_end'] for r in complete if r['fold_id'] in mask),
            full_calendar_year_claimed=False) for year,mask in sorted(byyear.items())},
        state_consistency={state:policy_summary(rows,'applied',mask) for state,mask in sorted(bystate.items())},
        state_coverage=dict(status='OBSERVED_SOURCE_LABELS' if bystate else 'NOT_SUPPLIED',
            labelled_fold_ids=[r['fold_id'] for r in complete if r['state_labels']],
            unlabelled_fold_ids=[r['fold_id'] for r in complete if not r['state_labels']],
            reason='No classifier fitted; source-labelled overlapping states only, not inferred from outcome sign.'),
        execution_differences=dict(status='SOURCE_BOUND_NOT_REPLAYED' if any(r['execution_comparison'] is not None for r in complete) else 'NOT_SUPPLIED',
            observed_fold_ids=[r['fold_id'] for r in complete if r['execution_comparison'] is not None],
            missing_fold_ids=[r['fold_id'] for r in complete if r['execution_comparison'] is None],
            reason='Parameter changes are not execution differences. Only original compared execution witnesses qualify.'),
        forward_mark_span_days=describe([r['mark_span_days'] for r in complete]),
        state_interpretation='Source-labelled dependent views; overlaps are allowed, calendar groups are not independent regimes.',
        acquired_prediction_loss=dict(origin_rows=loss,supported_origins=len(loss),
            total_observed_labels=sum(r['labels'] for r in loss),
            origin_macro_y_mse=float(np.mean([r['y_mse'] for r in loss])) if loss else None,
            origin_macro_q_mse=float(np.mean([r['q_mse'] for r in loss])) if loss else None,
            controls=dict(fold_ids=[r['fold_id'] for r in loss],
                zero_y_origin_macro_mse=float(np.mean([r['zero_y_mse'] for r in loss])) if loss else None,
                structural_q_zero_origin_macro_y_mse=float(np.mean([r['structural_q_zero_y_mse'] for r in loss])) if loss else None,
                structural_q_zero_origin_macro_q_mse=float(np.mean([r['structural_q_zero_q_mse'] for r in loss])) if loss else None,
                application_policy='REFERENCE_ERRORS_ONLY_NO_NEW_DECISIONS',
                interpretation='Permitted Yhat=0 and Yhat=deltaIS/Qhat=0 references on the exact same witnessed label mask; neither is random search or an executed replacement policy.'),
            interpretation='Same acquired witnessed labels only, equal within-origin then equal-origin; not selected-winner loss, randomized acquisition, full-pool regret or independent Y/Q tests.'))
