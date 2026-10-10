"""M5T-101..104/109: whole-prefix rights, reviewed history and actual stress."""
import pytest

from quantbt.mode5.diagnostics.access import AccessPolicy, AccessWitness
from tools.mode5_economics import validation_rights, cached_validation_rights, prefix_rights, StressRequest


def witness(role="DEVELOPMENT_REVIEWED",start=10,end=20,ready=20):
    return AccessWitness("same-market",role,start,end,ready)


def access(role="DEVELOPMENT_REVIEWED",purpose="selection",cutoff=100):
    return AccessPolicy("frozen",(role,),("same-market",),cutoff,purpose)


def test_full_sample_parent_cannot_gain_independent_claim_from_child():
    proof=validation_rights(frozen_at_ns=50,first_execution_ns=60,witness=witness(),access=access())
    assert proof.data["parent_validation_claim"] == "none_full_sample_calibration"
    assert proof.data["validation_claim"] == "reviewed_exploratory"
    assert not proof.data["deployment_authorized"]


@pytest.mark.parametrize("kind", ["diagnostics","candidate_discovery","recipe","market","preprocessing","labels"])
def test_future_or_immature_input_blocks_entire_prefix(kind):
    inputs=[(k,witness()) for k in ("diagnostics","candidate_discovery","recipe","market")]
    inputs.append((kind,witness(start=80,end=99,ready=101)))
    with pytest.raises(PermissionError,match="future or immature"):
        prefix_rights(inputs,access=access(),origin_ns=100)


def test_complete_prefix_proof_is_not_whole_recipe_validation():
    inputs=[(k,witness()) for k in ("diagnostics","candidate_discovery","recipe","market")]
    proof=prefix_rights(inputs,access=access(),origin_ns=100)
    assert not proof.data["whole_procedure_validation"]
    with pytest.raises(ValueError,match="complete pipeline"):
        prefix_rights(inputs[:-1],access=access(),origin_ns=100)


def test_reviewed_2024_never_becomes_clean_holdout_by_new_label():
    fresh=witness(role="independent_validation")
    with pytest.raises(PermissionError,match="laundered"):
        validation_rights(frozen_at_ns=50,first_execution_ns=60,witness=fresh,
            access=access(role="independent_validation",purpose="independent_validation"),
            reviewed_witnesses=(witness(role="EXPLORATORY_REVIEWED_2024"),),requested_claim="independent_fixed_vector")


def test_untouched_forward_is_authorized_only_after_actual_freeze():
    w=witness(role="independent_validation")
    proof=validation_rights(frozen_at_ns=50,first_execution_ns=60,witness=w,
        access=access(role=w.role,purpose="independent_validation"),requested_claim="independent_fixed_vector")
    assert proof.data["validation_claim"] == "independent_fixed_vector"
    with pytest.raises(PermissionError,match="freeze"):
        validation_rights(frozen_at_ns=60,first_execution_ns=50,witness=w,access=access())


def test_actual_dynamic_stress_rejects_fixed_fill_fee_proxy():
    request=StressRequest("baseline","actual-vector","higher-costs","fee/slippage")
    with pytest.raises(ValueError,match="proxy"):
        request.execute(lambda req: dict(method="FIXED_FILL_FEE_ARITHMETIC",params_digest=req.params_digest,
            economic_contract=req.stressed_economic_contract,accounting_verified=True,execution_id="invented"))
    result=request.execute(lambda req: dict(method="ACTUAL_ACCOUNT_RESIMULATION",params_digest=req.params_digest,
        economic_contract=req.stressed_economic_contract,accounting_verified=True,execution_id="real-stress"))
    assert result.data["execution_id"] == "real-stress"


def test_cached_reviewed_execution_is_not_a_new_post_freeze_run():
    proof=cached_validation_rights(witness=witness(),access=access(purpose="diagnostic"),source_receipt_id="qualified-original")
    assert not proof.data["reexecuted_account"] and not proof.data["new_post_freeze_execution"]
    with pytest.raises(PermissionError,match="independent"):
        cached_validation_rights(witness=witness(),access=access(purpose="diagnostic"),source_receipt_id="qualified-original",
            requested_claim="independent_fixed_vector")


def test_cached_witness_still_revalidates_current_data_permissions():
    with pytest.raises(PermissionError,match="future or immature"):
        cached_validation_rights(witness=witness(ready=101),access=access(purpose="diagnostic",cutoff=100),
            source_receipt_id="qualified-original")
