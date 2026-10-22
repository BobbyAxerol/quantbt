"""Internal report agreement and exact observation/chronology checks on reload."""

import math

import pandas as pd

from quantbt.optimization.meta_selection.common import digest
from quantbt.optimization.meta_selection.persistence import observation_from_payload
from quantbt.optimization.meta_selection.records import CompatibilityFamily

from .effects import raw_effect
from .contracts import FoldSlot, ReportCohort


def effect_of(observations):
    names=('anchor_is','selected_is','anchor_forward','selected_forward')
    ia,iw,oa,ow=(observations[k]['raw_sharpe'] if observations[k]['status']=='VALID' else None for k in names)
    if all(v is not None for v in (ia,iw,oa,ow)):
        result=raw_effect(ia,iw,oa,ow)
        return dict(result,anchor_decay=ia-oa,selected_decay=iw-ow)
    return dict(R=None,Q=ow-oa if ow is not None and oa is not None else None,
        IS_contribution=ia-iw if ia is not None and iw is not None else None,
        anchor_decay=ia-oa if ia is not None and oa is not None else None,
        selected_decay=iw-ow if iw is not None and ow is not None else None)


def validate_rows(payload):
    rows=payload['rows']
    roster=payload['roster']
    if [r['fold_id'] for r in rows]!=[r['fold_id'] for r in roster]:
        raise ValueError('report rows must preserve the declared calendar including gaps')
    family=payload['family']
    if CompatibilityFamily(**family).family_id!=payload['family_id']:
        raise ValueError('changed family identity')
    slots=[FoldSlot(**s) for s in roster]
    if len({s.fold_id for s in slots})!=len(slots) or any(a.stop_ns>b.start_ns for a,b in zip(slots,slots[1:])):
        raise ValueError('altered ordered calendar')
    cohorts=[ReportCohort(**dict(c,fold_ids=tuple(c['fold_ids']))) for c in payload['cohorts']]
    if (len({c.name for c in cohorts})!=len(cohorts)
            or any(not set(c.fold_ids)<={s.fold_id for s in slots} for c in cohorts)
            or any(c.fold_ids!=tuple(s.fold_id for s in slots if s.fold_id in set(c.fold_ids)) for c in cohorts)):
        raise ValueError('altered cohort mask')
    expected_use='MATURE_HISTORICAL_ONLY' if payload['view']=='prefix' else 'NOT_BACKDATABLE'
    if payload['view'] not in {'prefix','post_wfo'} or payload['decision_use']!=expected_use:
        raise ValueError('altered report data role')
    for row,slot in zip(rows,roster):
        if row['start_ns']!=slot['start_ns'] or row['stop_ns']!=slot['stop_ns']:
            raise ValueError('report row differs from original calendar slot')
        if row['status']=='MISSING_FOLD_RECORD':
            continue
        if row['status']!='OBSERVED':
            raise ValueError('unknown fold disposition')
        clock=row['decision_clock']
        if payload['view']=='prefix' and row['state_labels'] and row['state_label_purpose']!='decision_vintage':
            raise PermissionError('descriptive state source cannot be backdated as a prefix partition')
        if not (pd.Timestamp(row['is_end'])<=pd.Timestamp(clock['cutoff'])<pd.Timestamp(row['forward_start'])
                <=pd.Timestamp(clock['first_forward_action'])<=pd.Timestamp(row['forward_end'])
                and pd.Timestamp(clock['sealed'])<=pd.Timestamp(clock['first_forward_action'])
                and pd.Timestamp(clock['outcome_available'])>=pd.Timestamp(row['forward_end'])):
            raise ValueError('retained fold clocks disagree')
        native=row['policies']['native']
        for name,policy in row['policies'].items():
            candidate=policy['evaluation_id']
            if candidate is not None:
                if policy['params_identity']!=digest(policy['params']):
                    raise ValueError('changed params/identity in retained report')
                expected=effect_of(policy['observations'])
                if policy['effect']!=expected:
                    raise ValueError('altered raw effect/decomposition')
                if (policy['same_id']!=(candidate==native['evaluation_id'])
                        or policy['same_effective']!=(policy['params']==native['params'])):
                    raise ValueError('altered candidate change mask')
            elif policy['effect'] is not None:
                raise ValueError('missing policy cannot claim an effect')
            for role,observation in policy['observations'].items():
                if observation['status']=='MISSING_EXECUTION':
                    continue
                values={k:v for k,v in observation.items() if k!='identity'}
                original=observation_from_payload(values)
                expected_window=(row['is_start'],row['is_end']) if role.endswith('_is') else (row['forward_start'],row['forward_end'])
                if (digest(original)!=observation['identity'] or original.metric_contract_id!=family['metric_contract_id']
                        or original.economics_id!=family['economics_id']
                        or (original.window_start.isoformat(),original.window_end.isoformat())!=tuple(expected_window)):
                    raise ValueError('altered observation/contract/window identity')
            if any(policy['observations'][key]!=native['observations'][key] for key in ('anchor_is','anchor_forward')):
                raise ValueError('policies do not share the original native anchor observations')
        proposed,applied=(row['policies'][p]['evaluation_id'] for p in ('proposed','applied'))
        expected=native['evaluation_id'] if row['activation'] in {'off','shadow'} else proposed if row['activation']=='active' else None
        if applied!=expected:
            raise ValueError('proposal/shadow/active actual-application mismatch')
        for observation in row['acquired_predictions']:
            if not math.isclose(observation['qhat']-observation['actual_q'],
                    -(observation['yhat']-observation['actual_y']),rel_tol=1e-10,abs_tol=1e-10):
                raise ValueError('acquired prediction target/measurement mismatch')
