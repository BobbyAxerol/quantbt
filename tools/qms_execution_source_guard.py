"""Exact execution-route amendment; old phase receipts remain immutable."""

from hashlib import sha256
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "566adcb"
MANIFEST = ROOT / "benchmarks/optimization/meta_selection/qms_execution_reviewed_source.json"
ALLOW = frozenset({"src/quantbt/endpoint.py", "src/quantbt/walkforward.py", "src/quantbt/wfo_execution.py",
    "src/quantbt/engines.py",
    "src/quantbt/core/delivery_lifecycle.py",
    *["src/quantbt/optimization/meta_selection/"+n for n in ("config.py", "observer.py")],
    *["src/quantbt/optimization/meta_selection/domains/"+n for n in ("registry.py", "execution.py")]})
SEALED_ALLOW = ALLOW
ALLOW = ALLOW | {"src/quantbt/optimization/meta_selection/domains/base.py"}
from tools.qms_pre03_source_guard import ALLOW as PRE03_ALLOW
from tools.qms_pre04_source_guard import ALLOW as PRE04_ALLOW
REVIEWED_SCOPE = ALLOW | PRE03_ALLOW | PRE04_ALLOW


def without_execution_routes(source, name):
    from tools.qms_pre02_source_guard import without_pre02_repairs
    source = without_pre02_repairs(source, name)
    if name not in ALLOW:
        return source
    original = subprocess.run(["git", "show", f"{ENTRY}:{name}"], cwd=ROOT, capture_output=True)
    before = original.stdout if original.returncode == 0 else b""
    if source == before:
        return source
    manifest = json.loads(MANIFEST.read_text())
    if manifest["baseline"] != ENTRY or set(manifest["source_sha256"]) != SEALED_ALLOW:
        raise AssertionError("execution amendment reviewed scope mismatch")
    if sha256(source).hexdigest() != manifest["source_sha256"][name]:
        raise AssertionError(f"unreviewed execution route bytes: {name}")
    return before


def verify():
    names = set(subprocess.check_output(["git", "diff", "--name-only", ENTRY,
        "--", "src", "rust"], cwd=ROOT, text=True).splitlines())
    names.update(subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard",
        "--", "src", "rust"], cwd=ROOT, text=True).splitlines())
    from tools.qms_pre05_source_guard import prior_names
    names = prior_names(names, ENTRY)
    if names != REVIEWED_SCOPE:
        raise AssertionError(f"unreviewed execution source: {sorted(names ^ REVIEWED_SCOPE)}")
    for name in names:
        without_execution_routes((ROOT/name).read_bytes(), name)
    return dict(schema="qms-execution-route-exact-amendment-v1", baseline=ENTRY,
        source_sha256=json.loads(MANIFEST.read_text())["source_sha256"],
        scientific_estimator_changed=False, native_financial_kernel_changed=False,
        quarterly_policy="pre_expiry_flatten_v1", cash_settlement=False, publication=False)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal-reviewed", action="store_true")
    if parser.parse_args().seal_reviewed:
        MANIFEST.write_text(json.dumps(dict(baseline=ENTRY, source_sha256={
            n: sha256((ROOT/n).read_bytes()).hexdigest() for n in sorted(ALLOW)}), indent=2, sort_keys=True)+"\n")
    print(json.dumps(verify(), sort_keys=True))
