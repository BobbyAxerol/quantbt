"""Run an existing consumer inside an exact, isolated installed runtime."""

import argparse
from contextlib import redirect_stdout
from hashlib import sha256
from io import StringIO
import json
import importlib.util
from pathlib import Path
import runpy
import sys


def identity_helper(path):
    spec = importlib.util.spec_from_file_location("e08_identity", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def consume(args):
    raw_manifest = args.manifest.read_bytes()
    manifest = json.loads(raw_manifest)
    if (Path(args.consumer).name != args.consumer
            or args.consumer not in manifest["allowed_consumers"]):
        raise ValueError("unregistered installed consumer")
    kind = getattr(args, "kind", None)
    if (kind not in {"pair", "sdist"} or kind not in manifest.get("prefixes", {})
            or not manifest.get("interpreter") or not manifest.get("native_inventory")
            or manifest.get("schema") != "qms-e08-installed-manifest-v1"
            or manifest.get("package_proof_schema") not in {"qms-release-installed-pair-v1",
                "quantbt.m5_12.local_artifacts.v1", "quantbt.m5_12.local_artifacts.v2",
                "qms-e08-local-artifacts-v1"}
            or not isinstance(manifest.get("package_proof_sha256"), str)
            or len(manifest["package_proof_sha256"]) != 64):
        raise ValueError("fresh selected-prefix/proof manifest required; historical snapshots grant no execution rights")
    helper = Path(__file__).with_name("qms_e08_consumer.py")
    if sha256(helper.read_bytes()).hexdigest() != manifest["fixture_sha256"]["tools/qms_e08_consumer.py"]:
        raise ValueError("installed identity helper drift")
    identity = identity_helper(helper).identity
    package = identity(manifest, kind)
    def fixtures():
        for name, expected in manifest["fixture_sha256"].items():
            if sha256((args.root/name).read_bytes()).hexdigest() != expected:
                raise ValueError("integrated consumer source drift")
    fixtures()
    # Load financial modules from site-packages before allowing public fixtures.
    sys.path.append(str(args.root))
    from quantbt.optimization.meta_selection.telemetry import observed_threads
    previous_argv = sys.argv
    sys.argv = [str(args.root/"tools"/args.consumer), *args.arguments]
    captured = StringIO()
    try:
        with redirect_stdout(captured):
            runpy.run_path(sys.argv[0], run_name="__main__")
    finally:
        sys.argv = previous_argv
        print(captured.getvalue(), end="")
    result = json.loads(captured.getvalue().splitlines()[-1])
    # identity() already verifies loaded core/native origins and complete
    # namespace inventories; do not retain the old one-root origins adapter.
    if identity(manifest, kind) != package:
        raise ValueError("related consumer identity changed during execution")
    fixtures()
    if args.manifest.read_bytes() != raw_manifest:
        raise ValueError("integrated consumer manifest changed during execution")
    threads = observed_threads(native_serial=True)
    if threads["mismatches"] or threads["inspection_limits"]:
        raise ValueError("integrated consumer thread mismatch")
    return dict(schema="qms-e08-related-installed-v1", identity=package, kind=kind,
        consumer=args.consumer, result=result, threads=threads, publication=False,
        manifest_sha256=sha256(raw_manifest).hexdigest())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--consumer", required=True)
    parser.add_argument("--kind", choices=("pair", "sdist"), required=True)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.arguments[:1] == ["--"]:
        args.arguments = args.arguments[1:]
    print(json.dumps(consume(args), sort_keys=True))
