"""Source-exact C04 wheel/sdist proof, reusing the qualified native wheel."""

import argparse
import json
from pathlib import Path
import sys

from tools.qms08_package import ROOT, build_tool, file_hash, run
from tools.qms_c02_package import qualify as qualify_transport
from tools.qms_c04_source_guard import verify


def qualify(*, output, build_python, native_wheel, python):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("use a fresh C04 package proof directory")
    source = verify()
    transport = qualify_transport(output=output, build_python=build_python,
                                  native_wheel=native_wheel, python=python)
    installed = output / "consumer/bin/python"
    consumers = {}
    for label, artifact in (("wheel", next((output / "dist").glob("*.whl"))),
                            ("sdist", next((output / "dist").glob("*.tar.gz")))):
        run([build_tool("uv"), "pip", "install", "--offline", "--python", installed,
             "--no-deps", "--reinstall", artifact], cwd=output, log=output / f"c04-{label}-install.log")
        text = run([installed, "-I", ROOT / "tools/qms_c04_consumer.py", "--example",
                    ROOT / "examples/optimization_exact_continuation.py",
                    "--core-version", transport["core"], "--native-version", transport["native"]],
                   cwd=output / "workspace", log=output / f"c04-{label}.log")
        consumers[label] = json.loads(text.splitlines()[-1])
    result = dict(schema="qms-c04-installed-source-pair-v1", publication=False,
                  source_guard=source, core=transport["core"], native=transport["native"],
                  native_rebuilt=False, source_exact_wheel=True, source_exact_sdist=True,
                  artifact_allowlist=transport["artifact_allowlist"],
                  artifact_refs=transport["artifact_refs"], consumers=consumers,
                  transport_proof_sha256=file_hash(output / "proof.json"),
                  logs={p.name: file_hash(p) for p in output.glob("*.log")})
    (output / "continuation-proof.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
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
