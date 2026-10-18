"""Evidence-qualified explanations and non-executing recipe option cards."""

def finding(key, status, value, unit, evidence, interpretation, rival, missing, action):
    return dict(finding_id=key,status=status,value=value,unit=unit,evidence_ids=evidence,
        interpretation=interpretation,competing_explanation=rival,missing_evidence=missing,
        next_bounded_action=action,uncertainty=dict(value=None,
            reason='No new inferential estimator or independent study is introduced by this report.'))


def explanations(search, accounts, optional, associations):
    observed = [finding('search_support','OBSERVED',dict(
        observations=search['retained_observations'],effective_points=search['unique_effective_points'],
        duplicate_observations=search['duplicate_effective_observations'],
        attempted=search['attempts']['attempted']), 'counts_with_distinct_units',['search'],
        'Attempts, retained observations, effective points and independent origins are different quantities.',
        'Concentration can reflect the objective, feasible domain, data or sampler, not sampler identity alone.',
        ['Neutral-design coverage or matched recipe evidence is needed for stronger search-quality claims.'],
        'Inspect branch/boundary support before choosing a compatible challenger.')]
    for account in accounts:
        groups=account['groups']
        observed.append(finding('environment_concentration/'+account['evaluation_id'],
            'OBSERVED' if groups else account['environments_status'],groups or None,
            account['monetary_unit'],[account['execution_id']],
            'State-labelled actual monetary contributions and positive/loss masses are shown without division by signed net PnL.',
            'Directional exposure, market composition, objective and selector can explain bull concentration under any sampler.',
            [] if groups else [account['environments_reason']],
            'Inspect exact calendar/state support; a causal sampler explanation needs a separately matched comparison.'))
        observed.append(finding('participation/'+account['evaluation_id'],'OBSERVED',dict(
            exposed_bars=account['exposed_bars'],observed_bars=account['observed_bars'],
            exposed_days=account['exposed_days'],zero_valid_return_days=account['zero_valid_return_days'],
            undefined_return_days=account['undefined_return_days']), 'named_bar_day_counts',[account['execution_id']],
            'Activity and zero-return support are descriptive; no sparse-candidate rejection is added.',
            'Flatness may be a legitimate specialist, insufficient opportunities, risk rejection or an inactive branch.',
            ['Opportunity/rejection and campaign evidence is not inferred from close marks.'],
            'Review available opportunity and execution witnesses before changing an alpha gate.'))
    concerns = dict(geometry='sensitivity',sharpness='fragility',regime='environments',
        factors='factors',selector_concentration='selection',sampler_response='sampler_comparison',
        execution_sensitivity='execution_stress')
    for concern, section in concerns.items():
        item=optional.get(section)
        available=item is not None and item['status']=='SOURCE_BOUND_ANALYSIS'
        observed.append(finding(concern,'OBSERVED_SOURCE' if available else 'NOT_SUPPLIED',
            dict(reference=item['reference'],producer_status=item['value'].get('status'),
                 producer_method=item['value'].get('method')) if available else None,'producer_declared_in_source',
            [item['reference']['source']] if available else [],
            'Retained producer analysis, not a newly qualified estimator or universal alpha classification.' if available else
            'No authorized compatible analysis supplied; the absent effect is not assigned a neutral value.',
            'Adaptive associations cannot prove causal interaction, basin volume or globally dead parameters.',
            [] if available else ['Missing source-bound '+section+' analysis.'],
            'Inspect source masks, scope and method; register only the missing targeted test if needed.'))
    if not accounts:
        observed.append(finding('account_participation_concentration','NOT_SUPPLIED',None,
            'actual_account_marks',[],'No account path supplied; aggregate Sharpe cannot establish regime PnL or activity.',
            'Missing path evidence does not establish an inactive or non-robust alpha.',
            ['Original account marks, positions, costs and authorized state labels.'],
            'Supply exact retained arrays; do not run a financial simulation from the renderer.'))
    observed.append(finding('association_rights',associations['status'],
        dict(reference='associations/result',status=associations['status']) if associations['result'] is not None else None,
        'existing_branch_local_rank_reducer',['associations'],associations['reason'],
        'A reviewed/adaptive pool has a selection-dependent distribution.',
        ['A complete registered structured design is required for named global sensitivity.'],
        'Use existing prefix-authorized structured/local evidence; never reinterpret arbitrary TPE trials as Saltelli.'))
    return observed


def recipe_cards(compatibility, advice, optional, search):
    cards=[]
    comparison=optional.get('sampler_comparison')
    comparison_available=bool(comparison and comparison['status']=='SOURCE_BOUND_ANALYSIS')
    observed_geometry=dict(branches=len(search['branches']),
        conditional_axes=sum(a['conditional'] for a in search['axes']),
        source_inactive_axes=sum(a['source_inactive_reason'] is not None for a in search['axes']),
        observed_varying_axes=search['observed_varying_axes'],
        unique_effective_points=search['unique_effective_points'],
        duplicate_effective_observations=search['duplicate_effective_observations'],
        coupled_constraints=search['constraint_count'])
    for option in compatibility:
        name=option['recipe_id']
        rationale={
            'tpe_legacy':'Retain the incumbent marginal-search comparator; observed adaptive coverage need not suit every branch or interaction.',
            'tpe_multivariate_group':'A compatible joint-search challenger when interactions have supporting evidence; dimension count alone is not evidence.',
            'cmaes':'A static numeric geometry option under the existing factory policy; categorical/conditional encodings require an explicit compatible policy.',
            'sobol':'An authorized low-discrepancy coverage option, not automatic economic superiority or Sobol sensitivity.'}[name]
        cards.append(dict(kind='sampler',recipe_id=name,
            status=('COMPATIBLE_SOURCE_AVAILABLE' if comparison_available else 'COMPATIBLE_UNMEASURED') if option['compatible'] else 'NOT_COMPATIBLE',
            compatible=option['compatible'],compatibility_reason=option['reason'],
            basis='SCHEMA_COMPATIBILITY',rationale=rationale,
            observed_geometry=observed_geometry,
            evidence_ids=['geometry','search']+([comparison['reference']['source']] if comparison_available else []),
            observed_response=comparison['reference'] if comparison_available else None,
            response_status='SOURCE_AVAILABLE_NOT_AUTOMATIC_WINNER' if comparison_available else 'NOT_SUPPLIED',
            competing_explanation='Objective, data, branch constraints and selector also affect concentration; no TPE-only bull-bias attribution.',
            missing_evidence=['Scientific matching/support of the supplied comparison and actual dependency/fallback telemetry.'] if comparison_available else
                ['Recipe-specific matched economic comparison and actual dependency/fallback telemetry.'],
            next_bounded_action='Inspect the registered matched comparison before shortlisting; do not launch an optimizer here.',
            researcher_override='Supply explicit DiagnosticAdvice/compatible schema policy and record with_choice; this card does not activate a recipe.',
            applies_configuration=False))
    for item in advice:
        if item['kind']=='selector':
            cards.append(dict(item,status='RESEARCHER_SUPPLIED',compatible=None,
                competing_explanation='A Mode 5 selector requires its actual metric/probe contract before use as a Mode 4 selector.',
                next_bounded_action='Verify IS-only metric availability and implementation; keep absent annual/local evidence explicit.',
                applies_configuration=False))
    if not any(c['kind']=='selector' for c in cards):
        cards.append(dict(kind='selector',recipe_id=None,status='NOT_SUPPLIED',compatible=None,
            basis='NO_SELECTOR_CONTRACT',rationale='No source-backed selector shortlist supplied.',evidence_ids=[],
            missing_evidence=['Selector implementation, metrics, chronology and authorized probes.'],
            competing_explanation='Aggregate quality does not supply annual floor or local fragility.',
            next_bounded_action='Supply an explicit versioned selector option; no selector is invented by this report.',
            applies_configuration=False))
    return cards
