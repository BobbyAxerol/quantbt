"""Shared fail-closed scalar, transport, sampler and continuation evidence."""

RECIPES = ("tpe_legacy", "tpe_multivariate_group", "cmaes", "sobol")
EXAMPLES = {"qms_c03_consumer.py": "wfo_reactive_samplers.py",
            "qms_c04_consumer.py": "optimization_exact_continuation.py"}
CONSUMERS = ("qms08_consumer.py", "qms_local_consumer.py", *EXAMPLES)


def consumer_arguments(name, *, core, native, examples):
    args = ["--core-version", core, "--native-version", native]
    if name == "qms_local_consumer.py":
        args.append("--witness-transport")
    elif name in EXAMPLES:
        args.extend(["--example", str(examples / EXAMPLES[name])])
    elif name != "qms08_consumer.py":
        raise ValueError("unknown QMS installed consumer")
    return args


def validate_consumers(records, *, core, native, require_extended=True):
    required = CONSUMERS if require_extended else CONSUMERS[:2]
    if any(name not in records for name in required):
        raise ValueError("missing required installed QMS consumer")
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
    if require_extended:
        validate_extensions(records, core=core, native=native)
    return True


def validate_extensions(records, *, core, native):
    transport = records["qms_local_consumer.py"].get("c02_transport") or {}
    if (any(transport.get(k) is not True for k in (
            "original_pool_account_witness_exact", "native_tokens", "closed_children"))
            or transport.get("market_ipc_bytes_per_task") != 0):
        raise ValueError("installed C02 transport proof failed")
    c03, c04 = records["qms_c03_consumer.py"], records["qms_c04_consumer.py"]
    for record in (c03, c04):
        if (record.get("core"), record.get("native")) != (core, native):
            raise ValueError("installed C03/C04 pair mismatch")
    matrix = c03.get("matrix", [])
    expected = {(r, s) for r in RECIPES for s in ("certified_sequential_v1", "throughput_batch_v1")}
    if (len(matrix) != 8 or {(r.get("recipe"), r.get("scheduler")) for r in matrix} != expected
            or any(r.get("repeat_account_exact") is not True or r.get("attempts") != 16
                   or r.get("states") != {"COMPLETE": 16} for r in matrix)
            or c03.get("process_recipes") != 4 or c03.get("frozen_pool_recipes") != 4
            or c03.get("closed_children") is not True
            or c03.get("financial_account_policy") != "segmented_reset_flat"):
        raise ValueError("installed C03 scheduler proof failed")
    meta = c03.get("meta_matrix", [])
    if (len(meta) != 8 or {(r.get("recipe"), r.get("mode")) for r in meta}
            != {(r, m) for r in RECIPES for m in ("shadow", "active")}
            or any(any(r.get(k) is not True for k in (
                "pool_exact", "selected_lineage", "same_pass_observer", "actual_rust_fit",
                "process_pool_account_exact")) or r.get("mode") == "shadow"
                and r.get("shadow_account_exact") is not True for r in meta)):
        raise ValueError("installed C03 original-pass meta proof failed")
    continuation = c04.get("matrix", [])
    if (len(continuation) != 4 or {r.get("recipe") for r in continuation} != set(RECIPES)
            or any(r.get("fresh_process_exact") is not True or r.get("attempts") != 48
                   or r.get("split") != 23 or r.get("states") != ["COMPLETE", "FAIL", "PRUNED"]
                   for r in continuation)
            or c04.get("no_source_imports") is not True or c04.get("no_financial_replay") is not True):
        raise ValueError("installed C04 fresh-process continuation proof failed")
