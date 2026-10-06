"""Exact bounded package adapter amendment, preserving earlier source seals."""

from hashlib import sha256
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "1df2aaf"
MANIFEST = ROOT / "benchmarks/optimization/meta_selection/qms_e05_reviewed_source.json"
ALLOW = frozenset({"src/quantbt/endpoint.py", "src/quantbt/walkforward.py",
    *["src/quantbt/optimization/meta_selection/"+n for n in ("config.py", "observer.py")],
    *["src/quantbt/optimization/meta_selection/domains/"+n for n in
      ("registry.py", "portfolio.py", "package.py", "package_contract.py")]})


def without_e05_package(source, name):
    if name not in ALLOW:
        return source
    original = subprocess.run(["git", "show", f"{ENTRY}:{name}"], cwd=ROOT, capture_output=True)
    before = original.stdout if original.returncode == 0 else b""
    if source == before:
        return source
    manifest = json.loads(MANIFEST.read_text())
    if manifest.get("baseline") != ENTRY or set(manifest.get("source_sha256", {})) != ALLOW:
        raise AssertionError("E05 reviewed manifest scope mismatch")
    if sha256(source).hexdigest() != manifest["source_sha256"][name]:
        raise AssertionError(f"unreviewed E05 package bytes: {name}")
    return before


def verify():
    names = set(subprocess.check_output(["git", "diff", "--name-only", ENTRY,
        "--", "src", "rust"], cwd=ROOT, text=True).splitlines())
    names.update(subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard",
        "--", "src", "rust"], cwd=ROOT, text=True).splitlines())
    if names != ALLOW:
        raise AssertionError(f"E05 unreviewed/missing production changes: {sorted(names ^ ALLOW)}")
    for name in names:
        without_e05_package((ROOT / name).read_bytes(), name)
    protected = ("rust", "src/quantbt/core", "src/quantbt/backends", "src/quantbt/sizing",
        "src/quantbt/metrics", "src/quantbt/backtester.py", "src/quantbt/engines.py",
        "pyproject.toml", "uv.lock", "contracts",
        "upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md")
    if subprocess.check_output(["git", "diff", "--name-only", ENTRY, "--", *protected], cwd=ROOT):
        raise AssertionError("E05 financial/math/native/release identity changed")
    return dict(schema="qms-e05-exact-source-v1", baseline=ENTRY,
        source_sha256=json.loads(MANIFEST.read_text())["source_sha256"],
        financial_numeric_source_unchanged=True, publication=False)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal-reviewed", action="store_true")
    if parser.parse_args().seal_reviewed:
        MANIFEST.write_text(json.dumps(dict(baseline=ENTRY, source_sha256={n:
            sha256((ROOT/n).read_bytes()).hexdigest() for n in sorted(ALLOW)}), indent=2, sort_keys=True)+"\n")
    print(json.dumps(verify(), sort_keys=True))
