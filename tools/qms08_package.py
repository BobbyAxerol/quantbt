"""Build-only private or approved release pair; clean consumers, never publish."""

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
import tomllib
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


def declared_pair():
    core = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    native = tomllib.loads((ROOT / "rust/native_event/pyproject.toml").read_text())["project"]["version"]
    return core, native


def stage_source(directory, *, release_pair=False):
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
    source_core, source_native = declared_pair()
    if release_pair:
        return {}
    product["versions"]["core_package"]["version"] = CORE
    product["versions"]["native_package"].update(version=NATIVE, published=False)
    for pair in product["compatibility"]:
        if pair["core_version"] == source_core and pair["native_version"] == source_native:
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
            (f'version = "{source_core}"', f'version = "{CORE}"'),
            (f"quantbt-native=={source_native};", f"quantbt-native=={NATIVE};"),
        ],
        "src/quantbt/__init__.py": [
            (f'__version__ = "{source_core}"', f'__version__ = "{CORE}"')
        ],
        "rust/native_event/pyproject.toml": [
            (f'version = "{source_native}"', f'version = "{NATIVE}"')
        ],
        "rust/native_event/Cargo.toml": [
            (f'version = "{source_native}"', 'version = "0.4.3-dev.4"')
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


def qualify(python, *, output=OUTPUT, reuse_native_lane=None, release_pair=False):
    """One fresh local interpreter lane; separate off/core-only/installed-pair environments."""
    python = Path(python).absolute()
    core_version, native_version = declared_pair() if release_pair else (CORE, NATIVE)
    if release_pair and reuse_native_lane is not None:
        raise ValueError("release proof requires a fresh default-feature native build")
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
    differences = stage_source(stage, release_pair=release_pair)
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
    if reuse_native_lane is not None:
        from tools.qms08_gate import verify_pair

        old_lane = Path(reuse_native_lane).resolve()
        if old_lane.name != lane.name:
            raise ValueError("native reuse must match the actual interpreter lane")
        old_proof = json.loads((old_lane / "proof.json").read_text())
        verify_pair(old_proof, source_revision="6c0f877")
        for path in (stage / "rust").rglob("*"):
            if path.is_file() and path.name != "Cargo.lock":
                previous = old_lane / "stage" / path.relative_to(stage)
                if file_hash(path) != file_hash(previous):
                    raise ValueError("native reuse requires exact staged Rust source")
        shutil.copy2(old_lane / "stage/rust/Cargo.lock", stage / "rust/Cargo.lock")
        native_ref = next(r for r in old_proof["artifact_refs"]
                          if Path(r["path"]).name.startswith("quantbt_native-"))
        native_source = ROOT / native_ref["path"]
        shutil.copy2(native_source, dist / native_source.name)
        (lane / "native-build.log").write_text(
            f"Exact sealed native wheel reused; Rust bytes unchanged: {native_ref['sha256']}\n"
        )
    else:
        env_target = str(ROOT / "rust/target/qms08-candidate")
        old_target = os.environ.get("CARGO_TARGET_DIR")
        os.environ["CARGO_TARGET_DIR"] = env_target
        try:
            run(
                [maturin, "build", "--offline", "--release",
                 *([] if release_pair else ["--no-default-features", "--features", FEATURES]),
                 "--manifest-path", stage / "rust/native_event/Cargo.toml",
                 "--interpreter", python, "--out", dist],
                cwd=stage, log=lane / "native-build.log",
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
        if f"quantbt-native=={native_version}" not in meta.replace(" ", ""):
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
        args = [vp, "-I", ROOT / "tools/qms08_consumer.py", "--core-version", core_version]
        if name == "core_off":
            args += ["--without-optimization"]
        if name in {"pair", "sdist"}:
            args += ["--native-version", native_version]
        consumers[name] = json.loads(
            run(args, cwd=lane, log=lane / f"{name}-consumer.log").splitlines()[-1]
        )
    proof = {
        "schema": "qms-release-installed-pair-v1" if release_pair else "qms08-installed-candidate-v1",
        "build_only": True,
        "core": core_version,
        "native": native_version,
        "features": "cargo-default" if release_pair else FEATURES,
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
    parser.add_argument("--reuse-native-lane", type=Path)
    parser.add_argument("--release-pair", action="store_true", help="Build canonical release identities with Cargo default features; never publish")
    args = parser.parse_args()
    result = qualify(args.python, output=args.output, reuse_native_lane=args.reuse_native_lane, release_pair=args.release_pair)
    print(
        json.dumps(
            {
                "core": result["core"],
                "native": result["native"],
                "consumers": list(result["consumers"]),
            }
        )
    )
