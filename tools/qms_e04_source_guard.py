"""Exact reviewed portfolio amendment; original financial/Rust math is sealed."""

from hashlib import sha256
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "7b83ba4"
MANIFEST = ROOT / "benchmarks/optimization/meta_selection/qms_e04_reviewed_source.json"
ALLOW = frozenset({"src/quantbt/endpoint.py", "src/quantbt/walkforward.py",
    *["src/quantbt/optimization/meta_selection/" + n for n in
      ("config.py", "runtime.py", "observer.py")],
    *["src/quantbt/optimization/meta_selection/domains/" + n for n in
      ("registry.py", "portfolio.py", "portfolio_contract.py", "portfolio_witness.py")]})


def without_e04_portfolio(source, name):
    from tools.qms_e05_source_guard import without_e05_package
    source = without_e05_package(source, name)
    if name not in ALLOW:
        return source
    original = subprocess.run(["git", "show", f"{ENTRY}:{name}"], cwd=ROOT, capture_output=True)
    before = original.stdout if original.returncode == 0 else b""
    if source == before:
        return source
    manifest = json.loads(MANIFEST.read_text())
    if manifest.get("baseline") != ENTRY or set(manifest.get("source_sha256", {})) != ALLOW:
        raise AssertionError("E04 reviewed manifest scope mismatch")
    if sha256(source).hexdigest() != manifest["source_sha256"][name]:
        raise AssertionError(f"unreviewed E04 portfolio bytes: {name}")
    return before


def verify():
    from tools.qms_e05_source_guard import verify as verify_e05
    verify_e05()
    names = set(subprocess.check_output(["git", "diff", "--name-only", ENTRY,
        "--", "src", "rust"], cwd=ROOT, text=True).splitlines())
    names.update(subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard",
        "--", "src", "rust"], cwd=ROOT, text=True).splitlines())
    scope = reviewed_scope()
    if names != scope:
        raise AssertionError(f"E04 unreviewed/missing production changes: {sorted(names ^ scope)}")
    for name in names:
        without_e04_portfolio((ROOT / name).read_bytes(), name)
    protected = ("rust", "src/quantbt/core", "src/quantbt/backends", "src/quantbt/sizing",
        "src/quantbt/backtester.py", "src/quantbt/engines.py", "src/quantbt/metrics",
        "pyproject.toml", "uv.lock", "contracts",
        "upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md")
    from tools.qms_g01_source_guard import protected_changes
    if protected_changes(ENTRY, protected):
        raise AssertionError("E04 financial/math/native/release identity changed")
    return dict(schema="qms-e04-exact-source-v1", baseline=ENTRY,
        source_sha256=json.loads(MANIFEST.read_text())["source_sha256"],
        financial_numeric_source_unchanged=True, publication=False)


def reviewed_scope():
    from tools.qms_e05_source_guard import ALLOW as later_scope
    from tools.qms_g01_source_guard import ALLOW as G01_ALLOW
    return ALLOW | later_scope | G01_ALLOW


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal-reviewed", action="store_true")
    if parser.parse_args().seal_reviewed:
        MANIFEST.write_text(json.dumps(dict(baseline=ENTRY, source_sha256={
            name: sha256((ROOT / name).read_bytes()).hexdigest() for name in sorted(ALLOW)}),
            indent=2, sort_keys=True)+"\n")
    print(json.dumps(verify(), sort_keys=True))
