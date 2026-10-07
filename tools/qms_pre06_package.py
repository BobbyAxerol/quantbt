"""Local source-exact core builds and independent offline installed consumers."""

import argparse
import json
import shutil
import sys
import time

from tools.qms08_package import ROOT, build_tool, declared_pair, file_hash, run, stage_source
from tools.qms_installed_consumers import qualify as consumers
from tools.qms_pre06_contract import (
    LANE, PRE05, artifact_source, core_inventory, native_reuse, prerequisites, write_once,
)

NATIVE = ROOT / ".maturin/qms08/g01-package-v1-native/quantbt_native-0.4.3-cp312-cp312-manylinux_2_34_x86_64.whl"
PINNED = ("numpy==2.2.6", "pandas==2.3.3", "numba==0.65.1", "optuna==4.8.0",
          "scipy==1.18.1", "cmaes==0.12.0", "arch==8.0.0", "scikit-learn==1.8.0",
          "threadpoolctl==3.7.0", "pytest==9.1.1")
EXTRA = {
    "g01": ("qms_g01_consumer.py", ()),
    "scalar": ("qms_e03_consumer.py", ("--example", "examples/wfo_meta_scalar.py")),
    "portfolio": ("qms_e04_consumer.py", ("--example", "examples/wfo_meta_portfolio.py")),
    "package": ("qms_e05_consumer.py", ("--example", "examples/wfo_meta_package.py")),
    "execution": ("qms_execution_consumer.py", ()),
    "execution-native": ("qms_execution_consumer.py", ("--native-probe",)),
}


def qualify():
    start = time.perf_counter()
    if LANE.exists():
        raise ValueError("refuse to overwrite an existing qualification lane")
    before = shutil.disk_usage(ROOT).free
    if before < 7 * 1024**3:
        raise ValueError("registered 2 GiB + 5 GiB budget unavailable")
    guard, reuse = prerequisites(), native_reuse(NATIVE)
    prior = json.loads(PRE05.read_text())
    expected = {}
    for name in prior["samples_sha256"]:
        sample = json.loads((ROOT / f".maturin/qms08/pre-e06-05/samples/matched-v3-{name}.json").read_text())
        expected[sample["cell"]] = sample["semantic_sha256"]
    if len(expected) != 76:
        raise ValueError("sealed workload cardinality drift")
    registration = dict(schema="qms-pre06-registration-v1", source=guard, native=reuse,
                        core_inventory=core_inventory(ROOT / "src/quantbt"),
                        expected_cells=expected, pinned_dependencies=PINNED,
                        entry_free_bytes=before, incremental_budget_bytes=2 * 1024**3,
                        safety_bytes=5 * 1024**3, numeric_threads=1, publication=False)
    write_once(LANE / "registration.json", registration)
    output = LANE / "package-v1"
    output.mkdir()
    uv = build_tool("uv")
    build = output / "build-env"
    run([uv, "venv", "--python", sys.executable, build], cwd=output, log=output / "build-env.log")
    build_python = build / "bin/python"
    run([uv, "pip", "install", "--offline", "--python", build_python,
         "build", "setuptools>=82,<83", "wheel>=0.46,<0.47"],
        cwd=output, log=output / "build-dependencies.log")
    stage = output / "stage"
    stage_source(stage, release_pair=True)
    dist = output / "dist"
    run([build_python, "-m", "build", "--no-isolation", "--wheel", "--sdist", "--outdir", dist],
        cwd=stage, log=output / "build.log")
    core, sdist = next(dist.glob("*.whl")), next(dist.glob("*.tar.gz"))
    artifacts = {kind: artifact_source(path, registration["core_inventory"])
                 for kind, path in (("wheel", core), ("sdist", sdist))}
    core_version, native_version = declared_pair()
    if (core_version, native_version) != ("1.1.2", "0.4.3"):
        raise ValueError("approved pair drift")
    results = {}
    for kind, artifact in (("wheel", core), ("sdist", sdist)):
        env = output / (kind + "-consumer")
        run([uv, "venv", "--python", sys.executable, env], cwd=output, log=output / (kind + "-venv.log"))
        python = env / "bin/python"
        run([uv, "pip", "install", "--offline", "--python", python,
             f"{artifact}[optimization]", NATIVE, *PINNED], cwd=output, log=output / (kind + "-install.log"))
        run([uv, "pip", "check", "--python", python], cwd=output, log=output / (kind + "-dependencies.log"))
        mandatory = consumers([python], root=ROOT, core=core_version, native=native_version,
                              workspace=output, logs=output / (kind + "-mandatory"))
        extra = {}
        for label, (script, arguments) in EXTRA.items():
            argv = [str(ROOT / arg) if arg.startswith("examples/") else arg for arg in arguments]
            result = run([python, "-I", ROOT / "tools" / script, *argv],
                         cwd=output, log=output / (kind + "-" + label + ".log"))
            extra[label] = json.loads(result.splitlines()[-1])
        full = output / (kind + "-full-work.json")
        run([python, "-I", ROOT / "tools/qms_pre06_consumer.py", "--root", ROOT,
             "--registration", LANE / "registration.json", "--output", full],
            cwd=output, log=output / (kind + "-full-work.log"))
        results[kind] = dict(mandatory=mandatory, extra=extra, full_work=str(full.relative_to(ROOT)),
                             full_work_sha256=file_hash(full))
        write_once(output / (kind + "-proof.json"), results[kind])
        print(f"{kind}: mandatory, supplementary and 76 full-work cells PASS", flush=True)
        if shutil.disk_usage(ROOT).free < 5 * 1024**3:
            raise ValueError("safety headroom violated")
    checked = prerequisites()
    if guard != checked:
        raise ValueError("source changed during installed proof")
    receipt = dict(schema="qms-pre06-package-v1", status="PASS_LOCAL_INSTALLED_ARTIFACTS",
                   registration_sha256=file_hash(LANE / "registration.json"), artifacts=artifacts,
                   source=guard, native=reuse, results=results, elapsed_seconds=time.perf_counter()-start,
                   artifact_refs={str(p.relative_to(ROOT)): file_hash(p) for p in (core, sdist, NATIVE)},
                   logs={str(p.relative_to(ROOT)): file_hash(p) for p in output.rglob("*.log")},
                   publication=False, remote=False)
    write_once(output / "proof.json", receipt)
    print(json.dumps(dict(status=receipt["status"], core=core_version, native=native_version, publication=False)))


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    qualify()
