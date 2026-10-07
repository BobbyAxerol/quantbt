"""Installed-only full-work comparison with the sealed public PRE05 corpus."""

import argparse
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import subprocess
import sys


def identity(expected):
    import quantbt
    import _quantbt_native as native
    import _quantbt_native._quantbt_native as extension
    base = Path(quantbt.__file__).resolve().parent
    if "site-packages" not in base.parts or quantbt.__version__ != "1.1.2" or native.version() != "0.4.3":
        raise ValueError("noninstalled/wrong package pair")
    actual = {p.relative_to(base).as_posix(): sha256(p.read_bytes()).hexdigest()
              for p in base.rglob("*") if p.is_file() and (p.suffix == ".py" or p.name == "py.typed")}
    if actual != expected:
        raise ValueError("installed canonical source inventory mismatch")
    native_hash = sha256(Path(extension.__file__).read_bytes()).hexdigest()
    if native_hash != "e338a0f1549395211dc42332ed15eb43c0bb92f71728ca3181b0268f56a57aba":
        raise ValueError("installed extension hash mismatch")
    return dict(core="1.1.2", native="0.4.3", core_origin=str(base), native_sha256=native_hash,
                modules=len(actual), dependencies={n: version(n) for n in (
                    "numpy", "pandas", "numba", "optuna", "scipy", "cmaes", "arch", "scikit-learn")})


def origins(base):
    for name, module in tuple(sys.modules.items()):
        if name == "quantbt" or name.startswith("quantbt."):
            origin = getattr(module, "__file__", None)
            if origin is not None and not Path(origin).resolve().is_relative_to(base):
                raise ValueError(f"checkout runtime substitution: {name}")


def main(args):
    registration = json.loads(args.registration.read_text())
    package = identity(registration["core_inventory"])
    # Only public fixtures/tools are loaded from the repository, after the core.
    sys.path.append(str(args.root))
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    from tools.qms_pre06_contract import validate_matrix, write_once
    from tests.meta_selection.test_pre04_latent import (
        BINDING, ExactStudySession, advance, continuation_config,
    )
    if args.resume is not None:
        session = ExactStudySession.loads(args.resume.read_text(), config=continuation_config(),
                                         binding=BINDING, expected_digest=args.digest)
        advance(session, 21)
        origins(Path(package["core_origin"]))
        write_once(args.output, dict(identity=package, witness=session.witness()))
        return
    from tools.qms_pre05_workloads import cells, execute, metadata, prepare, semantic
    records = {}
    for cell in cells():
        result_context = prepare(cell, args.root / ".maturin/qms08/pre-e06-05")
        result = execute(result_context, cell)
        value, _ = semantic(result, cell, result_context[2])
        meta = metadata(result, cell).get("meta_selection", {})
        records[cell.identity] = dict(
            mode=cell.mode, semantic_sha256=value,
            expected_sha256=registration["expected_cells"][cell.identity],
            models=len(meta.get("models", {})),
            minimum_origins=min((r["matured_origins"] for r in meta.get("records", [])), default=0),
            observer_failures=meta.get("observer_failures", 0), skipped=0)
        print(json.dumps(dict(cell=cell.identity, parity=value == records[cell.identity]["expected_sha256"])), flush=True)
    validate_matrix(records, registration["expected_cells"])
    from examples.wfo_conditional_policies import execute as conditional
    _, conditional_result = conditional()
    studies = conditional_result.metadata["walk_forward"]["sampler_studies"]
    if not studies or not all(s.get("latent_stream") for s in studies):
        raise ValueError("conditional runtime did not execute")
    full, partial = (ExactStudySession(continuation_config(), binding=BINDING) for _ in range(2))
    advance(full, 40)
    advance(partial, 19)
    text, digest = partial.dumps()
    journal = args.output.with_suffix(".journal.json")
    with journal.open("x") as stream:
        stream.write(text)
    resumed = args.output.with_suffix(".resumed.json")
    process = subprocess.run([sys.executable, "-I", __file__, "--root", str(args.root),
                              "--registration", str(args.registration), "--resume", str(journal),
                              "--digest", digest, "--output", str(resumed)],
                             capture_output=True, text=True, check=False)
    log = args.output.with_suffix(".resume.log")
    with log.open("x") as stream:
        stream.write(process.stdout + process.stderr)
    if process.returncode or json.loads(resumed.read_text())["witness"] != full.witness():
        raise ValueError("fresh installed conditional continuation mismatch")
    origins(Path(package["core_origin"]))
    proof = dict(schema="qms-pre06-installed-full-work-v1", identity=package, cells=records,
                 conditional_actual_folds=len(studies), exact_conditional_continuation=True,
                 continuation_states=sorted({t.state.name for t in full.trials}),
                 installed_only=True, skipped=0, publication=False)
    write_once(args.output, proof)
    print(json.dumps(dict(status="PASS_INSTALLED_FULL_WORK", cells=len(records), **package)), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--registration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--digest")
    main(parser.parse_args())
