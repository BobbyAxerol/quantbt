"""Seal exact E02 search/account/selection baselines, without an economic claim."""

import argparse
from hashlib import sha256
import json
from pathlib import Path

import optuna
import numpy as np

from tools.qms_e01_audit import snapshot as native_snapshot
from tools.qms05_public import execute
from quantbt.optimization.meta_selection.common import digest, wire


def array_signature(value):
    array = np.ascontiguousarray(value, dtype=np.float64)
    return dict(shape=array.shape, sha256=sha256(array.tobytes()).hexdigest())


def snapshot():
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    native = native_snapshot()
    scalar = {}
    for mode, observer in (("off", False), ("shadow", False), ("shadow", True), ("active", True)):
        row = execute(mode, observer=observer)
        scalar[f"{mode}-{observer}"] = {
            k: row[k] for k in ("scientific_signature", "selected_params_by_fold",
                               "observer_attempts", "observer_failures", "switches", "account_authority")
        }
        scalar[f"{mode}-{observer}"]["decisions"] = [{k: r[k] for k in (
            "family_id", "native_selected_evaluation_id", "selected_evaluation_id",
            "eligible_is_pool_size", "training_revision_ids", "final_selection_reason")}
            for r in row["records"]]
    from tests.meta_selection.test_local_reactive import execute as reactive_execute
    reactive = {}
    for mode in (None, "shadow", "active"):
        result, _, runtime = reactive_execute(mode)
        try:
            meta = result.metadata.get("meta_selection")
            reactive[str(mode)] = dict(params=wire({str(k): v for k, v in result.params_by_fold.items()}),
                objective=digest(array_signature(result.trial_table.objective)),
                account=digest([{key: array_signature(getattr(row.result, key).to_numpy())
                    for key in ("equity", "returns", "positions", "fees", "funding", "margin")}
                    for row in result.fold_results]),
                tasks=[dict(family=t.family.family_id, anchor=t.anchor.evaluation_id,
                    candidates=[wire(c.observation) for c in t.candidates])
                    for t in meta["tasks"]] if meta else [],
                decisions=[{key: r[key] for key in ("family_id", "native_selected_evaluation_id",
                    "selected_evaluation_id", "panel_members", "final_selection_reason")}
                    for r in meta["records"]] if meta else [])
        finally:
            runtime.close()
    return wire(dict(schema="qms-e02-baseline-v1", native=native, scalar=scalar, reactive=reactive,
                     publication=False, economic_claim=False))


def compare(old, new):
    assert old["schema"] == new["schema"] == "qms-e02-baseline-v1"
    assert old["native"]["lanes"] == new["native"]["lanes"]
    assert old["native"]["guide_sha256"] == new["native"]["guide_sha256"]
    for name, value in old["native"]["historical_receipts"].items():
        assert new["native"]["historical_receipts"].get(name) == value, name
    for name, before in old["scalar"].items():
        after = new["scalar"][name]
        assert {k: v for k, v in before.items() if k != "decisions"} == {
            k: v for k, v in after.items() if k != "decisions"}
        assert len(before["decisions"]) == len(after["decisions"])
        for a, b in zip(before["decisions"], after["decisions"], strict=True):
            # Original observer receipts include measured availability clocks;
            # those revision bytes differ even in two unchanged wall-time runs.
            assert {k: v for k, v in a.items() if k != "training_revision_ids"} == {
                k: v for k, v in b.items() if k != "training_revision_ids"}
            assert len(a["training_revision_ids"]) == len(b["training_revision_ids"])
    assert old["reactive"] == new["reactive"]
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("baseline is sealed; choose a fresh output")
    result = snapshot()
    failed = False
    if args.baseline:
        try:
            result["exact_parity"] = compare(json.loads(args.baseline.read_text()), result)
        except AssertionError:
            result["exact_parity"] = False
            failed = True
        result["baseline_sha256"] = sha256(args.baseline.read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(dict(exact_parity=result.get("exact_parity"), routes=8, scalar_lanes=4)))
    if failed:
        raise AssertionError("E02 exact baseline mismatch; actual failed snapshot retained")
