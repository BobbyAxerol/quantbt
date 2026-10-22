"""Build fresh core bytes; reuse unchanged exact native artifact, never publish."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
import tarfile

from tools.qms08_package import ROOT, build_tool, declared_pair, file_hash, run, stage_source
from tools.check_release_artifacts import inspect_artifact
from tools.verify_wheels import core_wheel_source_differences
from tools.qms_execution_source_guard import verify


def qualify(output, build_python, native_wheel):
    output, native_wheel = Path(output).resolve(), Path(native_wheel).resolve()
    build_python = Path(build_python).absolute()
    if output.exists():
        raise ValueError("use a fresh evidence lane")
    guard = verify()
    output.mkdir(parents=True)
    stage = output / "stage"
    stage_source(stage, release_pair=True)
    dist = output / "dist"
    dist.mkdir()
    run([build_python, "-m", "build", "--no-isolation", "--wheel", "--sdist", "--outdir", dist],
        cwd=stage, log=output / "build.log")
    core, sdist = next(dist.glob("*.whl")), next(dist.glob("*.tar.gz"))
    for artifact in (core, sdist, native_wheel):
        if inspect_artifact(artifact):
            raise ValueError("artifact allowlist failed")
    if any(core_wheel_source_differences(core, ROOT / "src/quantbt").values()):
        raise ValueError("wheel differs from exact canonical source")
    with tarfile.open(sdist) as archive:
        modules = {m.name.split("/src/quantbt/", 1)[1]: sha256(archive.extractfile(m).read()).hexdigest()
            for m in archive.getmembers() if m.isfile() and "/src/quantbt/" in m.name and m.name.endswith(".py")}
    expected = {p.relative_to(ROOT / "src/quantbt").as_posix(): file_hash(p)
                for p in (ROOT / "src/quantbt").rglob("*.py")}
    if modules != expected:
        raise ValueError("sdist differs from canonical source")
    uv = build_tool("uv")
    consumer = output / "consumer"
    run([uv, "venv", "--python", sys.executable, consumer], cwd=output, log=output / "venv.log")
    python = consumer / "bin/python"
    run([uv, "pip", "install", "--offline", "--python", python, f"{core}[optimization]", native_wheel],
        cwd=output, log=output / "install.log")
    run([uv, "pip", "check", "--python", python], cwd=output, log=output / "dependencies.log")
    records = {}
    for kind in ("wheel", "sdist"):
        if kind == "sdist":
            run([uv, "pip", "install", "--offline", "--python", python, "--no-deps", "--reinstall", sdist],
                cwd=output, log=output / "sdist-install.log")
        result = run([python, "-I", ROOT / "tools/qms_execution_consumer.py"],
            cwd=output, log=output / f"{kind}-consumer.log")
        records[kind] = json.loads(result.splitlines()[-1])
        if (records[kind]["core"], records[kind]["native"]) != declared_pair():
            raise ValueError("installed pair mismatch")
    receipt = dict(schema="qms-execution-installed-artifacts-v1", publication=False,
        source_guard=guard, source_exact_wheel=True, source_exact_sdist=True,
        native_rebuilt=False, records=records,
        artifact_refs=[dict(path=str(p.relative_to(ROOT)), sha256=file_hash(p), bytes=p.stat().st_size)
                       for p in (core, sdist, native_wheel)],
        logs={p.name: file_hash(p) for p in output.glob("*.log")})
    (output / "proof.json").write_text(json.dumps(receipt, indent=2, sort_keys=True)+"\n")
    print(json.dumps(dict(publication=False, core=declared_pair()[0], native=declared_pair()[1],
        consumers=list(records), source_exact_wheel=True, source_exact_sdist=True)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--build-python", type=Path, required=True)
    parser.add_argument("--native-wheel", type=Path, required=True)
    qualify(**vars(parser.parse_args()))
