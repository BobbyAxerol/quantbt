"""Focused local helper artifact proof, reusing unchanged sealed native bytes."""

import json
import os
import sys

from tools.qms08_package import ROOT, build_tool, declared_pair, file_hash, run, stage_source
from tools.qms_pre06_contract import artifact_source, core_inventory, native_reuse, write_once
from tools.qms_pre06_package import NATIVE, PINNED

LANE = ROOT / ".maturin/qms08/sampler-helper-v1/package-v2/cp312"
SCRATCH = ("build-env", "pair", "sdist", "stage/build")


def build():
    if LANE.exists():
        raise ValueError("refuse to overwrite helper artifact evidence")
    if sys.version_info[:2] != (3, 12):
        raise ValueError("local proof is CPython 3.12 only, not a remote matrix")
    disk = os.statvfs(ROOT)
    if disk.f_bavail * disk.f_frsize < 7 * 1024**3:
        raise ValueError("2 GiB copy-mode increment + 5 GiB safety headroom unavailable")
    core, native = declared_pair()
    reuse = native_reuse(NATIVE)
    source = core_inventory(ROOT / "src/quantbt")
    LANE.mkdir(parents=True)
    write_once(LANE / "registration.json", dict(
        schema="qms-sampler-helper-artifact-registration-v1", core=core, native=native,
        core_inventory=source, native_reuse=reuse, publication=False,
        incremental_budget_bytes=2 * 1024**3, free_bytes=disk.f_bavail * disk.f_frsize,
        free_inodes=disk.f_favail, cleanup_allowlist=SCRATCH,
        scope="helper import/config and public pct-equity parity, not full E08 qualification",
    ))
    uv = build_tool("uv")
    env = LANE / "build-env"
    run([uv, "venv", "--python", sys.executable, env], cwd=LANE, log=LANE / "build-env.log")
    python = env / "bin/python"
    run([uv, "pip", "install", "--offline", "--python", python,
         "build", "setuptools>=82,<83", "wheel>=0.46,<0.47"],
        cwd=LANE, log=LANE / "build-dependencies.log")
    stage, dist = LANE / "stage", LANE / "dist"
    stage_source(stage, release_pair=True)
    run([python, "-m", "build", "--no-isolation", "--wheel", "--sdist", "--outdir", dist],
        cwd=stage, log=LANE / "build.log")
    artifacts = {"pair": next(dist.glob("*.whl")), "sdist": next(dist.glob("*.tar.gz"))}
    consumers = {}
    for kind, artifact in artifacts.items():
        artifact_source(artifact, source)
        env = LANE / kind
        run([uv, "venv", "--python", sys.executable, env], cwd=LANE, log=LANE / (kind + "-venv.log"))
        python = env / "bin/python"
        run([uv, "pip", "install", "--offline", "--python", python,
             str(artifact) + "[optimization]", NATIVE, *PINNED],
            cwd=LANE, log=LANE / (kind + "-install.log"))
        run([uv, "pip", "check", "--python", python], cwd=LANE, log=LANE / (kind + "-dependencies.log"))
        stdout = run([python, "-I", ROOT / "tools/qms_sampler_helper_consumer.py",
                      LANE / "registration.json"], cwd="/tmp", log=LANE / (kind + "-consumer.log"))
        consumers[kind] = json.loads(stdout)
        if consumers[kind]["status"] != "PASS":
            raise ValueError("installed helper consumer failed")
    if core_inventory(ROOT / "src/quantbt") != source or native_reuse(NATIVE) != reuse:
        raise ValueError("source drift during helper packaging")
    proof = dict(schema="qms-sampler-helper-artifact-proof-v1", status="PASS",
                 core=core, native=native, modules=len(source), native_rebuilt=False,
                 source_exact_wheel_sdist=True, consumers=consumers, publication=False,
                 artifact_refs=[dict(path=str(p.relative_to(ROOT)), sha256=file_hash(p), bytes=p.stat().st_size)
                                for p in (*artifacts.values(), NATIVE)])
    write_once(LANE / "proof.json", proof)
    print(json.dumps(dict(status="PASS", modules=len(source), publication=False)))


if __name__ == "__main__":
    build()
