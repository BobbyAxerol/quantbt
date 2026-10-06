"""Fresh E04 core artifacts with unchanged exact native and installed consumers."""

import argparse
import json
from pathlib import Path

from tools.qms_e03_package import qualify as base_qualify
from tools.qms08_package import ROOT, build_tool, file_hash, run
from tools.qms_e04_source_guard import verify


def qualify(*, output, build_python, python, native_baseline):
    base = base_qualify(output=output, build_python=build_python, python=python,
                        native_baseline=native_baseline)
    output = output.resolve()
    consumer = output / "consumer/bin/python"
    rows = {}
    for label, pattern in (("wheel", "*.whl"), ("sdist", "*.tar.gz")):
        artifact = next((output / "dist").glob(pattern))
        run([build_tool("uv"), "pip", "install", "--offline", "--python", consumer,
             "--no-deps", "--reinstall", artifact], cwd=output, log=output / f"e04-{label}-install.log")
        rows[label] = json.loads(run([consumer, "-I", ROOT / "tools/qms_e04_consumer.py",
            "--example", ROOT / "examples/wfo_meta_portfolio.py"], cwd=output / "workspace",
            log=output / f"e04-{label}-consumer.log").splitlines()[-1])
    receipt = dict(schema="qms-e04-installed-pair-v1", core=base["core"], native=base["native"],
        source_guard=verify(), source_exact_wheel=True, source_exact_sdist=True,
        native_rebuilt=False, base_proof_sha256=file_hash(output / "e03-proof.json"),
        artifact_refs=base["artifact_refs"], consumers=rows, publication=False, empirical_promotion=False)
    (output / "e04-proof.json").write_text(json.dumps(receipt, indent=2, sort_keys=True)+"\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "build-python", "python", "native-baseline"):
        parser.add_argument("--"+name, type=Path, required=True)
    result = qualify(**vars(parser.parse_args()))
    print(json.dumps(dict(pair=[result["core"], result["native"]], consumers=list(result["consumers"]), publication=False)))
