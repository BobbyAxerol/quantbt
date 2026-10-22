"""Exact installed runtime identity before loading public execution test fixtures."""

import argparse
from hashlib import sha256
from importlib.metadata import distribution
import json
from pathlib import Path
import sys
import sysconfig
import xml.etree.ElementTree as ET

GROUPS = {
    "intrabar": ("test_e06_intrabar_meta.py", "test_e06_intrabar_fold_contract.py", "test_e08_bracket_incident.py"),
    "event": ("test_e07_mature.py", "test_e07_lifecycle.py", "test_e07_order_bounds.py",
              "test_e08_v3_mature.py", "test_e08_telemetry.py"),
}
EXPECTED = {"intrabar": 65, "event": 84}


def inventory(directory):
    result = {}
    for p in directory.rglob("*"):
        if "__pycache__" in p.parts or p.suffix in {".pyc", ".pyo"}:
            continue
        if p.is_symlink():
            raise ValueError("linked installed package member")
        if p.is_file():
            result[p.relative_to(directory).as_posix()] = sha256(p.read_bytes()).hexdigest()
    return result


def identity(manifest, kind):
    import quantbt
    import _quantbt_native as native
    import _quantbt_native._quantbt_native as extension
    prefix = Path(sys.prefix).resolve()
    if (kind not in {"pair", "sdist"} or kind not in manifest["prefixes"]
            or prefix != Path(manifest["prefixes"][kind]).resolve()
            or prefix == Path(sys.base_prefix).resolve()
            or Path(sys.executable).absolute() != prefix / "bin/python"
            or manifest["interpreter"] != "cp" + "".join(map(str, sys.version_info[:2]))
            or not sys.flags.isolated or not sys.flags.dont_write_bytecode):
        raise ValueError("exact selected isolated -I/-B consumer and interpreter required")
    sites = {Path(sysconfig.get_path(key)).resolve() for key in ("purelib", "platlib")}
    roots = {"quantbt": Path(quantbt.__file__).resolve().parent,
             "_quantbt_native": Path(native.__file__).resolve().parent}
    inventories = {"quantbt": manifest["core_inventory"], "_quantbt_native": manifest["native_inventory"]}
    for package, name, actual, expected in (
            ("quantbt", "quantbt-engine", quantbt.__version__, manifest["core"]),
            ("_quantbt_native", "quantbt-native", native.version(), manifest["native"])):
        root, dist = roots[package], distribution(name)
        if (root.parent not in sites or root.parent.name != "site-packages"
                or not root.is_relative_to(prefix) or root != root.parent / package
                or Path(dist.locate_file(package)).resolve() != root):
            raise ValueError("package/distribution outside selected installed site-packages")
        if dist.version != expected or actual != expected:
            raise ValueError("installed metadata/runtime version mismatch")
        if inventory(root) != inventories[package]:
            raise ValueError("complete installed core/native source and resource mismatch")
    binary = Path(extension.__file__).resolve()
    if not binary.is_relative_to(roots["_quantbt_native"]):
        raise ValueError("native extension outside selected namespace")
    if sha256(binary.read_bytes()).hexdigest() != manifest["native_extension_sha256"]:
        raise ValueError("loaded extension does not match exact wheel")
    origins(roots, inventories)
    return dict(core_origin=str(roots["quantbt"]), native_origin=str(binary), modules=len(manifest["core_inventory"]),
        native_package_origin=str(roots["_quantbt_native"]), native_files=len(manifest["native_inventory"]),
        prefix=str(prefix), interpreter=manifest["interpreter"], isolated=True, dont_write_bytecode=True,
        core=quantbt.__version__, native=native.version(), native_sha256=manifest["native_extension_sha256"])


def origins(roots, inventories):
    for name, module in tuple(sys.modules.items()):
        package = name.split(".", 1)[0]
        if package in roots and module is not None:
            value = getattr(module, "__file__", None)
            if not value:
                raise ValueError(f"missing installed module origin: {name}")
            path = Path(value).resolve()
            if (not path.is_relative_to(roots[package])
                    or inventories[package].get(path.relative_to(roots[package]).as_posix())
                    != sha256(path.read_bytes()).hexdigest()):
                raise ValueError(f"checkout substitution: {name}")
            if any(Path(entry).resolve() != path.parent for entry in getattr(module, "__path__", ())):
                raise ValueError(f"external package search path: {name}")


def consume(args):
    raw_manifest = args.manifest.read_bytes()
    manifest = json.loads(raw_manifest)
    package = identity(manifest, args.kind)
    def fixtures():
        for name, expected in manifest["fixture_sha256"].items():
            if sha256((args.root/name).read_bytes()).hexdigest() != expected:
                raise ValueError("public fixture source changed during installed proof")
    fixtures()
    fixture_temp = args.output.parent / (args.output.stem + "-fixtures")
    if fixture_temp.exists() or fixture_temp.is_symlink():
        raise ValueError("installed fixture scratch already exists; use a fresh output")
    # Only tests/examples/tools are checkout-owned; all financial code is installed.
    sys.path.append(str(args.root))
    import pytest
    from quantbt.optimization.meta_selection.telemetry import observed_threads
    code = pytest.main(["-q", "--tb=short", "--noconftest", "--import-mode=importlib",
        "-p", "no:cacheprovider", "--basetemp", str(fixture_temp),
        *[str(args.root/"tests/meta_selection"/name) for name in GROUPS[args.group]],
        f"--junitxml={args.output.with_suffix('.xml')}"])
    if identity(manifest, args.kind) != package:
        raise ValueError("consumer identity changed during execution")
    fixtures()
    if args.manifest.read_bytes() != raw_manifest:
        raise ValueError("consumer manifest changed during execution")
    suites = ET.parse(args.output.with_suffix(".xml")).getroot().findall("testsuite")
    counts = {key: sum(int(s.get(key, 0)) for s in suites) for key in ("tests", "failures", "errors", "skipped")}
    if code or counts != dict(tests=EXPECTED[args.group], failures=0, errors=0, skipped=0):
        raise ValueError(f"incomplete installed {args.group} gate: {counts}")
    threads = observed_threads(native_serial=True)
    if threads["mismatches"] or threads["inspection_limits"]:
        raise ValueError(f"unresolved qualification thread budget: {threads}")
    result = dict(schema="qms-e08-installed-execution-v1", group=args.group, kind=args.kind,
        identity=package, counts=counts, threads=threads,
        manifest_sha256=sha256(raw_manifest).hexdigest(),
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
    parser.add_argument("--kind", choices=("pair", "sdist"), required=True)
    print(json.dumps(consume(parser.parse_args()), sort_keys=True))
