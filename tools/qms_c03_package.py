"""Fresh C03 core wheel/sdist matrix using the already qualified C02 native wheel."""

import argparse
import json
from pathlib import Path
import sys

from tools.qms08_package import ROOT, build_tool, file_hash, run
from tools.qms_c02_package import qualify as qualify_transport
from tools.qms_c03_source_guard import verify


def qualify(*, output, build_python, native_wheel, python):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("use a fresh C03 evidence directory")
    source_guard = verify()
    transport = qualify_transport(output=output, build_python=build_python,
        native_wheel=native_wheel, python=python)
    core = next((output / "dist").glob("*.whl"))
    sdist = next((output / "dist").glob("*.tar.gz"))
    installed = output / "consumer/bin/python"
    uv = build_tool("uv")
    consumers = {}
    for label, artifact in (("wheel", core), ("sdist", sdist)):
        run([uv, "pip", "install", "--offline", "--python", installed, "--no-deps", "--reinstall", artifact],
            cwd=output, log=output / f"c03-{label}-install.log")
        result = run([installed, "-I", ROOT / "tools/qms_c03_consumer.py", "--example",
            ROOT / "examples/wfo_reactive_samplers.py", "--core-version", transport["core"],
            "--native-version", transport["native"]], cwd=output / "workspace", log=output / f"c03-{label}.log")
        consumers[label] = json.loads(result.splitlines()[-1])
    result = dict(schema="qms-c03-installed-source-pair-v1", publication=False, source_guard=source_guard,
        core=transport["core"], native=transport["native"], native_rebuilt=False,
        source_exact_wheel=transport["source_exact_wheel"], source_exact_sdist=transport["source_exact_sdist"],
        artifact_allowlist=transport["artifact_allowlist"], artifact_refs=transport["artifact_refs"],
        c02_transport_receipt_sha256=file_hash(output / "proof.json"), consumers=consumers,
        logs={path.name: file_hash(path) for path in output.glob("*.log")})
    (output / "sampler-proof.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--build-python", type=Path, required=True)
    parser.add_argument("--native-wheel", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    proof = qualify(**vars(parser.parse_args()))
    print(json.dumps(dict(core=proof["core"], native=proof["native"], native_rebuilt=False,
                         consumers=list(proof["consumers"]), publication=False)))
