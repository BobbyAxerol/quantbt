"""Exact installed runtime identity before loading public execution test fixtures."""

import argparse
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

GROUPS = {
    "intrabar": ("test_e06_intrabar_meta.py", "test_e06_intrabar_fold_contract.py", "test_e08_bracket_incident.py"),
    "event": ("test_e07_mature.py", "test_e07_lifecycle.py", "test_e07_order_bounds.py",
              "test_e08_v3_mature.py", "test_e08_telemetry.py"),
}
EXPECTED = {"intrabar": 65, "event": 84}


def inventory(directory):
    return {p.relative_to(directory).as_posix(): sha256(p.read_bytes()).hexdigest()
        for p in directory.rglob("*") if p.is_file() and (p.suffix == ".py" or p.name == "py.typed")}


def identity(manifest):
    import quantbt
    import _quantbt_native as native
    import _quantbt_native._quantbt_native as extension
    base, binary = Path(quantbt.__file__).resolve().parent, Path(extension.__file__).resolve()
    if "site-packages" not in base.parts or "site-packages" not in binary.parts:
        raise ValueError("checkout runtime cannot be an installed proof")
    if version("quantbt-engine") != quantbt.__version__ or quantbt.__version__ != manifest["core"]:
        raise ValueError("core version mismatch")
    if version("quantbt-native") != native.version() or native.version() != manifest["native"]:
        raise ValueError("native version mismatch")
    if inventory(base) != manifest["core_inventory"]:
        raise ValueError("complete installed core source mismatch")
    if sha256(binary.read_bytes()).hexdigest() != manifest["native_extension_sha256"]:
        raise ValueError("loaded extension does not match exact wheel")
    return dict(core_origin=str(base), native_origin=str(binary), modules=len(manifest["core_inventory"]),
        core=quantbt.__version__, native=native.version(), native_sha256=manifest["native_extension_sha256"])


def origins(base):
    for name, module in tuple(sys.modules.items()):
        if name == "quantbt" or name.startswith("quantbt."):
            path = getattr(module, "__file__", None)
            if path is not None and not Path(path).resolve().is_relative_to(base):
                raise ValueError(f"checkout substitution: {name}")


def consume(args):
    manifest = json.loads(args.manifest.read_text())
    package = identity(manifest)
    def fixtures():
        for name, expected in manifest["fixture_sha256"].items():
            if sha256((args.root/name).read_bytes()).hexdigest() != expected:
                raise ValueError("public fixture source changed during installed proof")
    fixtures()
    # Only tests/examples/tools are checkout-owned; all financial code is installed.
    sys.path.append(str(args.root))
    import pytest
    from quantbt.optimization.meta_selection.telemetry import observed_threads
    code = pytest.main(["-q", "--tb=short", "--noconftest", "--import-mode=importlib",
        *[str(args.root/"tests/meta_selection"/name) for name in GROUPS[args.group]],
        f"--junitxml={args.output.with_suffix('.xml')}"])
    origins(Path(package["core_origin"]))
    identity(manifest)
    fixtures()
    suites = ET.parse(args.output.with_suffix(".xml")).getroot().findall("testsuite")
    counts = {key: sum(int(s.get(key, 0)) for s in suites) for key in ("tests", "failures", "errors", "skipped")}
    if code or counts != dict(tests=EXPECTED[args.group], failures=0, errors=0, skipped=0):
        raise ValueError(f"incomplete installed {args.group} gate: {counts}")
    threads = observed_threads(native_serial=True)
    if threads["mismatches"] or threads["inspection_limits"]:
        raise ValueError(f"unresolved qualification thread budget: {threads}")
    result = dict(schema="qms-e08-installed-execution-v1", group=args.group,
        identity=package, counts=counts, threads=threads,
        manifest_sha256=sha256(args.manifest.read_bytes()).hexdigest(),
        source_sha256={name: sha256((args.root/"tests/meta_selection"/name).read_bytes()).hexdigest()
            for name in GROUPS[args.group]}, publication=False, empirical_promotion=False)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--group", choices=GROUPS, required=True)
    print(json.dumps(consume(parser.parse_args()), sort_keys=True))
