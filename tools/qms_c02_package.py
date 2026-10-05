"""Fresh local core wheel/sdist and installed C02 proof; never publishes."""

import argparse
import json
from pathlib import Path
import sys
import tarfile
import zipfile

from tools.qms08_package import ROOT, build_tool, declared_pair, file_hash, run, stage_source
from tools.check_release_artifacts import inspect_artifact
from tools.qms_c02_source_guard import verify
from tools.verify_wheels import core_wheel_source_differences


def qualify(*, output, build_python, native_wheel, python):
    output = Path(output).resolve()
    build_python = Path(build_python).absolute()
    python = Path(python).absolute()
    if output.exists():
        raise ValueError("use a fresh package evidence directory")
    source_guard = verify()
    output.mkdir(parents=True)
    stage = output / "stage"
    stage_source(stage, release_pair=True)
    dist = output / "dist"
    dist.mkdir()
    run([build_python, "-m", "build", "--no-isolation", "--wheel", "--sdist", "--outdir", dist],
        cwd=stage, log=output / "core-build.log")
    core = next(dist.glob("*.whl"))
    sdist = next(dist.glob("*.tar.gz"))
    native_wheel = Path(native_wheel).resolve()
    for path in (core, sdist, native_wheel):
        findings = inspect_artifact(path)
        if findings:
            raise ValueError(findings)
    differences = core_wheel_source_differences(core, ROOT / "src/quantbt")
    if any(differences.values()):
        raise ValueError("source and fresh core wheel differ")
    with tarfile.open(sdist) as archive:
        from hashlib import sha256

        modules = {member.name.split("/src/quantbt/", 1)[1]: sha256(archive.extractfile(member).read()).hexdigest()
                   for member in archive.getmembers()
                   if member.isfile() and "/src/quantbt/" in member.name and member.name.endswith(".py")}
    expected = {path.relative_to(ROOT / "src/quantbt").as_posix(): file_hash(path)
                for path in (ROOT / "src/quantbt").rglob("*.py")}
    if modules != expected:
        raise ValueError("sdist missing/drifted canonical source")
    core_version, native_version = declared_pair()
    with zipfile.ZipFile(native_wheel) as archive:
        metadata = archive.read(next(n for n in archive.namelist() if n.endswith("/METADATA"))).decode()
        if f"Version: {native_version}\n" not in metadata:
            raise ValueError("native wheel version mismatch")
    uv = build_tool("uv")
    environment = output / "consumer"
    run([uv, "venv", "--python", python, environment], cwd=output, log=output / "venv.log")
    installed_python = environment / "bin/python"
    # Dependency wheels are reused from the prior local qualification cache;
    # this is a new site-packages consumer, not an editable/source-tree import.
    run([uv, "pip", "install", "--offline", "--python", installed_python,
         f"{core}[optimization]", native_wheel], cwd=output, log=output / "install.log")
    run([uv, "pip", "check", "--python", installed_python], cwd=output, log=output / "check.log")
    workspace = output / "workspace"
    workspace.mkdir()
    records = {}
    for name, command in (
        ("installed_w3", [installed_python, "-I", ROOT / "tools/qms_local_consumer.py",
            "--core-version", core_version, "--native-version", native_version, "--witness-transport"]),
        ("runnable_process_example", [installed_python, "-I", ROOT / "examples/wfo_meta_w3_process.py"]),
    ):
        records[name] = json.loads(run(command, cwd=workspace,
                                      log=output / f"{name}.log").splitlines()[-1])
    run([uv, "pip", "install", "--offline", "--python", installed_python,
         "--no-deps", "--reinstall", sdist], cwd=output, log=output / "sdist-install.log")
    records["installed_sdist_w3"] = json.loads(run([
        installed_python, "-I", ROOT / "tools/qms_local_consumer.py", "--core-version", core_version,
        "--native-version", native_version, "--witness-transport"],
        cwd=workspace, log=output / "installed_sdist_w3.log").splitlines()[-1])
    proof = records["installed_w3"].get("c02_transport")
    if not proof or not proof["original_pool_account_witness_exact"] or not proof["native_tokens"]:
        raise ValueError("C02 installed consumer did not qualify the new transport")
    receipt = dict(schema="qms-c02-installed-source-pair-v1", publication=False,
        core=core_version, native=native_version, source_guard=source_guard,
        source_exact_wheel=True, source_exact_sdist=True, artifact_allowlist=True, consumers=records,
        artifact_refs=[dict(path=str(path.relative_to(ROOT)), sha256=file_hash(path), bytes=path.stat().st_size)
                       for path in (core, sdist, native_wheel)],
        logs={path.name: file_hash(path) for path in output.glob("*.log")})
    (output / "proof.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--build-python", type=Path, required=True)
    parser.add_argument("--native-wheel", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    result = qualify(**vars(parser.parse_args()))
    print(json.dumps(dict(core=result["core"], native=result["native"], consumers=list(result["consumers"]),
                         publication=False)))
