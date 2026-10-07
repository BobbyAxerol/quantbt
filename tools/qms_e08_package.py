"""Fresh source-exact local core pair with unchanged, sealed native bytes."""

import argparse
import json
import os
from pathlib import Path
import sys

from tools.qms08_package import ROOT, build_tool, declared_pair, file_hash, run, stage_source
from tools.qms_e08_consumer import inventory
from tools.qms_installed_execution import qualify
from tools.qms_pre06_contract import artifact_source, native_reuse
from tools.qms_pre06_package import NATIVE, PINNED

LANE = ROOT/".maturin/qms08/e08-qualification-v1/package-v1/cp312"


def build():
    if LANE.exists():
        raise ValueError("refuse artifact lane overwrite")
    disk = os.statvfs(ROOT)
    if disk.f_bavail*disk.f_frsize < 8*1024**3:
        raise ValueError("3 GiB increment + 5 GiB safety budget unavailable")
    if sys.version_info[:2] != (3, 12):
        raise ValueError("local reuse lane is CPython 3.12 only; CI uses qms08_package")
    core, native = declared_pair()
    reuse = native_reuse(NATIVE)
    source = inventory(ROOT/"src/quantbt")
    LANE.mkdir(parents=True)
    registration = dict(schema="qms-e08-artifact-registration-v1", core=core, native=native,
        core_inventory=source, native_reuse=reuse, incremental_budget_bytes=3*1024**3,
        free_bytes=disk.f_bavail*disk.f_frsize, free_inodes=disk.f_favail, publication=False)
    (LANE/"registration.json").write_text(json.dumps(registration, indent=2, sort_keys=True)+"\n")
    uv = build_tool("uv")
    build_env = LANE/"build-env"
    run([uv, "venv", "--python", sys.executable, build_env], cwd=LANE, log=LANE/"build-env.log")
    python = build_env/"bin/python"
    run([uv, "pip", "install", "--offline", "--python", python, "build", "setuptools>=82,<83", "wheel>=0.46,<0.47"],
        cwd=LANE, log=LANE/"build-dependencies.log")
    stage, dist = LANE/"stage", LANE/"dist"
    stage_source(stage, release_pair=True)
    run([python, "-m", "build", "--no-isolation", "--wheel", "--sdist", "--outdir", dist],
        cwd=stage, log=LANE/"build.log")
    artifacts = {"pair": next(dist.glob("*.whl")), "sdist": next(dist.glob("*.tar.gz"))}
    for path in artifacts.values():
        artifact_source(path, source)
    for kind, artifact in artifacts.items():
        env = LANE/kind
        run([uv, "venv", "--python", sys.executable, env], cwd=LANE, log=LANE/(kind+"-venv.log"))
        python = env/"bin/python"
        run([uv, "pip", "install", "--offline", "--python", python, str(artifact)+"[optimization]", NATIVE, *PINNED],
            cwd=LANE, log=LANE/(kind+"-install.log"))
        run([uv, "pip", "check", "--python", python], cwd=LANE, log=LANE/(kind+"-dependencies.log"))
    if inventory(ROOT/"src/quantbt") != source or native_reuse(NATIVE) != reuse:
        raise ValueError("source drift during build")
    proof = dict(schema="qms-e08-local-artifacts-v1", core=core, native=native,
        native_reuse=reuse, source_exact_wheel_sdist=True, publication=False,
        artifact_refs=[dict(path=str(p.relative_to(ROOT)), sha256=file_hash(p), bytes=p.stat().st_size)
            for p in (*artifacts.values(), NATIVE)])
    (LANE/"proof.json").write_text(json.dumps(proof, indent=2, sort_keys=True)+"\n")
    return proof


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installed", action="store_true")
    args = parser.parse_args()
    result = qualify(LANE, offline=True) if args.installed else build()
    print(json.dumps(dict(schema=result["schema"], publication=False)))
