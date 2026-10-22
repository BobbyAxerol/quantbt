"""Prospective whole-account mandate; not an annual-return sign constraint."""
from copy import deepcopy

import pytest

from quantbt.mode5.continuous_eligibility import WholeAccountEligibility
from quantbt.mode5.diagnostics.identity import digest
from quantbt.mode5.dossier.records import Record
from tools.mode5_research.raw_control import RawControlSeal


def observed(value=.1, *, quality=True, risk=True, support=True, sharpe=.3):
    return dict(quality_pass=quality, risk_pass=risk, support_pass=support, raw_sharpe=sharpe,
                utility={"value": value, "status": "VALID"})


def test_negative_annual_quality_is_diagnostic_not_whole_account_gate():
    whole = observed()
    annual = (observed(-.2, quality=False), observed(.8))
    original = deepcopy(annual)
    policy = WholeAccountEligibility()
    rows = policy.project(whole, annual)
    assert annual == original
    assert policy.eligible(whole, annual)
    assert rows[0]["utility"]["value"] == -.2
    assert rows[0]["quality_pass"] is True and rows[0]["environment_quality_diagnostic"] is False
    assert rows[0]["quality_pass_basis"] == policy.metadata()["schema"]


@pytest.mark.parametrize("kind", ["whole_quality", "whole_risk", "whole_support", "annual_risk", "annual_support", "undefined_whole", "undefined_annual"])
def test_common_control_and_challenger_eligibility_reject_same_failure(kind):
    whole, annual = observed(), [observed()]
    if kind.startswith("whole_"):
        whole[kind.removeprefix("whole_")+"_pass"] = False
    elif kind.startswith("annual_"):
        annual[0][kind.removeprefix("annual_")+"_pass"] = False
    elif kind == "undefined_whole":
        whole["raw_sharpe"] = None
    else:
        annual[0]["utility"].update(value=None, status="UNDEFINED")
    assert not WholeAccountEligibility().eligible(whole, annual)


def test_nonfinite_whole_score_and_unknown_policy_fail_closed():
    with pytest.raises(ValueError, match="finite original"):
        WholeAccountEligibility().project(observed(sharpe=float("nan")), [observed()])
    with pytest.raises(ValueError, match="complete frozen"):
        WholeAccountEligibility.read({**WholeAccountEligibility.metadata(), "require_finite_whole_sharpe": False})
    with pytest.raises(ValueError, match="complete frozen"):
        WholeAccountEligibility.read({**WholeAccountEligibility.metadata(), "require_finite_whole_sharpe": 1})


def test_absent_raw_policy_preserves_original_seal_digest_and_new_policy_changes_it():
    values = dict(contract_identity=digest("account"), dossier_identity=digest("dossier"),
        provider_qualification_identity=digest("qualification"), registration_identity=digest("approval"),
        budget=256, seed=731, batch_size=1)
    old = digest(dict(schema="mode5.raw_whole_sharpe_control.v1", **values,
        objective="original_raw_whole_account_sharpe", eligibility="finite_whole_sharpe_only",
        tie_break="candidate_id_lexicographic_v1"))
    assert RawControlSeal(**values).identity == old
    assert RawControlSeal(**values, eligibility_policy=Record.of(WholeAccountEligibility.metadata())).identity != old


def test_absent_binding_policy_preserves_original_bytes_and_explicit_option_changes_them(tmp_path):
    from test_continuous_runtime import continuous_setup
    from quantbt.mode5.continuous_binding import continuous_calibration_binding, restore_geometry
    from quantbt.mode5.diagnostics.access import AccessWitness
    from quantbt.optimization import SamplerConfig
    _, _, _, calibration = continuous_setup(tmp_path)
    b = calibration.binding.data
    c = b["continuous"]
    args = dict(geometry=restore_geometry(c["geometry"]), source=Record.of(c["source"]),
        execution=Record.of(c["execution"]), witness=AccessWitness(**c["witness"]),
        windows=calibration.windows, reference=calibration.reference,
        sampler=SamplerConfig(**b["sampler"]), metrics=b["metrics"], selection=b["selection"],
        batch_size=b["batch_size"], warm_start=tuple(b["warm_start"]), local_offsets=b["local_offsets"])
    assert continuous_calibration_binding(**args) == calibration.binding
    new = continuous_calibration_binding(**args, eligibility_policy=WholeAccountEligibility())
    assert new.identity != calibration.binding.identity
    assert new.data["metrics"] == b["metrics"] and new.data["continuous"]["geometry"] == c["geometry"]
    with pytest.raises(ValueError, match="typed prospective"):
        continuous_calibration_binding(**args, eligibility_policy=WholeAccountEligibility(), quality_floor_comparison="strict_greater_v1")


def test_actual_public_whole_policy_reports_actual_unchanged_measurements(tmp_path):
    from test_continuous_runtime import continuous_setup
    from quantbt.mode5 import DecisionReport
    endpoint, data, ranges, calibration = continuous_setup(tmp_path, eligibility_policy=WholeAccountEligibility())
    result = endpoint.backtest(data=data, param_ranges=ranges)
    wf = result.metadata["walk_forward"]
    metadata = wf["mode5_diagnostics_first"]
    assert metadata["eligibility_policy"] == WholeAccountEligibility.metadata()
    assert calibration.binding.data["continuous"]["eligibility_policy"] == metadata["eligibility_policy"]
    for row in metadata["trial_ledger"]:
        if "whole_observation" not in row:
            continue
        whole = row["whole_observation"]
        for view in row["observations"]:
            assert view["quality_pass"] is (whole["quality_pass"] and whole["raw_sharpe"] is not None)
            assert view["quality_pass_basis"] == WholeAccountEligibility.metadata()["schema"]
    report = DecisionReport.read(metadata, selected_params=wf["best_trial"]["params"])
    assert report.to_dict()["runtime"]["eligibility_policy"] == metadata["eligibility_policy"]
    assert DecisionReport.from_json(report.to_json(private=True)) == report


def test_actual_raw_common_policy_filters_selection_not_sampler_observation(tmp_path):
    from dataclasses import replace
    from test_raw_control import actual_query
    from tools.mode5_research.raw_control import RawWholeControl
    original, query, _, scorer = actual_query(tmp_path, budget=3)
    raw = RawWholeControl(replace(original.seal, eligibility_policy=Record.of(WholeAccountEligibility.metadata())),
                          original.contract, original.bridge.bridge)
    def under_unsupported_whole(params, trial):
        request, account = query(params, trial)
        altered = Record.of({**account.whole.data, "quality_pass": False})
        return request, replace(account, whole=altered)
    try:
        metadata = raw.run(under_unsupported_whole).data
        assert metadata["status"] == "NO_SELECTION" and metadata["selected_candidate"] is None
        assert metadata["complete_rows"] > 0
        assert metadata["eligible_complete_rows"] == 0
        assert metadata["gate_excluded_complete_rows"] == metadata["complete_rows"]
        assert all(row["score"] is not None for row in metadata["trial_ledger"] if row["state"] == "COMPLETE")
    finally:
        scorer.release_prepared_state()
