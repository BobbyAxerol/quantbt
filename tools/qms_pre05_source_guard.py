"""Exact portable-dispatch amendment, not a financial/math file exemption."""

from hashlib import sha256
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "d0cd95a"
MANIFEST = (
    ROOT / "benchmarks/optimization/meta_selection/qms_pre_e06_05_reviewed_source_v2.json"
)
ALLOW = frozenset({"src/quantbt/optimization/meta_selection/common.py"})


def baseline(name):
    return subprocess.check_output(["git", "show", f"{ENTRY}:{name}"], cwd=ROOT)


def without_pre05(source, name):
    from tools.qms_e08_source_guard import without_e07_e08
    source = without_e07_e08(source, name)
    if name not in ALLOW:
        return source
    before = baseline(name)
    if source == before:
        return before
    manifest = json.loads(MANIFEST.read_text())
    if (
        manifest.get("baseline") != ENTRY
        or set(manifest.get("source_sha256", {})) != ALLOW
        or manifest["source_sha256"][name] != sha256(source).hexdigest()
    ):
        raise AssertionError(f"unreviewed PRE05 source: {name}")
    return before


def prior_names(names, entry):
    """Remove only an exact amendment absent from the historical scope."""
    result = set(names)
    from tools.qms_e08_source_guard import ALLOW as E08_ALLOW, RUNTIME
    for name in result & (ALLOW | E08_ALLOW | {RUNTIME}):
        normalized = without_pre05((ROOT / name).read_bytes(), name)
        old = subprocess.run(["git", "show", f"{entry}:{name}"], cwd=ROOT,
                             capture_output=True, check=False)
        if old.returncode == 0 and normalized == old.stdout:
            result.remove(name)
    return result


def verify():
    names = set(
        subprocess.check_output(
            ["git", "diff", "--name-only", ENTRY, "--", "src", "rust"],
            cwd=ROOT,
            text=True,
        ).splitlines()
    )
    names.update(
        subprocess.check_output(
            ["git", "ls-files", "--others", "--exclude-standard", "--", "src", "rust"],
            cwd=ROOT,
            text=True,
        ).splitlines()
    )
    names = prior_names(names - ALLOW, ENTRY) | (names & ALLOW)
    if names != ALLOW:
        raise AssertionError(f"unreviewed PRE05 runtime scope: {sorted(names ^ ALLOW)}")
    for name in names:
        assert without_pre05((ROOT / name).read_bytes(), name) == baseline(name)
    return dict(
        baseline=ENTRY,
        changed_runtime=sorted(names),
        scientific_or_accounting_changed=False,
        native_rebuild_required=False,
        publication=False,
    )


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal-reviewed", action="store_true")
    if parser.parse_args().seal_reviewed:
        with MANIFEST.open("x") as stream:
            json.dump(
                dict(
                    baseline=ENTRY,
                    source_sha256={
                        n: sha256((ROOT / n).read_bytes()).hexdigest()
                        for n in sorted(ALLOW)
                    },
                ),
                stream,
                indent=2,
                sort_keys=True,
            )
            stream.write("\n")
    print(json.dumps(verify(), sort_keys=True))


if __name__ == "__main__":
    main()
