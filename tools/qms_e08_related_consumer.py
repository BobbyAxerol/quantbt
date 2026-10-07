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

def consume(args):
    manifest = json.loads(args.manifest.read_text())
    if (Path(args.consumer).name != args.consumer
            or args.consumer not in manifest["allowed_consumers"]):
        raise ValueError("unregistered installed consumer")
    helper = Path(__file__).with_name("qms_e08_consumer.py")
    if sha256(helper.read_bytes()).hexdigest() != manifest["fixture_sha256"]["tools/qms_e08_consumer.py"]:
        raise ValueError("installed identity helper drift")
    spec = importlib.util.spec_from_file_location("e08_identity", helper)
    identity_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(identity_module)
    identity, origins = identity_module.identity, identity_module.origins
    package = identity(manifest)
    def fixtures():
        for name, expected in manifest["fixture_sha256"].items():
            if sha256((args.root/name).read_bytes()).hexdigest() != expected:
                raise ValueError("integrated consumer source drift")
    fixtures()
    # Load financial modules from site-packages before allowing public fixtures.
    sys.path.append(str(args.root))
    from quantbt.optimization.meta_selection.telemetry import observed_threads
    sys.argv = [str(args.root/"tools"/args.consumer), *args.arguments]
    captured = StringIO()
    try:
        with redirect_stdout(captured):
            runpy.run_path(sys.argv[0], run_name="__main__")
    finally:
        print(captured.getvalue(), end="")
    result = json.loads(captured.getvalue().splitlines()[-1])
    origins(Path(package["core_origin"]))
    identity(manifest)
    fixtures()
    threads = observed_threads(native_serial=True)
    if threads["mismatches"] or threads["inspection_limits"]:
        raise ValueError("integrated consumer thread mismatch")
    return dict(schema="qms-e08-related-installed-v1", identity=package,
        consumer=args.consumer, result=result, threads=threads, publication=False,
        manifest_sha256=sha256(args.manifest.read_bytes()).hexdigest())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--consumer", required=True)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.arguments[:1] == ["--"]:
        args.arguments = args.arguments[1:]
    print(json.dumps(consume(args), sort_keys=True))
