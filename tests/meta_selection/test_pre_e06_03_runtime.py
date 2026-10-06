"""C01 activation, original outer-window witnesses and native inner ownership."""

from dataclasses import replace
import math

import numpy as np
import optuna
import pandas as pd

import pytest

from quantbt.optimization.meta_selection.config import validate_meta_route
from tests.meta_selection import pre_e06_02_support as previous
from tests.meta_selection.pre_e06_03_support import ROUTES, CUTOFFS, endpoint, run

optuna.logging.set_verbosity(optuna.logging.WARNING)


@pytest.mark.parametrize("route", ROUTES)
def test_pre03_approved_nested_scalar_route_passes_preflight(route):
    bt = previous.endpoint(route, previous.tape(route), "active")
    wf = replace(bt.config.walkforward_config, optimization_mode="mode_1_decay",
        candidate_selection_metric="robust_decay", inner_split_frequency="monthly",
        inner_window_mode="expanding", inner_train_window="30D", inner_min_folds=2)
    validate_meta_route(wf)


@pytest.mark.parametrize("route", previous.ROUTES[5:])
def test_pre03_nested_non_scalar_routes_remain_closed_before_work(route):
    bt = previous.endpoint("signal_notional", previous.tape("signal_notional"), "active")
    wf = replace(bt.config.walkforward_config, target_mode=route,
        optimization_mode="mode_1_decay", candidate_selection_metric="robust_decay",
        inner_split_frequency="monthly", inner_window_mode="expanding",
        inner_train_window="30D", inner_min_folds=2)
    with pytest.raises(ValueError, match="META_METHODOLOGY_UNSUPPORTED|META_ROUTE_UNSUPPORTED"):
        validate_meta_route(wf, route="reactive_reset" if route == "reactive_reset" else "target_series")


@pytest.mark.parametrize("route", ROUTES)
def test_pre03_full_outer_pool_and_original_inner_anchor_are_distinct(route, monkeypatch):
    from quantbt.walkforward import WalkForwardEngine
    native_optimize = WalkForwardEngine.optimize_params
    trace = []

    def delegated(self, **kwargs):
        selected, records, candidates = native_optimize(self, **kwargs)
        trace.append((kwargs["folds"], selected, records, candidates))
        return selected, records, candidates

    monkeypatch.setattr(WalkForwardEngine, "optimize_params", delegated)
    cutoff=CUTOFFS[0]
    value=run(route, "shadow", data=previous.current(previous.tape(route), cutoff), start="2022-05-01")
    assert len(trace) == 1
    inner, native, records, candidates = trace[0]
    sidecar, task = value.meta["records"][0], value.meta["tasks"][0]
    eligible=[r for r in records if not r.pruned and r.selection_metadata.get("stage") == "is_search"
              and math.isfinite(r.objective) and r.selection_metadata.get("feasible",True)]
    assert sidecar["auxiliary_outer_is_evaluations"] == len(eligible) == len(task.candidates)
    assert len(eligible) > len(candidates)
    assert sidecar["native_inner_decay_objective"] == native.objective == max(c.objective for c in candidates)
    assert sidecar["native_selected_params"] == native.params
    assert sidecar["cohort"] == "nested_anchor_outer_IS_real_forward_v1"
    assert all(f.test_index[-1] <= task.data_cutoff and f.train_index[-1] < f.test_index[0] for f in inner)
    table=value.result.metadata["walk_forward"]["inner_fold_table"]
    assert len(table) == len(inner) >= 2
    for c in task.candidates:
        original=previous.independent(value,task,c)
        report=original.full_report(scope="full",trading_days=365)
        assert c.observation.raw_sharpe == report["sharpe"]
        assert c.observation.activity_count == report["num_trades"]
        record=next(r for r in eligible if r.trial_id==c.native_trial_id)
        assert c.objective == record.objective
        assert c.observation.window_start==task.is_start and c.observation.window_end==task.is_end
    assert sidecar["native_raw_is_sharpe"] == task.anchor.observation.raw_sharpe


def test_pre03_missing_inner_validation_does_not_copy_anchor_metrics():
    from quantbt.walkforward import WalkForwardTrialRecord
    from quantbt.optimization.meta_selection.nested import NestedCapturedPool, selected_record
    from quantbt.optimization.meta_selection.descriptors import DescriptorSchema
    from quantbt.optimization.meta_selection.records import CandidateISRecord, MetricObservation, OutcomeStatus
    from quantbt.optimization.meta_selection.common import digest
    date=pd.Timestamp("2022-01-01",tz="UTC")
    params={"window":3}
    source=WalkForwardTrialRecord(2,params,1.2,1.2,0.,0.,0.,[],selection_metadata={"stage":"is_search"})
    anchor=WalkForwardTrialRecord(0,{"window":9},7.,9.,8.,1.,.3,[],selection_metadata={"source_trial_id":0})
    observation=MetricObservation(OutcomeStatus.VALID,4.,3,10,.1,"metric","cost",date,date,date,
        20000.,20100.,"outer","input","original_result")
    c=CandidateISRecord("eval","candidate",2,params,params,source.objective,observation,date,{})
    pool=NestedCapturedPool(0,0,731,DescriptorSchema(previous.RANGES),(c,),"anchor",digest(anchor.params),
        1,(source,),date,.01)
    selected=selected_record(anchor,c,pool)
    assert selected.objective==1.2 and selected.params==params
    assert math.isnan(selected.mean_oos_sharpe) and math.isnan(selected.mean_decay)
    assert selected.selection_metadata["selected_inner_validation_objective"] is None
    assert selected.selection_metadata["source_trial_id"] == source.trial_id
    assert selected.selection_metadata["candidate_id"] is None
    assert selected.selection_metadata["source_is_objective"] == source.objective
    assert selected.selection_metadata["actual_objective_scope"]=="inner_IS_adaptive_search"
