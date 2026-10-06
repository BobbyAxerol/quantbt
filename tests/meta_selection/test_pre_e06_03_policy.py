"""Nested cohort identity and exact historical Mode 4 family compatibility."""

import ast
from dataclasses import replace
from types import SimpleNamespace

import pytest

from quantbt.optimization.meta_selection import runtime
from quantbt.optimization.meta_selection.common import digest
from quantbt.optimization.meta_selection.descriptors import DescriptorSchema
from quantbt.optimization.meta_selection.nested import family_policy
from tests.meta_selection import pre_e06_02_support as original
from tests.meta_selection.pre_e06_03_support import endpoint, RANGES
from tools.qms_pre03_source_guard import baseline


def family(config, function=runtime.PublicMetaRuntime.compatibility_family):
    scorer = SimpleNamespace(_meta_adapter=SimpleNamespace(contract=SimpleNamespace(metric_id="original-365")),
        _meta_economics_id="same-costs", meta_route_id="original-endpoint-reset-v1")
    engine = SimpleNamespace(config=config, scorer=scorer, strategy=original.strategy)
    return function(engine, SimpleNamespace(instrument_id="SYNTHETIC", timeframe="1D"), DescriptorSchema(RANGES))


def test_pre03_mode4_family_is_exact_baseline_not_rehashed_extension():
    # Execute the original function, not a manually reconstructed hash formula.
    tree = ast.parse(baseline("src/quantbt/optimization/meta_selection/runtime.py"))
    old_class = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "PublicMetaRuntime")
    old = next(n for n in old_class.body if isinstance(n, ast.FunctionDef) and n.name == "compatibility_family")
    old.decorator_list = []
    module = ast.fix_missing_locations(ast.Module(body=[old], type_ignores=[]))
    namespace = dict(vars(runtime))
    exec(compile(module, "historical-family-ca57fc3", "exec"), namespace)
    cfg = original.endpoint("signal_notional", original.tape("signal_notional"), "shadow").config.walkforward_config
    assert family(cfg) == family(cfg, namespace["compatibility_family"])
    assert family(cfg).family_id == family(cfg, namespace["compatibility_family"]).family_id


@pytest.mark.parametrize("field,value", [
    ("inner_split_frequency", "weekly"), ("inner_window_mode", "rolling"),
    ("inner_train_window", "31D"), ("inner_min_folds", 3),
    ("min_train_bars", 17), ("min_test_bars", 5),
    ("decay_lambda", .7), ("decay_gamma", .8),
    ("candidate_decay_lambda", .6), ("candidate_decay_gamma", .9),
    ("top_is_fraction", .2),
])
def test_pre03_inner_and_decay_policies_are_separate_compatibility_families(field, value):
    cfg = endpoint("signal_notional", original.tape("signal_notional"), "shadow").config.walkforward_config
    assert family(cfg).family_id != family(replace(cfg, **{field: value})).family_id


def test_pre03_nested_cohort_cannot_import_mode4_origins():
    from quantbt.optimization.meta_selection.history import MetaHistory
    from tests.meta_selection.test_qms05_public import run as mode4_run
    from tests.meta_selection.test_qms05_public import reviewed_history, sidecar
    from tests.meta_selection.pre_e06_03_support import run

    template = sidecar(mode4_run("shadow")[1])["tasks"][0]
    history, revision = reviewed_history(template)
    cfg = endpoint("signal_notional", original.tape("signal_notional"), "shadow").config.walkforward_config
    assert revision.task.family.family_id != family(cfg).family_id
    value = run("signal_notional", "active", history=history,
        data=original.current(original.tape("signal_notional"), original.CUTOFFS[0]), start="2022-05-01")
    assert value.meta["snapshots"][0].origin_count == 0
    assert value.meta["records"][0]["final_selection_reason"] == "META_SUPPORT_INSUFFICIENT"
    assert value.meta["tasks"][0].sampling_provenance["cohort"] == family_policy(cfg)["cohort"]
    assert digest(value.meta["tasks"][0].sampling_provenance["inner_policy"]) == digest(family_policy(cfg)["inner_policy"])
    assert isinstance(history, MetaHistory)
