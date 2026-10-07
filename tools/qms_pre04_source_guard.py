"""Exact approved C05 runtime amendment; historical receipts stay immutable."""

from hashlib import sha256
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "ba61e63"
MANIFEST = ROOT/"benchmarks/optimization/meta_selection/qms_pre_e06_04_reviewed_source.json"
NEW = frozenset("src/quantbt/optimization/"+n for n in ("conditional_sobol.py", "representatives.py"))
ALLOW = NEW | frozenset({"src/quantbt/endpoint.py", "src/quantbt/walkforward.py", *[
    "src/quantbt/optimization/"+n for n in ("config.py", "samplers.py", "wfo_study.py",
        "continuation/contract.py", "continuation/session.py", "meta_selection/runtime.py")], *[
    "src/quantbt/backends/"+n for n in ("reactive_wfo.py", "reactive_wfo_sampling.py", "reactive_wfo_support.py")]})


def baseline(name):
    result = subprocess.run(["git", "show", f"{ENTRY}:{name}"], cwd=ROOT, capture_output=True)
    if result.returncode and name not in NEW:
        raise AssertionError("missing reviewed PRE04 baseline")
    return result.stdout if result.returncode == 0 else b""


def without_pre04(source, name):
    from tools.qms_pre05_source_guard import without_pre05
    source = without_pre05(source, name)
    if name not in ALLOW:
        return source
    before = baseline(name)
    if source == before:
        return before
    manifest = json.loads(MANIFEST.read_text())
    if (manifest.get("baseline") != ENTRY or set(manifest.get("source_sha256", {})) != ALLOW
            or sha256(source).hexdigest() != manifest["source_sha256"][name]):
        raise AssertionError(f"unreviewed PRE04 source: {name}")
    return before


def verify():
    names = set(subprocess.check_output(["git", "diff", "--name-only", ENTRY, "--", "src", "rust"],
                                      cwd=ROOT, text=True).splitlines())
    names.update(subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "--", "src", "rust"],
                                        cwd=ROOT, text=True).splitlines())
    from tools.qms_pre05_source_guard import prior_names
    names = prior_names(names, ENTRY)
    if names != ALLOW:
        raise AssertionError(f"unreviewed PRE04 runtime scope: {sorted(names ^ ALLOW)}")
    for name in names:
        without_pre04((ROOT/name).read_bytes(), name)
    return dict(baseline=ENTRY, changed_runtime=sorted(names),
        conditional_sobol="conditional_numeric_latent_v1",
        representative="feasible_support_projection_v1", old_defaults_changed=False,
        accounting_or_ridge_changed=False, publication=False)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal-reviewed", action="store_true")
    args = parser.parse_args()
    if args.seal_reviewed:
        MANIFEST.write_text(json.dumps(dict(baseline=ENTRY, source_sha256={
            n: sha256((ROOT/n).read_bytes()).hexdigest() for n in sorted(ALLOW)}), indent=2, sort_keys=True)+"\n")
    print(json.dumps(verify(), sort_keys=True))


if __name__ == "__main__":
    main()
