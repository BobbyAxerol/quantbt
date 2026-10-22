"""Cold participation/concentration on the existing monetary attribution owner."""

import math
import numpy as np

from .environments.attribution import daily_path, attribute_days


def account_profile(account, policy):
    path = daily_path(account.evidence, policy, initial_equity=account.initial_equity,
                      evaluation_mode=account.evaluation_mode)
    pnl, returns, valid, exposed, bars = (b.array() for b in
        (path.pnl, path.returns, path.return_valid, path.exposed_bars, path.observed_bars))
    arrays = account.evidence.arrays()
    positive, negative = float(np.maximum(pnl,0).sum()), float(-np.minimum(pnl,0).sum())
    absolute = positive+negative
    labels = account.labels.array() if account.labels is not None else np.zeros(len(pnl),dtype=np.int64)
    if labels.shape != pnl.shape:
        raise ValueError('environment labels must align to original observed UTC days')
    attribution = attribute_days(path, labels) if path.mode=='CONTINUOUS_PATH_ATTRIBUTION' else None
    names = dict(account.label_names)
    groups = []
    if account.labels is not None and attribution is not None:
        for original in attribution['rows']:
            state = original['state']
            mask = labels==state
            up = float(np.maximum(pnl[mask],0).sum())
            down = float(-np.minimum(pnl[mask],0).sum())
            groups.append(dict(original, name=names.get(state,'UNKNOWN' if state==-1 else str(state)),
                positive_day_pnl=up, negative_day_loss=down,
                positive_day_mass_share=up/positive if positive>0 else None,
                negative_day_mass_share=down/negative if negative>0 else None,
                absolute_daily_pnl_share=(up+down)/absolute if absolute>0 else None))
    if attribution is not None:
        if not math.isclose(attribution['summed_group_pnl'],float(pnl.sum()),rel_tol=1e-12,abs_tol=1e-8):
            raise ValueError('actual monetary attribution does not reconcile')
    positions = arrays['positions']
    long_bars = int(np.count_nonzero(np.any(positions>0,axis=1) if positions.ndim==2 else positions>0))
    short_bars = int(np.count_nonzero(np.any(positions<0,axis=1) if positions.ndim==2 else positions<0))
    funding = arrays.get('funding')
    if funding is not None and funding.shape != arrays['timestamps'].shape:
        raise ValueError('funding observations must align to actual marks')
    observed = int(bars.sum())
    return dict(evaluation_id=account.evaluation_id, execution_id=account.evidence.execution_id,
        source_ref=account.evidence.source_ref, mode=path.mode, monetary_unit=account.monetary_unit,
        initial_equity=account.initial_equity, terminal_equity=float(path.equity_after.array()[-1]),
        net_pnl=float(pnl.sum()), positive_day_pnl=positive, negative_day_loss=negative,
        absolute_daily_pnl=absolute, signed_net_denominator_used=False,
        concentration_status='OBSERVED' if absolute>0 else 'UNDEFINED_ZERO_ABSOLUTE_PNL',
        groups=groups, attribution=attribution,
        environments_status='OBSERVED' if account.labels is not None and attribution is not None else 'NOT_SUPPLIED' if account.labels is None else 'NOT_COMPARABLE',
        environments_reason=None if account.labels is not None and attribution is not None else
            'No source-bound daily state labels supplied.' if account.labels is None else 'Reset episodes cannot be attributed as one continuous carried account.',
        label_purpose=account.label_purpose if account.labels is not None else None,
        label_source_ref=account.label_source_ref,
        observed_days=len(pnl), observed_bars=observed, exposed_bars=int(exposed.sum()),
        exposed_days=int(np.count_nonzero(exposed)), long_close_mark_bars=long_bars,short_close_mark_bars=short_bars,
        exposure_fraction=float(exposed.sum()/observed) if observed else None,
        valid_return_days=int(valid.sum()), undefined_return_days=int((~valid).sum()),
        zero_valid_return_days=int(np.count_nonzero(valid & (returns==0))),
        fees=float(path.fees.array().sum()) if path.fees is not None else None,
        funding=float(funding.sum()) if funding is not None else None,
        unknown_states=int(np.count_nonzero(labels==-1)) if account.labels is not None else None,
        opportunities=dict(status='NOT_SUPPLIED',value=None,reason='Close-mark exposure cannot establish entry opportunities or risk rejections.'),
        campaigns=dict(status='NOT_SUPPLIED',value=None,reason='No closed/open campaign ledger supplied; fills are not campaigns.'),
        participation_interpretation='Observed close-mark activity, not a minimum-activity gate; a sparse specialist may be valid.',
        limitations=['State families are separate dependent views, not independent market samples.',
                     'Long/short multi-symbol marks may overlap; close-flat days can contain intrabar fills.',
                     'Costs are already inside equity; no guessed fee/funding subtraction or strategy stress replay.',
                     'Conditional state compound returns are descriptive, not annualized or deployable spliced prices.'])
