"""Public result/endpoint access from synthetic saved records, no simulation."""

from types import SimpleNamespace

from quantbt import QuantBTEndpoint
from quantbt.diagnostics import ResearchDecisionReport
from examples.shared_decision_reporting import example_inputs


def example_result(count=12):
    rows,_,access,cohorts=example_inputs(count)
    metadata=dict(optimization_mode='mode_4_is_only_robust',optimization_schedule='per_fold_causal',
        meta_selection=dict(schema='qms-public-run-v1',config=dict(mode='active'),
            current_outer_oos_used_for_selection=False,tasks=tuple(r.revision.task for r in rows),
            observed_revisions=tuple(r.revision for r in rows),records=tuple(dict(
                fold_id=r.fold_id,task_id=r.revision.task.task_id,current_outer_oos_used_for_selection=False,
                native_optimization_mode='mode_4_is_only_robust',proposal=r.decision,
                selected_evaluation_id=r.decision.actual_evaluation_id,
                selected_params=dict(r.decision.proposed_params),matured_origins=12,
                training_snapshot_id=r.decision.training_snapshot_id) for r in rows)))
    return SimpleNamespace(metadata=dict(walk_forward=metadata)),access,cohorts


def example_report():
    result,access,cohorts=example_result()
    return ResearchDecisionReport.from_result(result,access=access,
        source_ref='synthetic-original-run',role='synthetic',cohorts=cohorts)


if __name__=='__main__':
    result,access,cohorts=example_result()
    # This shell owns no account/engine and never calls backtest or simulate.
    endpoint=object.__new__(QuantBTEndpoint)
    endpoint.result=result
    report=endpoint.research_report(access=access,source_ref='synthetic-original-run',role='synthetic',cohorts=cohorts)
    assert report.identity==example_report().identity
    print(report.to_markdown())
