"""Shared fail-closed scalar/W3 checks for exact installed release consumers."""


def validate_consumers(records, *, core, native):
    scalar, w3 = records["qms08_consumer.py"], records["qms_local_consumer.py"]
    for record in (scalar, w3):
        if (record.get("core_version"), record.get("native_version")) != (core, native):
            raise ValueError("installed QMS release pair mismatch")
    if (scalar.get("active_reference_prepared_parity") is not True
            or scalar.get("off_shadow_parity") is not True
            or scalar.get("actual_meta_folds") != 6
            or scalar.get("sampler_recipes") != ["tpe_legacy", "tpe_multivariate_group", "cmaes", "sobol"]
            or scalar.get("numeric_blocks", {}).get("selected_backend_by_block", {}).get("gram_solve") != "rust"):
        raise ValueError("installed QMS scalar/sampler/Rust proof failed")
    if (any(w3.get(k) is not True for k in ("off_shadow_exact", "same_pass", "selected_lineage", "closed"))
            or w3.get("observer_failures") != 0):
        raise ValueError("installed QMS W3 proof failed")
    return True
