"""Deliberately synthetic validator inputs; never installed/financial evidence."""

from tools.qms_release_consumers import RECIPES


def records(core="1.1.2", native="0.4.3", w3=None):
    w3 = dict(core_version=core, native_version=native, off_shadow_exact=True,
              same_pass=True, selected_lineage=True, closed=True, observer_failures=0) if w3 is None else dict(w3)
    w3.setdefault("c02_transport", dict(original_pool_account_witness_exact=True,
        native_tokens=True, closed_children=True, market_ipc_bytes_per_task=0))
    return {"qms08_consumer.py": dict(core_version=core, native_version=native,
        active_reference_prepared_parity=True, off_shadow_parity=True, actual_meta_folds=6,
        sampler_recipes=list(RECIPES), numeric_blocks={"selected_backend_by_block": {"gram_solve": "rust"}}),
        "qms_local_consumer.py": w3,
        "qms_c03_consumer.py": dict(core=core, native=native, closed_children=True,
            process_recipes=4, frozen_pool_recipes=4, financial_account_policy="segmented_reset_flat",
            matrix=[dict(recipe=r, scheduler=s, repeat_account_exact=True, attempts=16, states={"COMPLETE": 16})
                    for r in RECIPES for s in ("certified_sequential_v1", "throughput_batch_v1")],
            meta_matrix=[dict(recipe=r, mode=m, pool_exact=True, selected_lineage=True,
                same_pass_observer=True, actual_rust_fit=True, process_pool_account_exact=True,
                shadow_account_exact=m == "shadow") for r in RECIPES for m in ("shadow", "active")]),
        "qms_c04_consumer.py": dict(core=core, native=native, no_source_imports=True, no_financial_replay=True,
            matrix=[dict(recipe=r, attempts=48, split=23, fresh_process_exact=True,
                states=["COMPLETE", "FAIL", "PRUNED"]) for r in RECIPES])}
