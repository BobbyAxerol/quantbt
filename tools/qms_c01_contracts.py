"""Review-only native methodology map, not a runtime capability registry."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MethodologyCase:
    mode: str
    schedule: str
    adaptive_input: str
    final_selection_input: str
    decision_frontier: str
    native_anchor: str
    meta_status: str
    proposed_cohort: str


CASES = (
    MethodologyCase("mode_1_decay", "global", "all_train_folds",
        "all_train_and_test_folds", "last_selection_observation",
        "final_oos_candidate_selector", "UNSUPPORTED_REVIEW_REQUIRED",
        "separate_retrospective_calibration_tasks"),
    MethodologyCase("mode_1_decay", "per_fold_decay", "outer_IS",
        "outer_IS_and_current_outer_OOS", "outer_test_end",
        "final_oos_candidate_selector", "UNSUPPORTED_REVIEW_REQUIRED",
        "selection_adjusted_not_pristine_forward"),
    MethodologyCase("mode_1_decay", "per_fold_causal", "inner_train_folds",
        "inner_train_and_validation_within_outer_IS", "outer_train_end",
        "final_inner_decay_selector", "UNSUPPORTED_REVIEW_REQUIRED",
        "nested_anchor_outer_IS_real_forward_v1_proposed"),
    MethodologyCase("mode_2_sbb", "global", "synthetic_IS_proxy_returns",
        "real_OOS_rerank_for_default_robust_decay", "last_selection_observation",
        "final_oos_candidate_selector", "UNSUPPORTED_REVIEW_REQUIRED",
        "separate_real_forward_and_synthetic_stress_tasks"),
    MethodologyCase("mode_3_flat_minima", "global", "all_train_folds",
        "real_OOS_rerank_for_default_robust_decay", "last_selection_observation",
        "final_oos_candidate_selector_not_first_plateau", "UNSUPPORTED_REVIEW_REQUIRED",
        "separate_retrospective_plateau_anchor_tasks"),
    MethodologyCase("mode_4_is_only_robust", "global", "all_train_folds",
        "IS_robustness_OOS_scored_as_diagnostics", "last_train_observation",
        "final_IS_robust_candidate", "UNSUPPORTED_REVIEW_REQUIRED",
        "retrospective_multi_fold_calibration_not_fold_causal"),
    MethodologyCase("mode_4_is_only_robust", "per_fold_causal", "outer_IS",
        "outer_IS_temporal_and_plateau", "outer_train_end",
        "final_IS_robust_candidate", "SUPPORTED_EXISTING",
        "existing_mode4_real_forward_family"),
    MethodologyCase("mode_5_full_robust", "global", "entire_declared_sample",
        "entire_declared_sample_robustness", "sample_end",
        "final_full_sample_candidate", "UNSUPPORTED_REVIEW_REQUIRED",
        "deployment_calibration_with_separate_later_forward"),
)


def review_case(mode, schedule):
    for case in CASES:
        if (case.mode, case.schedule) == (mode, schedule):
            return case
    raise ValueError(f"C01 review has no native route: {mode}/{schedule}")
