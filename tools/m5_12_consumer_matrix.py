"""Reviewed synthetic installed-consumer roster; counts are gates, not claims."""

from hashlib import sha256
import json

EXECUTION_CASE = "tools/m5_12_consumer_features.py::test_bounded_mode5_cross_mode_execution"
EXECUTION_PROPERTY = "m5_12_bounded_execution"
PROPOSAL_LIMIT = 12
FINANCIAL_LIMIT = 23

FEATURES = {
    "diagnostics": {"tools/m5_12_consumer_features.py::test_shared_diagnostics": 1},
    "calibration": {"tools/m5_12_consumer_features.py::test_cold_calibration": 1, EXECUTION_CASE: 1},
    "winner": {
        "tests/mode5/test_winner_report.py::test_numeric_runnerup_and_raw_best_expose_return_risk_and_activity_tradeoffs": 1,
        "tests/mode5/test_winner_report.py::test_frozen_copy_detached_exports_and_expected_identity_roundtrip": 1,
        "tests/mode5/test_winner_report.py::test_qualification_rejects_unsupported_mode_and_mismatched_selected_dictionary": 1,
    },
    "donor": {
        "tests/mode5/test_coordinate_donors.py::test_complete_coordinates_are_researcher_ordered_and_sampler_compatible": 1,
        "tests/mode5/test_coordinate_donors.py::test_separate_coordinate_source_requires_current_selection_rights": 1,
        "tests/mode5/test_coordinate_donors.py::test_coordinate_digest_is_the_exact_canonical_archive_execution_digest": 1,
        "tests/mode5/test_coordinate_donors.py::test_cold_construction_and_reload_do_not_rank_import_scores_or_consume_rng": 1,
    },
    "reporting_v1": {
        "tools/m5_12_consumer_features.py::test_reporting_example": 1,
        "tests/metrics/test_acc01_bankruptcy_reporting.py::test_f18_public_bankruptcy_preserves_account_drawdown_ledger_execution": 8,
    },
    "acc_account": {
        "tools/m5_12_consumer_features.py::test_portfolio_daily_funding": 1,
        "tools/m5_12_consumer_features.py::test_portfolio_executed_liquidation_report": 1,
        "tests/test_acc01_event_vectorized.py::test_t01_t05_effective_minimum_and_matched_financial_control": 3,
        "tests/test_acc01_event_vectorized.py::test_t08_valid_vectorized_slippage_and_t10_capacity": 1,
        "tests/test_acc01_event_vectorized.py::test_t02_package_liquidation_uses_executed_costs_not_position_reconstruction": 2,
    },
    "acc_options": {
        "tests/options/test_acc01_reporting.py::test_f03_mismatched_wallet_rejected_before_execution": 4,
        "tests/options/test_acc01_reporting.py::test_f03_opening_tolerance_and_run_fx_override": 1,
        "tests/options/test_acc01_reporting.py::test_f04_f15_fee_currency_and_clock_follow_effective_event": 4,
        "tests/options/test_acc01_reporting.py::test_f06_supported_option_buffer_still_controls_admission": 1,
        "tests/options/test_acc01_configuration.py::test_f06_generic_option_account_nondefaults_are_rejected": 7,
    },
}

# Only these public synthetic inputs leave the checkout. No source package,
# repository conftest, private data or source-path bootstrap is copied.
FIXTURES = {name: name for name in (
    "tools/m5_12_consumer_matrix.py", "tools/m5_12_consumer_runtime.py",
    "tools/m5_12_consumer_features.py", "tools/m5_12_consumer_budget.py",
    "examples/shared_alpha_diagnostics.py", "examples/mode5_diagnostic_handoff.py",
    "examples/reporting_metrics_v1.py", "examples/mode5_cross_mode_qualification.py",
    "tests/mode5/test_winner_report.py",
    "tests/mode5/test_decision_report.py", "tests/mode5/test_coordinate_donors.py",
    "tests/metrics/test_acc01_bankruptcy_reporting.py", "tests/test_acc01_event_vectorized.py",
    "tests/options/test_acc01_reporting.py", "tests/options/test_acc01_configuration.py",
    "tests/options/conftest.py",
)}
FIXTURES["tools/m5_12_consumer_fixtures.py"] = "tests/mode5/selection_fixtures.py"

REQUIRED_MODULES = (
    "quantbt.diagnostics", "quantbt.diagnostics.calibration.pack",
    "quantbt.diagnostics.calibration.donors", "quantbt.diagnostics.winner.report",
    "quantbt.metrics.reporting.public", "quantbt.backends.native_event",
    "quantbt.backends.native_vectorized", "quantbt.backends.native_option",
    "quantbt.backends.native_portfolio", "quantbt.backends.portfolio_reports",
    "quantbt.backends.option_validation",
    "_quantbt_native._quantbt_native",
)

REQUIRED_FIXTURE_MODULES = {
    "examples.shared_alpha_diagnostics": "examples/shared_alpha_diagnostics.py",
    "examples.mode5_diagnostic_handoff": "examples/mode5_diagnostic_handoff.py",
    "examples.reporting_metrics_v1": "examples/reporting_metrics_v1.py",
    "examples.mode5_cross_mode_qualification": "examples/mode5_cross_mode_qualification.py",
    "selection_fixtures": "tests/mode5/selection_fixtures.py",
    "test_decision_report": "tests/mode5/test_decision_report.py",
    "m512_option_fixtures": "tests/options/conftest.py",
}


def selectors():
    return {node: count for feature in FEATURES.values() for node, count in feature.items()}


def validate_outcomes(collected, reports):
    """Require every exact selected parametrization and all three pytest phases."""
    expected = selectors()
    if len(collected) != len(set(collected)):
        raise ValueError("duplicate installed test IDs")
    actual = {node: [] for node in expected}
    for node in collected:
        selector = node.split("[", 1)[0]
        if selector not in actual:
            raise ValueError("unapproved installed test collected")
        actual[selector].append(node)
    if {node: len(ids) for node, ids in actual.items()} != expected:
        raise ValueError("missing or changed installed feature collection")
    if set(reports) != set(collected):
        raise ValueError("missing installed test execution")
    for phases in reports.values():
        if phases != {"setup": "passed", "call": "passed", "teardown": "passed"}:
            raise ValueError("skipped, failed, xfailed or incomplete installed feature")
    return {feature: dict(tests=sum(nodes.values()), passed=sum(nodes.values()), skipped=0)
            for feature, nodes in FEATURES.items()}


def execution_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def validate_execution(execution, optimizer):
    """Validate retained observations, not merely a requested budget or PASS flag."""
    if not isinstance(execution, dict) or not isinstance(optimizer, dict):
        raise ValueError("bounded execution summary and observed optimizer budget required")
    expected = dict(execution_case=EXECUTION_CASE, execution_cases=1, proposal_limit=12,
        financial_limit=23, create_study_calls=4, optimize_trials=[2, 2], ask_calls=12,
        tell_calls=8, walkforward_runs=3, forbidden_calls=[], observed_proposals=12)
    integers = ("execution_cases", "proposal_limit", "financial_limit", "create_study_calls",
                "ask_calls", "tell_calls", "walkforward_runs", "observed_proposals")
    if (optimizer != expected or any(type(optimizer.get(key)) is not int for key in integers)
            or any(type(value) is not int for value in optimizer.get("optimize_trials", ()))):
        raise ValueError("missing, changed or exceeded observed optimizer budget")
    summary = execution.get("summary")
    raw = execution.get("summary_json")
    if (not isinstance(summary, dict) or not isinstance(raw, str)
            or sha256(raw.encode()).hexdigest() != execution.get("summary_sha256")
            or json.loads(raw) != summary):
        raise ValueError("retained execution summary bytes mismatch")
    protocol = execution.get("protocol", {})
    if (any(type(protocol.get(key)) is not int for key in
            ("proposal_slots", "financial_invocation_ceiling", "retries"))
            or protocol.get("proposal_slots") != PROPOSAL_LIMIT
            or protocol.get("financial_invocation_ceiling") != FINANCIAL_LIMIT
            or protocol.get("donor_folds") != [0] or protocol.get("retries") != 0
            or protocol.get("automatic_routing") is not False):
        raise ValueError("missing or changed registered execution budget")
    if (summary.get("schema") != "quantbt.synthetic_cross_mode_run.v1"
            or summary.get("status") != "COMPLETED_SYNTHETIC_MECHANICS"
            or type(summary.get("observed_proposals")) is not int or summary["observed_proposals"] != 12
            or type(summary.get("financial_invocation_ceiling")) is not int
            or summary["financial_invocation_ceiling"] != FINANCIAL_LIMIT
            or type(summary.get("observed_financial_invocations")) is not int
            or not 0 < summary["observed_financial_invocations"] <= FINANCIAL_LIMIT):
        raise ValueError("missing, changed or exceeded actual proposal/financial budget")
    work = summary.get("work", {})
    if set(work) != {"mode4", "baseline", "challenger"}:
        raise ValueError("complete original three-arm work counts required")
    for arm, ceiling in (("mode4", 11), ("baseline", 6), ("challenger", 6)):
        row = work[arm]
        if (type(row.get("proposals")) is not int or row["proposals"] != 4
                or type(row.get("financial_invocations")) is not int
                or not 0 < row["financial_invocations"] <= ceiling):
            raise ValueError("actual per-arm work exceeds registered bounded protocol")
    if (sum(row["proposals"] for row in work.values()) != summary["observed_proposals"]
            or sum(row["financial_invocations"] for row in work.values()) != summary["observed_financial_invocations"]):
        raise ValueError("retained summary totals do not reconcile with original work")
    if (summary.get("baseline_warm_start_attempts") != 0
            or summary.get("challenger_warm_start_attempts") != 1
            or summary.get("challenger_attempts") != 4
            or summary.get("donor_evidence_ids") != ["mode4-fold-0"]
            or summary.get("archive_score_dispositions") != {
                "mode4-fold-0": "TARGETED_EXECUTION_REQUIRED", "mode4-fold-1": "TARGETED_EXECUTION_REQUIRED"}
            or execution.get("reconciliation_statuses") != {
                "baseline": "RECONCILED_RETAINED_RUN", "challenger": "RECONCILED_RETAINED_RUN"}
            or execution.get("winner_baseline_status") != "SOURCE_BOUND_SELECTED_PATHS"
            or execution.get("winner_report_id") != summary.get("winner_report_id")
            or execution.get("winner_candidate_id") != summary.get("challenger_winner_id")
            or execution.get("baseline_candidate_id") != summary.get("baseline_winner_id")):
        raise ValueError("actual winner/donor application or reconciliation incomplete")
    planned, applied = execution.get("planned_donor_params"), execution.get("applied_donor_params")
    if (not isinstance(planned, list) or len(planned) != 1 or not isinstance(planned[0], dict)
            or not planned[0] or applied != planned or execution.get("donor_sources") != ["warm_start"]):
        raise ValueError("actual donor coordinates differ from explicit selected fold")
    for key in ("donor_plan_id", "baseline_winner_id", "challenger_winner_id", "winner_report_id"):
        value = summary.get(key)
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("actual completed winner/donor identity required")
    if (summary.get("economic_superiority") != "NOT_QUALIFIED"
            or summary.get("independent_validation") != "NOT_PERFORMED"
            or summary.get("automatic_routing") is not False or summary.get("deployment_authorized") is not False):
        raise ValueError("bounded synthetic execution cannot promote economics or authority")
