"""Finite-panel ranks of original-account state readbacks, never selection."""

import math

from scipy.stats import rankdata, spearmanr


def finite_panel_regimes(accounts, diagnostic_ids, selected):
    ids=tuple(diagnostic_ids)
    if not ids or len(ids)!=len(set(ids)) or set(ids)-accounts.keys() or set(selected.values())-accounts.keys():
        raise ValueError("complete distinct diagnostic and actual-winner identities required")
    first=accounts[ids[0]]["views"]
    results={}
    for namespace,families in first.items():
        results[namespace]={}
        for family,attribution in families.items():
            expected={row["state"] for row in attribution["rows"]}
            matrix={}
            for cid in set(ids)|set(selected.values()):
                current=accounts[cid]["views"][namespace][family]
                if {row["state"] for row in current["rows"]}!=expected:
                    raise ValueError("state roster differs; missing states cannot disappear")
                if not math.isclose(current["conservation_residual"],0.,rel_tol=0.,abs_tol=1e-7):
                    raise ValueError("state PnL does not reconcile to the original account")
                matrix[cid]={row["state"]:row for row in current["rows"]}
            states=[]
            for state in sorted(expected):
                points=[(cid,matrix[cid][state]["mean_net_daily_return"]) for cid in ids]
                finite=[(cid,value) for cid,value in points if value is not None and math.isfinite(value)]
                values=[value for _,value in finite]
                ranks=rankdata([-value for value in values],method="average").tolist()
                reference=max(values) if values else None
                winners={}
                for arm,cid in selected.items():
                    row=matrix[cid][state]
                    value=row["mean_net_daily_return"]
                    defined=value is not None and math.isfinite(value)
                    rank=None if not defined else 1+sum(other>value for other in values)
                    winners[arm]=dict(candidate_id=cid,observation=row,
                        comparison_to_diagnostic_panel=dict(reference_mean_net_daily_return=reference,
                            rank_position_among_reference=rank,reference_points=len(values),
                            signed_reference_gap=None if not defined or reference is None else reference-value,
                            regret=None if not defined or reference is None else max(0.,reference-value),
                            extrapolated_above_reference=None if not defined or reference is None else value>reference))
                states.append(dict(state=state,diagnostic_support=len(finite),undefined_diagnostic=len(ids)-len(finite),
                    candidates=[dict(candidate_id=cid,mean_net_daily_return=value,rank=rank)
                        for (cid,value),rank in zip(finite,ranks,strict=True)],winners=winners,
                    positive_mean_candidates=sum(value>0 for value in values),
                    negative_mean_candidates=sum(value<0 for value in values),
                    flat_mean_candidates=sum(value==0 for value in values)))
            pairs=[]
            for left in sorted(expected):
                for right in sorted(expected):
                    observations=[(matrix[cid][left]["mean_net_daily_return"],matrix[cid][right]["mean_net_daily_return"]) for cid in ids]
                    paired=[(x,y) for x,y in observations if x is not None and y is not None and math.isfinite(x) and math.isfinite(y)]
                    x,y=zip(*paired) if paired else ((),())
                    rho=float(spearmanr(x,y).statistic) if len(paired)>=3 and len(set(x))>1 and len(set(y))>1 else None
                    pairs.append(dict(left=left,right=right,paired_candidates=len(paired),spearman=rho))
            results[namespace][family]=dict(states=states,rank_associations=pairs)
    return dict(schema="mode5.finite_panel_regime_qualification.v1",views=results,
        diagnostic_candidates=len(ids),selected_arms=len(selected),
        unit="decimal net account return per observed day; conditional descriptive, not annualized",
        rank_basis="diagnostic panel only; no later formal outcomes enter the reference",
        role="post-selection descriptive; cannot change a sealed recipe or winner",
        independent_regimes=False,optimizer_proposals=0,financial_executions=0)
