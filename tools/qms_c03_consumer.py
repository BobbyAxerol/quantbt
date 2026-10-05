"""Isolated installed four-recipe W3/R3B proof, without source-path imports."""

from dataclasses import replace
from hashlib import sha256
import importlib.metadata as metadata
import importlib.util
import json
from pathlib import Path
import sys


def example_module(path):
    spec = importlib.util.spec_from_file_location("c03_public_example", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def accounts_equal(a, b):
    import numpy as np

    assert a.params == b.params and a.params_by_fold == b.params_by_fold
    for left, right in zip(a.fold_results, b.fold_results, strict=True):
        for field in ("equity", "returns", "positions", "fees", "funding", "margin"):
            np.testing.assert_array_equal(getattr(left.result, field), getattr(right.result, field))


def qualify(*, example, core_version, native_version):
    import multiprocessing
    import optuna
    import quantbt
    import _quantbt_native as native
    from quantbt.optimization.meta_selection.config import MetaHistoryContext
    from quantbt.optimization.meta_selection.history import MetaHistory
    from quantbt.optimization.meta_selection.common import wire
    from quantbt.optimization.space import stable_params_key

    assert "site-packages" in Path(quantbt.__file__).resolve().parts
    assert metadata.version("quantbt-engine") == quantbt.__version__ == core_version
    assert metadata.version("quantbt-native") == native.version() == native_version
    origin = Path(native.__file__).resolve()
    binaries = [origin] if origin.suffix == ".so" else list(origin.parent.glob("_quantbt_native*.so"))
    assert len(binaries) == 1 and "site-packages" in binaries[0].parts
    assert native.qms_numeric_descriptor_v1()["abi"] == "qms-numeric-v1"
    assert hasattr(native.ReactiveCandidateBatchRunnerCore, "cancellation_tokens")
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    fixture = example_module(example)
    matrix, meta_rows = [], []
    for recipe in fixture.RECIPES:
        sequential = None
        for scheduler in ("certified_sequential_v1", "throughput_batch_v1"):
            first = fixture.execute(recipe, scheduler=scheduler)
            second = fixture.execute(recipe, scheduler=scheduler)
            accounts_equal(first, second)
            study = first.metadata["sampler_studies"][0]
            repeated = second.metadata["sampler_studies"][0]
            assert study["rows"] == repeated["rows"] and study["ask_tell_digest"] == repeated["ask_tell_digest"]
            assert study["attempts"] == 16 and study["states"] == {"COMPLETE": 16}
            if scheduler == "certified_sequential_v1":
                sequential = first
                process = fixture.execute(recipe, worker="process")
                accounts_equal(first, process)
                assert study["rows"] == process.metadata["sampler_studies"][0]["rows"]
            else:
                one = fixture.execute(recipe, scheduler=scheduler, batch_size=1)
                accounts_equal(sequential, one)
                assert sequential.metadata["sampler_studies"][0]["rows"] == one.metadata["sampler_studies"][0]["rows"]
                pool = [row["effective_params"] for row in study["rows"]]
                fixed = fixture.execute(config=replace(fixture.configuration(recipe), sampler_config=None),
                    scheduler=scheduler, candidate_matrix=pool,
                    ranges={"qty": (.5, 2.), "hold": (2, 8), "direction": 1.})
                accounts_equal(first, fixed)
                actual = {stable_params_key(r.params): r.objective for r in first.trial_table.itertuples() if not r.pruned}
                replay = {stable_params_key(r.params): r.objective for r in fixed.trial_table.itertuples() if not r.pruned}
                assert actual == replay and fixed.metadata["sampling_contract"] == "fixed_candidate_matrix_r3b_v1"
            matrix.append(dict(recipe=recipe, scheduler=scheduler, sampler_class=study["sampler_class"],
                optuna_version=study["optuna_version"], attempts=study["attempts"], states=study["states"],
                qmc_sequence_position=study["qmc_sequence_position"], ask_tell_digest=study["ask_tell_digest"],
                repeat_account_exact=True, sampling_contract=first.metadata["sampling_contract"]))
        config = fixture.configuration(recipe, schedule="per_fold_causal", trials=12)
        off = fixture.execute(config=config)
        for mode in ("shadow", "active"):
            result = fixture.execute(config=replace(config, meta_selection=dict(mode=mode,
                native_batch_policy="require", min_matured_origins=1, label_observer=True)),
                meta_history=MetaHistoryContext(MetaHistory(), "installed-C03", "BTC", "1D", "engineering"))
            for a, b in zip(off.metadata["sampler_studies"], result.metadata["sampler_studies"], strict=True):
                assert a["rows"] == b["rows"] and a["ask_tell_digest"] == b["ask_tell_digest"]
            if mode == "shadow":
                accounts_equal(off, result)
            meta = result.metadata["meta_selection"]
            assert meta["observer_attempts"] > 0 and meta["observer_failures"] == 0
            assert any(r["numeric_backend"]["selected_backend_by_block"].get("gram_solve") == "rust"
                       for r in meta["records"])
            assert all(r["selected_params"] == result.params_by_fold[r["fold_id"]]
                       and not r["current_outer_oos_used_for_selection"] for r in meta["records"])
            meta_rows.append(dict(recipe=recipe, mode=mode, pool_exact=True, selected_lineage=True,
                same_pass_observer=True, actual_rust_fit=True, shadow_account_exact=mode == "shadow"))
    assert not multiprocessing.active_children()
    return wire(dict(schema="qms-c03-installed-consumer-v1", core=core_version, native=native_version,
        core_origin=str(Path(quantbt.__file__).resolve()), native_origin=str(binaries[0]),
        native_sha256=sha256(binaries[0].read_bytes()).hexdigest(),
        example_sha256=sha256(Path(example).read_bytes()).hexdigest(), python=sys.version,
        matrix=matrix, meta_matrix=meta_rows, process_recipes=4, frozen_pool_recipes=4,
        closed_children=True, financial_account_policy="segmented_reset_flat", economic_claim=False,
        publication=False))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--example", type=Path, required=True)
    parser.add_argument("--core-version", required=True)
    parser.add_argument("--native-version", required=True)
    print(json.dumps(qualify(**vars(parser.parse_args())), sort_keys=True))
