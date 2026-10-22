"""Fresh exact core wheel/sdist; unchanged Rust bytes and offline consumers."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
LANE = ROOT / ".maturin/qms08/e07-qualification-v1"


def build():
    from tools.qms08_package import build_tool, run, stage_source
    from tools.qms_e07_contract import NATIVE, check_registration, file_hash, write_once
    from tools.qms_pre06_contract import artifact_source
    registered = check_registration()
    uv = build_tool("uv")
    build_env = LANE / "build-env"
    if build_env.exists():
        raise ValueError("refuse build environment reuse")
    run([uv, "venv", "--python", sys.executable, build_env], cwd=LANE, log=LANE / "build-env.log")
    python = build_env / "bin/python"
    run([uv, "pip", "install", "--offline", "--python", python,
         "build", "setuptools>=82,<83", "wheel>=0.46,<0.47"], cwd=LANE, log=LANE / "build-dependencies.log")
    stage, dist = LANE / "stage", LANE / "dist"
    stage_source(stage, release_pair=True)
    run([python, "-m", "build", "--no-isolation", "--wheel", "--sdist", "--outdir", dist],
        cwd=stage, log=LANE / "build.log")
    artifacts = {"wheel": next(dist.glob("*.whl")), "sdist": next(dist.glob("*.tar.gz")), "native": NATIVE}
    proof = {k: artifact_source(p, registered["core_inventory"]) for k, p in artifacts.items() if k != "native"}
    write_once(LANE / "artifacts.json", dict(paths={k: str(p) for k, p in artifacts.items()},
        sha256={k: file_hash(p) for k, p in artifacts.items()}, source=proof, native_rebuilt=False,
        publication=False))
    check_registration()
    print(json.dumps(dict(status="PASS_EXACT_CORE_ARTIFACTS", native_rebuilt=False)))


def install():
    from tools.qms08_package import build_tool, run
    from tools.qms_e07_contract import NATIVE, check_registration, file_hash
    from tools.qms_pre06_contract import artifact_source
    from tools.qms_pre06_package import PINNED
    registered = check_registration()
    artifacts = json.loads((LANE / "artifacts.json").read_text())
    uv = build_tool("uv")
    for kind in ("wheel", "sdist"):
        artifact = Path(artifacts["paths"][kind])
        if file_hash(artifact) != artifacts["sha256"][kind]:
            raise ValueError("core artifact changed")
        artifact_source(artifact, registered["core_inventory"])
        target = LANE / (kind+"-consumer")
        if target.exists() or target.is_symlink():
            raise ValueError("refuse installed consumer overwrite")
        run([uv, "venv", "--python", sys.executable, target], cwd=LANE, log=LANE / (kind+"-venv.log"))
        python = target / "bin/python"
        run([uv, "pip", "install", "--offline", "--python", python,
            str(artifact)+"[optimization]", NATIVE, *PINNED], cwd=LANE, log=LANE / (kind+"-install.log"))
        run([uv, "pip", "check", "--python", python], cwd=LANE, log=LANE / (kind+"-dependencies.log"))
        print(json.dumps(dict(consumer=kind, status="INSTALLED_EXACT")), flush=True)


def test_installed(bounds=False):
    from importlib.util import spec_from_file_location, module_from_spec
    spec = spec_from_file_location("e07_installed_check", ROOT / "tools/qms_pre06_consumer.py")
    checker = module_from_spec(spec)
    spec.loader.exec_module(checker)
    registered = json.loads((LANE / "registration.json").read_text())
    identity = checker.identity(registered["core_inventory"])
    # Load public tests, never checkout runtime, after exact installed identity.
    sys.path.append(str(ROOT))
    from tools.qms_e07_contract import write_once
    import pytest
    label = "wheel" if "wheel-consumer" in sys.executable else "sdist"
    names = ("test_e07_order_bounds.py",) if bounds else ("test_e07_output.py", "test_e07_lifecycle.py")
    suffix = "-bounds-v1" if bounds else "-tests-v1"
    code = pytest.main(["-q", "--tb=short", "--import-mode=importlib",
        *[str(ROOT / "tests/meta_selection" / name) for name in names],
        f"--junitxml={LANE / (label+suffix+'.xml')}"])
    checker.origins(Path(identity["core_origin"]))
    if code:
        raise ValueError("installed route/output tests failed")
    identity_suffix = "-bounds-v1" if bounds else "-tests"
    write_once(LANE / (label+identity_suffix+"-identity.json"), identity)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--tests", action="store_true")
    parser.add_argument("--bounds", action="store_true")
    args = parser.parse_args()
    if args.tests:
        test_installed(args.bounds)
    elif args.install:
        install()
    else:
        build()
