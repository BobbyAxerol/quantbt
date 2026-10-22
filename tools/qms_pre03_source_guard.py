"""Exact approved C01 amendment, layered over immutable historical receipts."""

from hashlib import sha256
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "ca57fc3"
MANIFEST = ROOT/"benchmarks/optimization/meta_selection/qms_pre_e06_03_reviewed_source.json"
ALLOW = frozenset({"src/quantbt/walkforward.py", *[
    "src/quantbt/optimization/meta_selection/"+name for name in
    ("config.py", "runtime.py", "nested.py", "domains/registry.py")]})


def baseline(name):
    result = subprocess.run(["git", "show", f"{ENTRY}:{name}"], cwd=ROOT, capture_output=True)
    if result.returncode and name != "src/quantbt/optimization/meta_selection/nested.py":
        raise AssertionError("missing reviewed PRE03 baseline")
    return result.stdout if result.returncode == 0 else b""


def without_pre03(source, name):
    from tools.qms_pre04_source_guard import without_pre04
    source = without_pre04(source, name)
    if name not in ALLOW:
        return source
    before = baseline(name)
    if source == before:
        return source
    manifest = json.loads(MANIFEST.read_text())
    if (manifest.get("baseline") != ENTRY or set(manifest.get("source_sha256", {})) != ALLOW
            or sha256(source).hexdigest() != manifest["source_sha256"][name]):
        raise AssertionError(f"unreviewed PRE03 source: {name}")
    return before


def verify():
    from tools.qms_pre04_source_guard import ALLOW as later_allow, verify as later_verify
    names = set(subprocess.check_output(["git", "diff", "--name-only", ENTRY, "--", "src", "rust"],
                                      cwd=ROOT, text=True).splitlines())
    names.update(subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "--", "src", "rust"],
                                        cwd=ROOT, text=True).splitlines())
    from tools.qms_pre05_source_guard import prior_names
    names = prior_names(names, ENTRY)
    if names != ALLOW | later_allow:
        raise AssertionError(f"unreviewed PRE03 runtime scope: {sorted(names ^ (ALLOW | later_allow))}")
    later_verify()
    for name in names:
        without_pre03((ROOT/name).read_bytes(), name)
    return dict(baseline=ENTRY, cohort="nested_anchor_outer_IS_real_forward_v1",
        changed_runtime=sorted(names), original_guide_changed=False,
        ridge_or_metric_estimator_changed=False, native_financial_kernel_changed=False,
        c05_activated=False, publication=False)


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal-reviewed", action="store_true")
    args=parser.parse_args()
    if args.seal_reviewed:
        MANIFEST.write_text(json.dumps(dict(baseline=ENTRY, source_sha256={
            n: sha256((ROOT/n).read_bytes()).hexdigest() for n in sorted(ALLOW)}), indent=2, sort_keys=True)+"\n")
    print(json.dumps(verify(), sort_keys=True))


if __name__ == "__main__":
    main()
