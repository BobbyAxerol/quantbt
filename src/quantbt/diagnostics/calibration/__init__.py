"""Explicit diagnostics-to-calibration handoff, not an automatic recipe router."""
from .worksheet import CalibrationRecipe, CalibrationWorksheet
from .pack import Mode5RunPack
from .reconcile import CalibrationRunReport
from .donors import ArchiveDonorPlan, CoordinateDonorTarget
from .donor_binding import continuous_donor_target


def calibration_handoff_capabilities():
    """Additive cold-workflow capabilities, not a new financial route registry."""
    return dict(schema="quantbt.calibration_handoff.capabilities.v1", opt_in=True,
        archive_required=False, automatic_routing=False, source_qualification_only=True,
        calibration="existing ContinuousMode5Calibration on walk_forward",
        executable_attribution="continuous_account_calendar_years",
        report_only_views=["quarter", "regime", "transition", "temporal_regret"],
        report_views_require_retained_authorized_evidence=True,
        market_index="explicit_timezone_aware", dataframe_attrs="not_qualified_without_manifest_extension",
        external_evidence_required=True, private_pack_export=True,
        explicit_complete_archive_coordinates=True, archive_scores_imported=False,
        winner_qualification='result.research_report(qualification=WinnerQualificationRequest(...))',
        exact_full_wfo_resume=False, deployment_authorized=False)


__all__ = ["CalibrationRecipe", "CalibrationWorksheet", "Mode5RunPack", "CalibrationRunReport",
           "calibration_handoff_capabilities", "ArchiveDonorPlan", "CoordinateDonorTarget",
           "continuous_donor_target"]
