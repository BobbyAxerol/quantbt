"""Replay the unchanged registered unit study after the approved metric repair."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil

from tools.qms_e03_study import read_registration
from tools.qms_real_review import dump, private_path
from tools.qms_g01_source_guard import ROOT, verify


def register(*, original, output):
    original, output = private_path(original), private_path(output)
    registration, identity = read_registration(original)
    if output.exists():
        raise ValueError("do not overwrite original or previous replay evidence")
    source = verify()
    failed = original/"unit-native_vectorized-active-require.json"
    if not failed.is_file():
        raise ValueError("missing preserved original failing unit study")
    output.mkdir(parents=True)
    shutil.copy2(original/"e03-registration.json", output/"e03-registration.json")
    receipt = dict(schema="qms-g01-replay-registration-v1", original_registration_sha256=identity,
        original_failing_receipt_sha256=sha256(failed.read_bytes()).hexdigest(), source=source,
        scientific_config_unchanged=True, no_economic_retuning=True, publication=False)
    dump(output/"g01-replay-registration.json", receipt)
    return receipt


def verify_installed_source(output, installed, expected):
    from tools.qms_e04_source_guard import without_e04_portfolio
    output = private_path(output)
    amendment = json.loads((output/"g01-replay-registration.json").read_text())
    _, identity = read_registration(output)
    if amendment["original_registration_sha256"] != identity or amendment["source"] != verify():
        raise ValueError("G01 replay registration/source amendment changed")
    for name, expected_hash in expected.items():
        actual = (installed/name.removeprefix("src/quantbt/")).read_bytes()
        original = without_e04_portfolio(actual, name)
        if sha256(original).hexdigest() != expected_hash:
            raise ValueError(f"G01 replay changed registered scalar source: {name}")
    for name, value in amendment["source"]["source_sha256"].items():
        if name.startswith("src/quantbt/"):
            actual = installed/name.removeprefix("src/quantbt/")
            if sha256(actual.read_bytes()).hexdigest() != value:
                raise ValueError(f"G01 installed compatibility source drift: {name}")
    return amendment


def compare(*, original, output):
    import numpy as np
    from tools.qms_e03_queue import prepared_trace_parity
    original, output = private_path(original), private_path(output)
    prefix = "unit-native_vectorized-active-"
    historical = json.loads((original/(prefix+"off.json")).read_text())
    ordinary = json.loads((output/(prefix+"off.json")).read_text())
    prepared = json.loads((output/(prefix+"require.json")).read_text())
    for left, right in ((historical, ordinary), (ordinary, prepared)):
        prepared_trace_parity(left, right)
        if left["params"] != right["params"]:
            raise AssertionError("registered selected params changed")
        if len(left["paired"]) != len(right["paired"]):
            raise AssertionError("forward label coverage changed")
        for a, b in zip(left["paired"], right["paired"], strict=True):
            for field in ("fold_id", "start", "end", "matured_origins"):
                if a[field] != b[field]:
                    raise AssertionError(f"chronological label identity changed: {field}")
            for side in ("native", "meta"):
                if a[side]["status"] != b[side]["status"]:
                    raise AssertionError("label validity changed")
                for field in ("is_sharpe", "forward_sharpe"):
                    if a[side][field] is None or b[side][field] is None:
                        if a[side][field] != b[side][field]:
                            raise AssertionError("undefined label changed")
                    else:
                        np.testing.assert_allclose(a[side][field], b[side][field], rtol=1e-9, atol=1e-9)
    for preparation in ("off", "require"):
        with np.load(original/(prefix+"off.npz")) as a, np.load(output/(prefix+preparation+".npz")) as b:
            if set(a.files) != set(b.files):
                raise AssertionError("account buffers changed")
            for key in a.files:
                np.testing.assert_allclose(a[key], b[key], rtol=1e-9, atol=1e-8)
    receipt = dict(schema="qms-g01-unit-replay-v1", prepared_gate="PASS",
        registration_sha256=ordinary["registration_sha256"], attempts_per_arm=ordinary["attempts"],
        historical_ordinary_parity=True, prepared_pool_objective_params_account_parity=True,
        raw_label_chronology_parity=True,
        tolerances=dict(objective_rtol=1e-9, objective_atol=1e-9, account_atol=1e-8),
        ordinary_seconds=ordinary["wall_seconds"], prepared_seconds=prepared["wall_seconds"],
        source=verify(), raw_receipts_sha256={p:sha256((output/(prefix+p+".json")).read_bytes()).hexdigest()
            for p in ("off", "require")}, empirical_promotion=False, publication=False)
    dump(output/"g01-replay-proof.json", receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("register", "compare"))
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(globals()[args.action](original=args.original, output=args.output), sort_keys=True))
