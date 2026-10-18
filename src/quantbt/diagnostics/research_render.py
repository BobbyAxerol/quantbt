"""Bounded text and allowlisted public views of the shared cold report."""

from html import escape
import json


def cell(value):
    text=value if isinstance(value,str) else json.dumps(value,sort_keys=True,allow_nan=False)
    return escape(text,quote=True).replace('|','\\|').replace('\n',' ').replace('\r',' ')


def markdown(research):
    search=research['search']
    lines=['','## Researcher Decision Support',
        'View: '+research['view']+'; decision use: '+research['decision_use'],
        'This report does not apply an optimizer, selector or parameter change.',
        '', '### Search And Coverage']
    for key in ('attempts','unique_effective_points','duplicate_effective_observations',
                'nominal_variable_axes','observed_varying_axes','effective_dimension','constraint_coverage'):
        lines.append('- '+key+': '+cell(search[key]))
    lines += ['', '| Axis | Active Points | Values | Low Hits | High Hits |', '|---|---:|---:|---:|---:|']
    for row in search['axes']:
        lines.append('| '+' | '.join(cell(row[k]) for k in
            ('name','active_effective_points','observed_values','low_boundary_points','high_boundary_points'))+' |')
    lines += ['', '### Account Participation And Environment Contributions']
    if not research['accounts']:
        lines.append('NOT_SUPPLIED: original account paths and state witnesses are missing.')
    for account in research['accounts']:
        lines += ['- Account '+cell(account['evaluation_id'])+': '+cell({k:account[k] for k in
            ('mode','monetary_unit','net_pnl','positive_day_pnl','negative_day_loss','exposed_days',
             'observed_days','exposed_bars','observed_bars','zero_valid_return_days','undefined_return_days',
             'fees','funding','environments_status','environments_reason')})]
        for group in account['groups']:
            lines.append('  - '+cell(group))
    lines += ['', '### Findings', '| Concern | Status / Value / Units | Interpretation | Rival / Missing | Next Action |', '|---|---|---|---|---|']
    for item in research['findings']:
        lines.append('| '+' | '.join(cell(v) for v in (item['finding_id'],
            dict(status=item['status'],value=item['value'],unit=item['unit']),item['interpretation'],
            dict(rival=item['competing_explanation'],missing=item['missing_evidence']),item['next_bounded_action']))+' |')
    lines += ['', '### Sampler And Selector Options', '| Kind / Recipe | Status | Rationale | Missing Proof | Next Action |', '|---|---|---|---|---|']
    for item in research['recipe_options']:
        lines.append('| '+' | '.join(cell(v) for v in ((item['kind'],item['recipe_id']),item['status'],
            item['rationale'],item['missing_evidence'],item['next_bounded_action']))+' |')
    lines += ['', '### Retained Analysis Details']
    for name,profile in research['analysis_profiles'].items():
        lines.append('- '+name+': '+cell(profile))
    lines += ['', '### Six-Matrix Availability']
    lines += ['- '+kind+': '+cell(value) for kind,value in research['matrices'].items()]
    return '\n'.join(lines)+'\n'


def public_data(data):
    """Only fixed enums and aggregate counts, never private prose/values/IDs."""
    coverage={k:data['coverage'][k] for k in ('evaluations','unique_effective_candidates',
        'duplicate_effective_evaluations','measured_primary','missing_primary')}
    coverage['status_counts']={k:v for k,v in data['coverage']['status_counts'].items()
        if k in {'COMPLETE','NO_TRADE','FAILED','INFEASIBLE','CANCELLED'} and type(v) is int}
    result=dict(schema='quantbt.alpha_diagnostics.public.v1',report_id=None,
        coverage=coverage,geometry=dict(axis_count=len(data['geometry']['axes']),
            coupled_constraint_count=data['geometry']['coupled_constraints']),
        authority=data['authority'],private_content='REDACTED')
    if 'researcher_diagnostics' in data:
        research=data['researcher_diagnostics']
        result['researcher_diagnostics']=dict(schema='quantbt.presearch_researcher.public.v1',
            view=research['view'],decision_use=research['decision_use'],
            attempted=research['search']['attempts']['attempted'],
            account_count=len(research['accounts']),finding_count=len(research['findings']),
            matrix_statuses={k:v['status'] for k,v in research['matrices'].items()},
            recipes=[dict(recipe_id=c['recipe_id'],compatible=c['compatible'])
                for c in research['recipe_options'] if c['kind']=='sampler' and
                    c['recipe_id'] in {'tpe_legacy','tpe_multivariate_group','cmaes','sobol'}])
    return result


def public_markdown(data):
    return '# Alpha Diagnostics (Public)\n\nPrivate content redacted. Counts and fixed states only.\n\n'+cell(data)+'\n'
