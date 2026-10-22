"""Fresh E01 core artifacts with byte-verified unchanged local native ownership."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess

from tools.qms_c02_package import qualify as build_core
from tools.qms_e01_source_guard import verify
from tools.qms_installed_consumers import qualify as installed
from tools.qms08_package import ROOT, build_tool, file_hash, run


def qualify(*, output, build_python, python, native_baseline):
    output = output.resolve()
    if output.exists():
        raise ValueError("use a fresh E01 artifact lane")
    baseline = native_baseline.resolve()
    historical = json.loads((baseline / "continuation-proof.json").read_text())
    native_ref = next(r for r in historical["artifact_refs"] if "quantbt_native-" in r["path"])
    native_wheel = ROOT / native_ref["path"]
    if file_hash(native_wheel) != native_ref["sha256"] or native_wheel.stat().st_size != native_ref["bytes"]:
        raise ValueError("native artifact changed since the C04 local seal")
    names = subprocess.check_output(["git", "ls-files", "rust"], cwd=ROOT, text=True).splitlines()
    rust = {name: file_hash(ROOT / name) for name in names}
    if any(file_hash(baseline / "stage" / name) != expected for name, expected in rust.items()):
        raise ValueError("native source changed; reused wheel cannot qualify E01")
    source_guard = verify()
    build = build_core(output=output, build_python=build_python, native_wheel=native_wheel, python=python)
    interpreter = output / "consumer/bin/python"
    consumers = {}
    for label, pattern in (("wheel", "*.whl"), ("sdist", "*.tar.gz")):
        artifact = next((output / "dist").glob(pattern))
        run([build_tool("uv"), "pip", "install", "--offline", "--python", interpreter,
             "--no-deps", "--reinstall", artifact], cwd=output, log=output / f"e01-{label}-install.log")
        consumers[label] = installed([interpreter], root=ROOT, core=build["core"], native=build["native"],
                                    workspace=output / "workspace", logs=output / f"e01-{label}-consumers")
    receipt = dict(schema="qms-e01-installed-source-pair-v1", core=build["core"], native=build["native"],
        source_guard=source_guard, consumers=consumers, artifact_refs=build["artifact_refs"],
        artifact_allowlist=build["artifact_allowlist"], source_exact_wheel=True, source_exact_sdist=True,
        native_rebuilt=False, native_reuse_source_sha256=sha256(json.dumps(rust, sort_keys=True).encode()).hexdigest(),
        native_baseline_receipt_sha256=file_hash(baseline / "continuation-proof.json"),
        c02_build_receipt_sha256=file_hash(output / "proof.json"),
        source_sha=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        publication=False, economic_claim=False)
    (output / "e01-proof.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--build-python", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--native-baseline", type=Path, required=True)
    receipt = qualify(**vars(parser.parse_args()))
    print(json.dumps(dict(pair=[receipt["core"], receipt["native"]], artifacts=len(receipt["artifact_refs"]),
                          consumers=list(receipt["consumers"]), native_rebuilt=False, publication=False)))
