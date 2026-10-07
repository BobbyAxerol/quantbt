"""Exact E07 output amendment, immutable evidence and bounded resource contract."""

from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess

from tools.qms08_package import ROOT, file_hash
from tools.qms_pre06_contract import core_inventory, native_reuse, write_once

ENTRY = "1a0f892"
LANE = ROOT / ".maturin/qms08/e07-qualification-v1"
RUNTIME = "src/quantbt/optimization/meta_selection/runtime.py"
GUIDE = "upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md"
NATIVE = ROOT / ".maturin/qms08/g01-package-v1-native/quantbt_native-0.4.3-cp312-cp312-manylinux_2_34_x86_64.whl"
MODES = ("off", "shadow", "active")
REPEATS = 3


def source_guard():
    names = subprocess.check_output(["git", "ls-files", "src/quantbt", "rust", "pyproject.toml", "MANIFEST.in"],
                                    cwd=ROOT, text=True).splitlines()
    additions = ((b"        self.records, self.models, self.tasks, self.snapshots = [], {}, [], []\n",
        b"        self.observed_revisions = []\n"),
        (b"        self.context.history.append(revision)\n", b"        self.observed_revisions.append(revision)\n"),
        (b'            "snapshots": tuple(self.snapshots),\n',
         b'            "observed_revisions": tuple(self.observed_revisions),\n'))
    hashes = {}
    for name in names:
        actual = (ROOT / name).read_bytes()
        old = subprocess.check_output(["git", "show", f"{ENTRY}:{name}"], cwd=ROOT)
        hashes[name] = sha256(actual).hexdigest()
        if name == RUNTIME:
            for anchor, insertion in additions:
                if old.count(anchor) != 1:
                    raise ValueError("ambiguous E07 output amendment")
                old = old.replace(anchor, anchor+insertion, 1)
        if actual != old:
            raise ValueError(f"unapproved E07 runtime/build change: {name}")
    return hashes


def register():
    prior = json.loads((ROOT / ".maturin/qms08/e06-qualification-v1/registration.json").read_text())
    protected = {str(p.relative_to(ROOT)): file_hash(p)
        for p in (ROOT / "benchmarks/optimization/meta_selection").glob("*") if p.is_file()}
    for directory in (ROOT / ".maturin/qms08/e06-qualification-v1", ROOT / ".maturin/qms08/pre-e06-05/history"):
        protected.update({str(p.relative_to(ROOT)): file_hash(p) for p in directory.rglob("*") if p.is_file()})
    for path in prior["artifacts"].values():
        protected[str(Path(path).relative_to(ROOT))] = file_hash(path)
    disk = os.statvfs(ROOT)
    if disk.f_bavail * disk.f_frsize < 8 * 1024**3:
        raise ValueError("E07 registered headroom unavailable")
    value = dict(schema="qms-e07-registration-v1", entry=ENTRY, runtime_sha256=source_guard(),
        core_inventory=core_inventory(ROOT / "src/quantbt"), guide_sha256=file_hash(ROOT / GUIDE),
        native=native_reuse(NATIVE), protected_sha256=protected,
        cases=[[r, b] for r, b in (("event_driven", "python"), ("event_driven", "rust"),
            ("order_commands", "python"), ("order_commands", "rust"), ("reactive_reset", "rust"))],
        modes=list(MODES), variants=[False, True], repeats=REPEATS, warmups=1,
        trials=8, seed=731, minimum_origins=12, lambda_reg=10.,
        free_bytes=disk.f_bavail*disk.f_frsize, free_inodes=disk.f_favail,
        safety_bytes=5*1024**3, budget_bytes=2560*1024**2,
        source_only=True, remote=False, publication=False, economic_promotion=False)
    write_once(LANE / "registration.json", value)
    return value


def check_registration():
    value = json.loads((LANE / "registration.json").read_text())
    if value["runtime_sha256"] != source_guard() or value["guide_sha256"] != file_hash(ROOT / GUIDE):
        raise ValueError("E07 source/guide seal drift")
    for name, expected in value["protected_sha256"].items():
        if file_hash(ROOT / name) != expected:
            raise ValueError(f"protected predecessor drift: {name}")
    return value


def validate_matrix(value, *, repeats):
    from tests.meta_selection.e07_support import CASES
    rows = value["rows"]
    if len(rows) != 30*repeats:
        raise ValueError("incomplete E07 workload matrix")
    for case in CASES:
        for mode in MODES:
            pairs = []
            for variant in (False, True):
                matches = [r for r in rows if tuple(r["case"]) == case and r["mode"] == mode and r["variant"] is variant]
                if len(matches) != repeats or len({r["repeat"] for r in matches}) != repeats:
                    raise ValueError("missing/duplicated E07 cell")
                for row in matches:
                    if not row["account_rebuild_exact"] or row["observer_failures"]:
                        raise ValueError("failed account/observer gate")
                    if mode != "off" and (row["minimum_origins"] < 12 or not row["models"]
                            or row["raw_pairs_checked"] < 2 or row["output_revisions"] != 1):
                        raise ValueError("cold/missing measurement or output gate")
                if len({r["semantic_sha256"] for r in matches}) != 1:
                    raise ValueError("nondeterministic matched cell")
                pairs.append(matches[0]["account_pool_sha256"] if case[0] == "reactive_reset"
                             else matches[0]["semantic_sha256"])
            if pairs[0] != pairs[1]:
                raise ValueError("prepared/reference logical divergence")
    return len(rows)
