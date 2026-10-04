"""Build-only exact private pair and clean installed consumers; never publish."""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from time import perf_counter
import zipfile

from tools.check_release_artifacts import inspect_artifact
from tools.generate_product_contracts import _fingerprint, render_python, render_rust
from tools.verify_wheels import core_wheel_source_differences

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".maturin/qms08"
CORE, NATIVE = "1.1.1+qms08", "0.4.3.dev4"
FEATURES = "qms-numeric-candidate,qms-prepared-witness-candidate"


def file_hash(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def run(command, *, cwd, log):
    env = dict(
        os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1"
    )
    env.pop("PYTHONPATH", None)
    env["UV_CACHE_DIR"] = "/tmp/quantbt-uv-cache"
    process = subprocess.run(
        [str(x) for x in command], cwd=cwd, env=env, capture_output=True, text=True
    )
    log.write_text(
        "$ " + " ".join(map(str, command)) + "\n" + process.stdout + process.stderr
    )
    if process.returncode:
        raise RuntimeError(
            f"package command failed ({process.returncode}); see {log}\n{process.stderr[-2500:]}"
        )
    return process.stdout


def stage_source(directory):
    """Only tracked allowlisted files. Never copy a venv, dataset or private alpha."""
    names = subprocess.check_output(
        ["git", "ls-files", "src/quantbt", "rust"], cwd=ROOT, text=True
    ).splitlines()
    names += ["pyproject.toml", "README.md", "CHANGELOG.md", "LICENSE", "MANIFEST.in"]
    for name in names:
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    product = json.loads(
        (ROOT / "contracts/native_event_product_registry.json").read_text()
    )
    product = deepcopy(product)
    product["versions"]["core_package"]["version"] = CORE
    product["versions"]["native_package"].update(version=NATIVE, published=False)
    for pair in product["compatibility"]:
        if pair["core_version"] == "1.1.1" and pair["native_version"] == "0.4.2":
            pair.update(core_version=CORE, native_version=NATIVE)
    fp = _fingerprint(product)
    life = product["lifecycle_registry"]["fingerprint"]
    rewritten = {
        "src/quantbt/core/generated_product_contracts.py": render_python(
            product, fp, life
        ),
        "rust/crates/quantbt-domain/src/generated_product_contracts.rs": render_rust(
            product, fp, life
        ),
    }
    for name, text in rewritten.items():
        (directory / name).write_text(text)
    edits = {
        "pyproject.toml": [
            ('version = "1.1.1"', f'version = "{CORE}"'),
            ("quantbt-native==0.4.2;", f"quantbt-native=={NATIVE};"),
        ],
        "src/quantbt/__init__.py": [
            ('__version__ = "1.1.1"', f'__version__ = "{CORE}"')
        ],
        "rust/native_event/pyproject.toml": [
            ('version = "0.4.2"', f'version = "{NATIVE}"')
        ],
        "rust/native_event/Cargo.toml": [
            ('version = "0.4.2"', 'version = "0.4.3-dev.4"')
        ],
    }
    for name, replacements in edits.items():
        path = directory / name
        text = path.read_text()
        for old, new in replacements:
            if text.count(old) != 1:
                raise ValueError(
                    f"build-only identity rewrite is not exact: {name}: {old}"
                )
            text = text.replace(old, new, 1)
        path.write_text(text)
    differences = {
        name: {"source": file_hash(ROOT / name), "staged": file_hash(directory / name)}
        for name in names
        if file_hash(ROOT / name) != file_hash(directory / name)
    }
    if set(differences) != set(rewritten) | set(edits):
        raise ValueError("unexpected stage-only source changes")
    (directory / "candidate_registry.json").write_text(
        json.dumps(product, sort_keys=True, indent=2) + "\n"
    )
    return differences


def qualify(python, *, output=OUTPUT):
    """One fresh local interpreter lane; separate off/core-only/installed-pair environments."""
    output = Path(output).absolute()
    lane = output / (
        "cp"
        + subprocess.check_output(
            [
                str(python),
                "-c",
                "import sys;print(''.join(map(str,sys.version_info[:2])))",
            ],
            text=True,
        ).strip()
    )
    if (lane / "proof.json").exists():
        raise ValueError(
            f"sealed lane already exists: {lane}; choose a new output, do not overwrite"
        )
    lane.mkdir(parents=True, exist_ok=True)
    stage = lane / "stage"
    differences = stage_source(stage)
    dist = lane / "dist"
    dist.mkdir()
    uv = ROOT / ".venv/bin/uv"
    maturin = ROOT / ".venv/bin/maturin"
    started = perf_counter()
    build_env = lane / "build-env"
    run(
        [uv, "venv", "--python", python, build_env],
        cwd=lane,
        log=lane / "build-venv.log",
    )
    build_python = build_env / "bin/python"
    run(
        [
            uv,
            "pip",
            "install",
            "--python",
            build_python,
            "build>=1.3,<2",
            "setuptools>=82,<83",
            "wheel>=0.46,<0.47",
        ],
        cwd=lane,
        log=lane / "build-dependencies.log",
    )
    run(
        [
            build_python,
            "-m",
            "build",
            "--no-isolation",
            "--wheel",
            "--sdist",
            "--outdir",
            dist,
        ],
        cwd=stage,
        log=lane / "core-build.log",
    )
    env_target = str(ROOT / "rust/target/qms08-candidate")
    old_target = os.environ.get("CARGO_TARGET_DIR")
    os.environ["CARGO_TARGET_DIR"] = env_target
    try:
        run(
            [
                maturin,
                "build",
                "--offline",
                "--release",
                "--features",
                FEATURES,
                "--manifest-path",
                stage / "rust/native_event/Cargo.toml",
                "--interpreter",
                python,
                "--out",
                dist,
            ],
            cwd=stage,
            log=lane / "native-build.log",
        )
    finally:
        if old_target is None:
            os.environ.pop("CARGO_TARGET_DIR", None)
        else:
            os.environ["CARGO_TARGET_DIR"] = old_target
    build_seconds = perf_counter() - started
    wheel = next(dist.glob("quantbt_engine-*.whl"))
    sdist = next(dist.glob("quantbt_engine-*.tar.gz"))
    native = next(dist.glob("quantbt_native-*.whl"))
    differences_wheel = core_wheel_source_differences(wheel, stage / "src/quantbt")
    if any(differences_wheel.values()):
        raise AssertionError(f"source/wheel drift: {differences_wheel}")
    for artifact in (wheel, sdist, native):
        findings = inspect_artifact(artifact)
        if findings:
            raise ValueError(findings)
    with tarfile.open(sdist) as archive:
        modules = {
            m.name.split("/src/quantbt/", 1)[1]: sha256(
                archive.extractfile(m).read()
            ).hexdigest()
            for m in archive.getmembers()
            if m.isfile() and "/src/quantbt/" in m.name and m.name.endswith(".py")
        }
    expected = {
        p.relative_to(stage / "src/quantbt").as_posix(): file_hash(p)
        for p in (stage / "src/quantbt").rglob("*.py")
    }
    if modules != expected:
        raise ValueError("sdist missing/drifted canonical source")
    with zipfile.ZipFile(wheel) as archive:
        meta = archive.read(
            next(n for n in archive.namelist() if n.endswith("/METADATA"))
        ).decode()
        if f"quantbt-native=={NATIVE}" not in meta.replace(" ", ""):
            raise ValueError("candidate dependency not wired")
    consumers = {}
    for name in ("core_off", "core_optimization", "pair", "sdist"):
        venv = lane / name
        run(
            [uv, "venv", "--python", python, venv],
            cwd=lane,
            log=lane / f"{name}-venv.log",
        )
        vp = venv / "bin/python"
        installs = [str(sdist) if name == "sdist" else str(wheel)]
        run(
            [
                uv,
                "pip",
                "install",
                "--python",
                vp,
                "numpy>=2.2.6,<2.3",
                "pandas>=2.3.3,<2.4",
                "numba>=0.65.1,<0.66",
            ],
            cwd=lane,
            log=lane / f"{name}-deps.log",
        )
        run(
            [uv, "pip", "install", "--python", vp, "--no-deps", *installs],
            cwd=lane,
            log=lane / f"{name}-core.log",
        )
        if name != "core_off":
            run(
                [
                    uv,
                    "pip",
                    "install",
                    "--python",
                    vp,
                    "optuna>=4.8.0,<4.9",
                    "cmaes==0.12.0",
                    "arch>=8.0.0,<8.1",
                    "scikit-learn>=1.8.0,<1.9",
                ],
                cwd=lane,
                log=lane / f"{name}-optimization.log",
            )
        if name in {"pair", "sdist"}:
            run(
                [uv, "pip", "install", "--python", vp, native],
                cwd=lane,
                log=lane / f"{name}-native.log",
            )
            run(
                [uv, "pip", "check", "--python", vp],
                cwd=lane,
                log=lane / f"{name}-check.log",
            )
        args = [vp, "-I", ROOT / "tools/qms08_consumer.py", "--core-version", CORE]
        if name == "core_off":
            args += ["--without-optimization"]
        if name in {"pair", "sdist"}:
            args += ["--native-version", NATIVE]
        consumers[name] = json.loads(
            run(args, cwd=lane, log=lane / f"{name}-consumer.log").splitlines()[-1]
        )
    proof = {
        "schema": "qms08-installed-candidate-v1",
        "build_only": True,
        "core": CORE,
        "native": NATIVE,
        "features": FEATURES,
        "stage_differences": differences,
        "source_exact_wheel_sdist": True,
        "artifact_allowlist": True,
        "build_seconds": build_seconds,
        "artifact_refs": [
            {
                "path": str(p.relative_to(ROOT)),
                "sha256": file_hash(p),
                "bytes": p.stat().st_size,
            }
            for p in (wheel, sdist, native)
        ],
        "consumers": consumers,
        "logs": {str(p.relative_to(ROOT)): file_hash(p) for p in lane.glob("*.log")},
        "source_versions_unchanged": True,
        "release_authorized": False,
    }
    (lane / "proof.json").write_text(json.dumps(proof, sort_keys=True, indent=2) + "\n")
    return proof


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    result = qualify(args.python, output=args.output)
    print(
        json.dumps(
            {
                "core": result["core"],
                "native": result["native"],
                "consumers": list(result["consumers"]),
            }
        )
    )
