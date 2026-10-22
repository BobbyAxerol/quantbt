"""Rebuild approved metric repair, prove exact installed pair, never publish."""

import argparse
import json
import os
from pathlib import Path

from tools.qms08_package import ROOT, build_tool, declared_pair, file_hash, run
from tools.qms_c02_package import qualify as build_core
from tools.qms_g01_source_guard import verify
from tools.qms_installed_consumers import qualify as consumers
from tools.qms_g01_installed import validate_consumer


def prove_retained(output):
    output = Path(output).resolve()
    destination = output/"g01-refresh-proof.json"
    if destination.exists():
        raise ValueError("retained proof already sealed; never overwrite execution evidence")
    base_path = output/"g01-proof.json"
    base = json.loads(base_path.read_text())
    source = verify()
    if base["source"] != source or tuple(base["pair"]) != declared_pair():
        raise ValueError("retained G01 source or release pair changed")
    for artifact in base["artifact_refs"]:
        path = ROOT/artifact["path"]
        if file_hash(path) != artifact["sha256"] or path.stat().st_size != artifact["bytes"]:
            raise ValueError("retained G01 artifact changed")
    proof = dict(core=base["pair"][0], native=base["pair"][1], artifact_refs=base["artifact_refs"])
    rows = {}
    interpreter = output/"consumer/bin/python"
    for name, pattern in (("wheel", "*.whl"), ("sdist", "*.tar.gz")):
        artifact = next((output/"dist").glob(pattern))
        run([build_tool("uv"), "pip", "install", "--offline", "--python", interpreter,
             "--no-deps", "--reinstall", artifact], cwd=output, log=output/f"g01-refresh-{name}-install.log")
        log = output/f"g01-refresh-{name}-consumer.log"
        row = json.loads(run([interpreter, "-I", ROOT/"tools/qms_g01_consumer.py"],
            cwd=output/"workspace", log=log).splitlines()[-1])
        validate_consumer(row, proof)
        rows[name] = dict(result=row, log_sha256=file_hash(log))
    receipt = dict(schema="qms-g01-retained-artifact-reproof-v1", source=source,
        base_proof_sha256=file_hash(base_path), consumer_source_sha256=file_hash(ROOT/"tools/qms_g01_consumer.py"),
        consumers=rows, artifact_refs=base["artifact_refs"], publication=False)
    destination.write_text(json.dumps(receipt, indent=2, sort_keys=True)+"\n")
    return receipt


def qualify(*, output, build_python, python):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("use a fresh G01 lane; preserve failed and historical evidence")
    source = verify()
    native_dist = output.parent / (output.name + "-native")
    if native_dist.exists():
        raise ValueError("native lane exists; do not overwrite sealed artifacts")
    native_dist.mkdir(parents=True)
    old_target = os.environ.get("CARGO_TARGET_DIR")
    os.environ["CARGO_TARGET_DIR"] = str(ROOT/"rust/target/qms08-candidate")
    try:
        run([build_tool("maturin"), "build", "--offline", "--locked", "--release",
            "--manifest-path", ROOT/"rust/native_event/Cargo.toml", "--interpreter", python,
            "--out", native_dist], cwd=ROOT, log=native_dist/"build.log")
    finally:
        if old_target is None:
            os.environ.pop("CARGO_TARGET_DIR", None)
        else:
            os.environ["CARGO_TARGET_DIR"] = old_target
    native = next(native_dist.glob("*.whl"))
    base = build_core(output=output, build_python=build_python, native_wheel=native, python=python)
    interpreter = output/"consumer/bin/python"
    run([build_tool("uv"), "pip", "install", "--offline", "--python", interpreter, "pytest"],
        cwd=output, log=output/"test-dependencies.log")
    records = {}
    core_version, native_version = declared_pair()
    for name, pattern in (("wheel", "*.whl"), ("sdist", "*.tar.gz")):
        artifact = next((output/"dist").glob(pattern))
        run([build_tool("uv"), "pip", "install", "--offline", "--python", interpreter,
            "--no-deps", "--reinstall", artifact], cwd=output, log=output/f"g01-{name}-install.log")
        records[name] = consumers([interpreter], root=ROOT, core=core_version, native=native_version,
            workspace=output/"workspace", logs=output/f"g01-{name}-mandatory")
        for tool, args in (("qms_e03_consumer.py", ["--example", ROOT/"examples/wfo_meta_scalar.py"]),
            ("qms_e04_consumer.py", ["--example", ROOT/"examples/wfo_meta_portfolio.py"]),
            ("qms_e05_consumer.py", ["--example", ROOT/"examples/wfo_meta_package.py"]),
            ("qms_g01_consumer.py", [])):
            records[name][tool] = json.loads(run([interpreter, "-I", ROOT/"tools"/tool, *args],
                cwd=output/"workspace", log=output/f"g01-{name}-{tool}.log").splitlines()[-1])
    receipt = dict(schema="qms-g01-installed-compatibility-v1", source=source,
        pair=[core_version, native_version], native_rebuilt=True, consumers=records,
        artifact_refs=base["artifact_refs"], native_build_log_sha256=file_hash(native_dist/"build.log"),
        publication=False, empirical_promotion=False)
    (output/"g01-proof.json").write_text(json.dumps(receipt, indent=2, sort_keys=True)+"\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reprove-retained", action="store_true")
    for name in ("build-python", "python"):
        parser.add_argument("--"+name, type=Path)
    args = parser.parse_args()
    if args.reprove_retained:
        result = prove_retained(args.output)
    else:
        if args.build_python is None or args.python is None:
            parser.error("fresh qualification requires --build-python and --python")
        result = qualify(output=args.output, build_python=args.build_python, python=args.python)
    print(json.dumps(dict(installed=list(result["consumers"]), publication=False)))
