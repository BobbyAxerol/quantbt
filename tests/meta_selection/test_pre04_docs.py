"""Current user discoverability and runnable actual conditional strategy."""

from tools.check_docs_links import validate_links
from tools.qms_pre04_source_guard import ROOT

DOCS = ("upgrade/implement.md", "docs/meta_selection/CONDITIONAL_POLICIES.md",
    "docs/meta_selection/PRE_E06_04_REPORT.md", "docs/meta_selection/SAMPLERS.md",
    "docs/meta_selection/USAGE.md", "docs/meta_selection/EXACT_CONTINUATION.md",
    "docs/meta_selection/CURRENT_ROUTE_REVIEW.md", "docs/meta_selection/GAP_CLOSURE_STATUS.md",
    "docs/meta_selection/QUALIFICATION.md", "docs/meta_selection/W3_SAMPLER_SCHEDULES.md",
    "docs/meta_selection.md", "handoff/WFO_META_CURRENT.md")


def test_policy_documentation_links_and_anchors():
    assert validate_links(ROOT, check_anchors=True, files=[ROOT/n for n in DOCS]) == []


def test_runnable_example_actual_conditional_strategy():
    from examples.wfo_conditional_policies import execute
    endpoint, result = execute()
    config = endpoint.config.walkforward_config
    assert config.optimization_mode == "mode_4_is_only_robust"
    assert config.optimization_schedule == "per_fold_causal"
    wf = result.metadata["walk_forward"]
    for st in wf["sampler_studies"]:
        assert st["attempts"] == 16 and st["latent_stream"]["next_qmc_index"] == 15
        assert st["latent_stream"]["dimensions"] == ["window", "filter_window"]
        for row in st["rows"]:
            params = row["effective_params"]
            assert ("filter_window" in params) == params["use_filter"]
    assert wf["best_trial"]["selection_metadata"]["auxiliary_is_evaluations"] == 0
