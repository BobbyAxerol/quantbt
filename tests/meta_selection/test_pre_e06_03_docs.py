"""Current discovery/docs and runnable source-level nested example."""

import pytest

from examples.wfo_meta_nested import execute_nested, make_nested_endpoint
from tools.check_docs_links import validate_links
from tools.qms_pre03_source_guard import ROOT

DOCS = (
    "docs/meta_selection.md", "docs/meta_selection/NESTED_MODE1.md",
    "docs/meta_selection/PRE_E06_03_REPORT.md", "docs/meta_selection/USAGE.md",
    "docs/meta_selection/INTEGRATION.md", "docs/meta_selection/QUALIFICATION.md",
    "docs/meta_selection/CURRENT_ROUTE_REVIEW.md", "docs/meta_selection/GAP_CLOSURE_STATUS.md",
    "docs/meta_selection/DOMAIN_ADAPTER_CONTRACT.md", "docs/endpoint.md",
    "docs/walkforward_causal.md", "docs/walkforward_methodology_vi.md",
    "handoff/WFO_META_CURRENT.md", "upgrade/implement.md",
)


def test_pre03_current_links_have_real_files_and_anchors():
    assert validate_links(ROOT, check_anchors=True, files=[ROOT/n for n in DOCS]) == []


@pytest.mark.parametrize("target", ("signal_notional", "notional", "unit", "pct_equity", "dca_ladder"))
def test_pre03_example_declares_exact_nested_contract(target):
    from quantbt.optimization.meta_selection.config import validate_meta_route
    c=make_nested_endpoint(target).config.walkforward_config
    validate_meta_route(c)
    assert c.optimization_mode=="mode_1_decay" and c.optimization_schedule=="per_fold_causal"
    assert c.meta_selection.min_matured_origins==12
    assert c.meta_selection.lambda_reg==10. and c.meta_selection.q_hat_floor==-.1


def test_pre03_runnable_example_off_and_shadow_native_winner_and_account_match():
    from tests.meta_selection.pre_e06_02_support import account_equal
    a, x, _ = execute_nested("signal_notional", "off")
    b, y, _ = execute_nested("signal_notional", "shadow")
    account_equal(x, y)
    wx, wy = (v.metadata["walk_forward"] for v in (x,y))
    assert wx["params_by_fold"]==wy["params_by_fold"]
    assert wy["meta_selection"]["records"][0]["cohort"]=="nested_anchor_outer_IS_real_forward_v1"
    assert a.config.walkforward_config.meta_selection is None
    assert b.config.walkforward_config.meta_selection.mode=="shadow"
