"""Run registered E03 arms sequentially, retaining every failure and raw log."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter

from tools.qms_e03_study import CELLS, read_registration, summarize


def prepared_trace_parity(plain, prepared):
    import numpy as np
    from tools.qms_real_review import trial_trace
    a, b = trial_trace(plain), trial_trace(prepared)
    assert len(a) == len(b)
    for left, right in zip(a, b, strict=True):
        for key in ("trial_id", "params", "pruned", "fold_id"):
            assert left[key] == right[key], key
        for key in ("objective", "mean_is_sharpe"):
            if isinstance(left[key], (int, float)) and isinstance(right[key], (int, float)):
                np.testing.assert_allclose(left[key], right[key], rtol=1e-9, atol=1e-9)
            else:
                assert left[key] == right[key], key


def queue(output, *, prepared=True):
    output = Path(output).resolve()
    registration, identity = read_registration(output)
    cells = [(t, b, a, "off") for t, b in CELLS for a in ("off", "active")]
    if prepared:
        cells += [(t, "native_vectorized", "active", "require") for t in ("notional", "unit")]
    environment = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1",
                       MKL_NUM_THREADS="1", NUMBA_NUM_THREADS="1")
    environment.pop("PYTHONPATH", None)
    for target, backend, arm, preparation in cells:
        name = f"{target}-{backend}-{arm}-{preparation}"
        receipt = output / f"{name}.json"
        if receipt.exists():
            existing = json.loads(receipt.read_text())
            if (existing["registration_sha256"] != identity or
                    existing["source_sha256"] != registration["source"]["source_sha256"] or
                    existing["attempts"] != 28*128):
                raise ValueError(f"cannot resume unmatched sealed arm: {name}")
            print(json.dumps(dict(arm=name, stage="existing_sealed_arm")), flush=True)
            continue
        command = [sys.executable, "-m", "tools.qms_e03_study", "worker", "--output", str(output),
                   "--target", target, "--backend", backend, "--arm", arm, "--prepared", preparation]
        ordinal = 1
        while (output / f"{name}-attempt-{ordinal}.log").exists():
            ordinal += 1
        log = output / f"{name}-attempt-{ordinal}.log"
        began = perf_counter()
        print(json.dumps(dict(arm=name, stage="worker_started")), flush=True)
        with log.open("w") as stream:
            with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, env=environment) as process:
                for line in process.stdout:
                    stream.write(line)
                    stream.flush()
                    if line.startswith('{"cell":'):
                        print(line.rstrip(), flush=True)
                code = process.wait()
        execution = dict(arm=name, attempt=ordinal, elapsed_seconds=perf_counter()-began,
                         exit_code=code, log_sha256=sha256(log.read_bytes()).hexdigest())
        with (output / "queue-executions.jsonl").open("a") as stream:
            stream.write(json.dumps(execution)+"\n")
        if code or not receipt.exists():
            raise RuntimeError(f"registered worker failed; preserved {log}; no automatic retry")
    summary = summarize(output)
    if prepared:
        import numpy as np
        for target in ("notional", "unit"):
            names = [f"{target}-native_vectorized-active-{p}" for p in ("off", "require")]
            plain, prepared_run = [json.loads((output / f"{n}.json").read_text()) for n in names]
            prepared_trace_parity(plain, prepared_run)
            assert plain["params"] == prepared_run["params"]
            with np.load(output / f"{names[0]}.npz") as a, np.load(output / f"{names[1]}.npz") as b:
                for key in a.files:
                    np.testing.assert_allclose(a[key], b[key], rtol=1e-9, atol=1e-8)
    print(json.dumps(dict(stage="queue_complete", cells=len(summary["rows"]),
                          empirical_promotion=False, publication=False)), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--skip-prepared", action="store_true")
    args = parser.parse_args()
    queue(args.output, prepared=not args.skip_prepared)
