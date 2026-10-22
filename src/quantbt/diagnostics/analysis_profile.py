"""Scope-bound views of producer analyses, never substitute metric estimators."""

def analysis_profiles(owner, rows, optional):
    byid={r.evaluation_id:r for r in rows}
    result={}
    for name,fields in (
        ('selection',('raw_best_id','native_id','selected_id','selection_reason','top_cohort_count','cluster_size',
                      'fallback','objective_version','objective_components')),
        ('fragility',('status','method','centers','probe_role','design_id')),
        ('sensitivity',('status','method','design_id','representation','metric_names','estimates')),
        ('execution_stress',('status','scenario_id','base_execution_id','stress_execution_id','rank_changes')),
        ('sampler_comparison',('status','design_id','sampler_ids','matched_contract','response'))):
        source=optional.get(name)
        if source is None or source['status']!='SOURCE_BOUND_ANALYSIS':
            result[name]=dict(status='NOT_SUPPLIED',reference=None,
                values={k:None for k in fields},missing_fields=list(fields),
                reason='No compatible source-bound '+name+' analysis supplied; no estimator is invented.')
            continue
        value=source['value']
        if 'cutoff_ns' in value and value['cutoff_ns']!=owner.access.cutoff_ns:
            raise ValueError('analysis cutoff differs from declared diagnostic scope')
        if name=='selection':
            for key in ('raw_best_id','native_id','selected_id'):
                if value.get(key) is not None and value[key] not in byid:
                    raise ValueError('selection analysis references another candidate pool')
        if name=='fragility':
            centers=value.get('centers')
            if centers is not None and (not isinstance(centers,list) or any(not isinstance(c,dict) for c in centers)):
                raise ValueError('local center records must be a retained list of objects or explicit null')
            for center in centers or []:
                row=byid.get(center.get('evaluation_id'))
                if row is None or center.get('point_identity')!=row.point.identity:
                    raise ValueError('probe center does not match the exact retained candidate')
                if center.get('probe_role') not in {'selection_probes','local_validation_probes'}:
                    raise ValueError('explicit selection/held local probe role required')
        result[name]=dict(status='SOURCE_BOUND_NOT_REESTIMATED',reference=source['reference'],
            values={k:value.get(k) for k in fields},missing_fields=[k for k in fields if value.get(k) is None],
            reason='Exact producer fields only; absent inputs are not reconstructed from aggregate Sharpe.')
    return result
