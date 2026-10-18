"""Public allowlists and readable quantitative summaries, no private source prose."""

from html import escape
import json

from quantbt.mode5.decision_report import DecisionReport
from quantbt.mode5.dossier.records import Record

from .reduction import POLICIES

STATS=('status','count','mean','median','sample_std','minimum','maximum','q05','q95',
    'positive','negative','zero','positive_magnitude','negative_magnitude','mean_negative',
    'mean_worst_20pct','worst_20pct_status')
COHORTS={'all_calendar','model_ready','fallback','meta_disabled','applied_changed','proposed_changed'}
UNITS={'fraction','ratio','USD','USDT','USDC','executed_fill_count','closed_action_count','closed_campaign_count'}
ACCOUNT_METRICS={'initial_capital','final_equity','total_return_pct','cagr_pct','sharpe','sortino','calmar','omega',
    'max_drawdown_pct','avg_drawdown_pct','max_dd_duration_days','avg_dd_duration_days','profit_factor',
    'long_hitrate_pct','short_hitrate_pct','avg_win_pct','avg_loss_pct','expectancy_pct','liquidated',
    'actual_fill_count','fees','funding','oos_exposure_fraction'}


def _accounts(values):
    return [dict(policy=v['policy'] if v['policy'] in {'native','proposed','applied','selected'} else 'REDACTED',
        scope_relation=v['scope_relation'],start_ns=v['start_ns'],stop_ns=v['stop_ns'],
        metrics={k:x for k,x in v['metrics'].items() if k in ACCOUNT_METRICS},
        units={k:x if x in UNITS|{'percent','elapsed_days','count'} else 'REDACTED'
            for k,x in v['units'].items() if k in ACCOUNT_METRICS}) for v in values]


def _pick(data,names):
    return {k:data[k] for k in names if k in data}


def _stats(value,alias):
    result=_pick(value,STATS)
    if 'fold_ids' in value:
        result['fold_ids']=[alias[k] for k in value['fold_ids']]
    return result


def _policy(value,alias):
    result=_pick(value,('calendar_count','observed_decisions','missing_or_undefined_effects','model_ready',
        'changed_ids','changed_effective','helped','harmed','tied','q_help_rate','r_improvement_rate'))
    for key in ('missing_fold_ids','missing_policy_ids','paired_effect_fold_ids'):
        result[key]=[alias[k] for k in value[key]]
    result['effects']={k:_stats(v,alias) for k,v in value['effects'].items()}
    result['activity']=dict(unit=value['activity']['unit'],fold_ids=[alias[k] for k in value['activity']['fold_ids']],
        statistics=_stats(value['activity']['statistics'],alias))
    result['matched_decomposition']=dict(means=value['matched_decomposition']['means'],
        fold_ids=[alias[k] for k in value['matched_decomposition']['fold_ids']])
    for key in ('positive_forward_sharpe','positive_forward_return'):
        original=value[key]
        result[key]=_pick(original,('positive','defined','rate'))
        result[key]['fold_ids']=[alias[k] for k in original['fold_ids']]
    result['supplemental']={k:dict(unit=v['unit'] if v['unit'] in UNITS else 'REDACTED',
        fold_ids=[alias[x] for x in v['fold_ids']],statistics=_stats(v['statistics'],alias))
        for k,v in value['supplemental'].items()}
    result['prediction']=_pick(value['prediction'],('count','y_count','q_mse','y_mse','q_mae','q_signed_bias','errors_not_independent'))
    result['guard']=_pick(value['guard'],('accepted_defined_count','accepted_negative_q','accepted_negative_q_rate',
        'accepted_q_below_minus_0_1','accepted_q_below_minus_0_1_rate',
        'observed_floor_count','accepted_below_original_floor','accepted_below_original_floor_rate'))
    result['witnessed_opportunity']=_pick(value['witnessed_opportunity'],('status','observed_origins','members',
        'valid_members','better_observed_base_candidate','mean_positive_headroom','full_pool_oracle'))
    return result


def public_view(data,*,detail):
    result=dict(schema='quantbt.research_decision_report.public.v1',mode=data['mode'],
        payload=dict(view=data['payload']['view'],decision_use=data['payload']['decision_use']),
        limits=data['limits'],private_content='REDACTED')
    if data['mode']=='mode5':
        original=DecisionReport(Record.of(data['payload']['mode5_snapshot'])).to_dict()
        result['summary']=dict(mode5_summary=original['summary'],mode5_report=original,
            continuous_accounts=_accounts(data['payload']['accounts']) or [dict(status='NOT_SUPPLIED')])
        return result
    payload,summary=data['payload'],data['summary']
    alias={r['fold_id']:f'fold-{i+1}' for i,r in enumerate(payload['roster'])}
    cohorts={}
    names={name:name if name in COHORTS else f'registered-cohort-{i+1}' for i,name in enumerate(summary['cohorts'])}
    for name,cohort in summary['cohorts'].items():
        comparisons={}
        for key,value in cohort['comparisons'].items():
            comparisons[key]=dict(_pick(value,('treatment','comparator','calendar_count','helped','harmed','tied')),
                paired_fold_ids=[alias[k] for k in value['paired_fold_ids']],
                unpaired_fold_ids=[alias[k] for k in value['unpaired_fold_ids']],
                differences={k:_stats(v,alias) for k,v in value['differences'].items()},
                matched_levels={p:{k:_stats(v,alias) for k,v in metrics.items()} for p,metrics in value['matched_levels'].items()})
        cohorts[names[name]]=dict(fold_ids=[alias[k] for k in cohort['fold_ids']],
            policies={p:_policy(v,alias) for p,v in cohort['policies'].items()},comparisons=comparisons)
    intervals=[]
    for value in summary['uncertainty']['coordinates']:
        intervals.append(dict(cohort=names[value['cohort']],comparison=value['comparison'],metric=value['metric'],
            fold_ids=[alias[k] for k in value['fold_ids']],estimate=value['estimate'],lower=value['lower'],upper=value['upper'],
            status=value['status'] if value['status']=='DEFINED_EXPLORATORY' else 'UNAVAILABLE'))
    loss=summary['acquired_prediction_loss']
    result['summary']=dict(cohorts=cohorts,
        forward_mark_span_days=_stats(summary['forward_mark_span_days'],alias),
        state_coverage=dict(status=summary['state_coverage']['status'],
            labelled_fold_ids=[alias[k] for k in summary['state_coverage']['labelled_fold_ids']],
            unlabelled_fold_ids=[alias[k] for k in summary['state_coverage']['unlabelled_fold_ids']]),
        execution_differences=dict(status=summary['execution_differences']['status'],
            observed_fold_ids=[alias[k] for k in summary['execution_differences']['observed_fold_ids']],
            missing_fold_ids=[alias[k] for k in summary['execution_differences']['missing_fold_ids']]),
        parameter_turnover={p:_pick(v,('observed_adjacent_transitions','missing_adjacent_transitions','changed_transitions'))
            for p,v in summary['parameter_turnover'].items()},
        time_consistency={f'time-group-{i+1}':_policy(v,alias) for i,v in enumerate(summary['time_consistency'].values())},
        state_consistency={f'state-group-{i+1}':_policy(v,alias) for i,v in enumerate(summary['state_consistency'].values())},
        acquired_prediction_loss=dict(_pick(loss,('supported_origins','total_observed_labels','origin_macro_y_mse','origin_macro_q_mse')),
            controls=dict(_pick(loss['controls'],('zero_y_origin_macro_mse','structural_q_zero_origin_macro_y_mse',
                'structural_q_zero_origin_macro_q_mse','application_policy')),
                fold_ids=[alias[k] for k in loss['controls']['fold_ids']])),
        uncertainty=dict(status=summary['uncertainty']['status'],coordinates=intervals),
        continuous_accounts=_accounts(payload['accounts']) or [dict(status='NOT_SUPPLIED')])
    if detail:
        result['payload']['rows']=[]
        for row in payload['rows']:
            out=dict(fold_id=alias[row['fold_id']],status=row['status'])
            if row['status']=='OBSERVED':
                out.update(model_ready=row['model_ready'],activation=row['activation'],
                    policies={p:dict(params='REDACTED',measurement_status=v['measurement_status'],
                        same_id=v['same_id'],same_effective=v['same_effective'],
                        effect=v['effect'],forward_sharpe=v['observations']['selected_forward']['raw_sharpe']
                            if v['observations']['selected_forward']['status']=='VALID' else None)
                        for p,v in row['policies'].items()})
            result['payload']['rows'].append(out)
    return result


def _cell(value):
    if isinstance(value,float):
        return f'{value:.6g}'
    if value is None:
        return 'N/A'
    text=value if isinstance(value,str) else json.dumps(value,sort_keys=True,allow_nan=False)
    return escape(text,quote=True).replace('|','\\|').replace('\n',' ').replace('\r',' ')


def _table(title,columns,rows):
    return ['','## '+title,'','| '+' | '.join(columns)+' |','| '+' | '.join('---' for _ in columns)+' |']+[
        '| '+' | '.join(_cell(v) for v in row)+' |' for row in rows]


def markdown(data):
    lines=['# Research Decision Report','',
        'Mode: '+data['mode']+'; view: '+data['payload']['view']+'; decision use: '+data['payload']['decision_use'],
        'R = decay(anchor) - decay(selected); Q = forward(selected) - forward(anchor).',
        'R = IS contribution + Q on the same four-operand mask. Positive R does not imply positive Q.',
        'Help/harm uses Q sign. Positive forward Sharpe and positive account return have separate masks.',
        'No requirement that every fold be positive or that OOS exceed IS.']
    summary=data['summary']
    if data['mode']=='mode5':
        original=summary.get('mode5_report')
        if original is not None:
            lines += _table('Full-Development Calibration',('Field','Value'),summary['mode5_summary'].items())
            lines += ['','Full-development dictionary and dependent environment views; not causal WFO/OOS.']
            return '\n'.join(lines)+'\n'
        lines += _table('Fixed Decision',('Field','Retained Value'),summary['selection'].items())
        lines += _table('Selected Dictionary',('Field','Value'),(summary['selected_params'] or {}).items())
        lines += _table('Environment Observations',('Environment','Raw Sharpe','Return','DD','Utility','Support'),
            ((o.get('environment_id'),o.get('raw_sharpe'),o.get('net_return'),o.get('max_drawdown'),o.get('utility'),o.get('daily_count'))
             for o in summary['environments']))
        lines += _table('Original Whole Observation',('Field','Value'),(summary['selected_observation'] or {'status':'NOT_SUPPLIED'}).items())
    else:
        rows=[]
        paired=[]
        for name,cohort in summary['cohorts'].items():
            for p in POLICIES:
                value=cohort['policies'][p]; means=value['matched_decomposition']['means']
                rows.append((name,p,value['calendar_count'],len(value['paired_effect_fold_ids']),value['model_ready'],
                    value['changed_effective'],f"{value['helped']}/{value['harmed']}/{value['tied']}",
                    means['R'],means['IS_contribution'],means['Q'],
                    f"{value['positive_forward_sharpe']['positive']}/{value['positive_forward_sharpe']['defined']}",
                    f"{value['positive_forward_return']['positive']}/{value['positive_forward_return']['defined']}"))
            for name2,value in cohort['comparisons'].items():
                r,q=value['differences']['R'],value['differences']['Q']
                paired.append((name,name2,r['count'],r['mean'],q['count'],q['mean'],value['helped'],value['harmed'],value['tied']))
        lines += _table('Cohorts And Matched Decomposition',('Cohort','Policy','Calendar','Four Operands','Model Ready','Changed',
            'Q Help/Harm/Tie','Mean R','Mean IS','Mean Q','OOS Sharpe > 0','OOS Return > 0'),rows)
        lines += _table('Same-Origin Comparisons',('Cohort','Contrast','R n','Delta R','Q n','Delta Q','Help','Harm','Tie'),paired)
        all_policy=summary['cohorts']['all_calendar']['policies']['applied']
        lines += _table('Applied Forward Distribution',('Metric','n','Mean','Median','Std','Min','Max','Worst20%'),
            ((key,value['count'],value['mean'],value['median'],value['sample_std'],value['minimum'],value['maximum'],value['mean_worst_20pct'])
             for key,value in all_policy['effects'].items()))
        lines += _table('Original Supplemental Metrics',('Metric','Unit','Observed Origins','Mean','Median','Min','Max'),
            ((key,value['unit'],value['statistics']['count'],value['statistics']['mean'],value['statistics']['median'],
              value['statistics']['minimum'],value['statistics']['maximum']) for key,value in all_policy['supplemental'].items()))
        lines += _table('Guard And Decision Calibration',('Field','Value'),
            [*all_policy['prediction'].items(),*all_policy['guard'].items()])
        lines += _table('Witnessed Candidate Opportunity',('Field','Value'),all_policy['witnessed_opportunity'].items())
        lines += _table('Original Activity Count',('Field','Value'),all_policy['activity'].items())
        lines += ['','Own-metric masks, means/medians/dispersion/tails and missing dispositions are retained in JSON.',
            'Matched decomposition above uses one common mask; own-mask statistics must not be subtracted as matched means.']
        lines += _table('Parameter Turnover',('Policy','Observed Adjacent','Missing Adjacent','Changed'),
            ((p,v['observed_adjacent_transitions'],v['missing_adjacent_transitions'],v['changed_transitions'])
             for p,v in summary['parameter_turnover'].items()))
        lines += _table('Acquired Prediction Loss',('Field','Value'),
            ((k,v) for k,v in summary['acquired_prediction_loss'].items() if k!='origin_rows'))
        if 'rows' in data['payload']:
            detail=[]
            for row in data['payload']['rows']:
                for policy,v in row.get('policies',{}).items():
                    effect=v.get('effect') or {}
                    detail.append((row['fold_id'],policy,row['status'],v['same_effective'],
                        effect.get('anchor_is'),effect.get('selected_is'),effect.get('anchor_forward'),effect.get('selected_forward'),
                        effect.get('R'),effect.get('Q'),v['measurement_status']))
            lines += _table('Per-Fold Measurement',('Fold','Policy','Status','Same Params','Anchor IS','Selected IS',
                'Anchor OOS','Selected OOS','R','Q','Measurement'),detail)
    lines += _table('Retained Uncertainty',('Field','Value'),summary.get('uncertainty',{'status':'NOT_APPLICABLE_FULL_DEVELOPMENT'}).items())
    lines += _table('Original Continuous Accounts',('Field','Value'),{'accounts':summary.get('continuous_accounts')}.items())
    lines += ['','## Limits','',*['- '+x for x in data['limits']]]
    return '\n'.join(lines)+'\n'
