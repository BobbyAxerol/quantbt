"""Independent E02 source, actual parity, JUnit, installed and resource gate."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

from tools.qms_e01_gate import check_package, file_hash
from tools.qms_e02_audit import compare
from tools.qms_e02_inventory import verify as inventory
from tools.qms_e02_source_guard import ROOT, ENTRY, MANIFEST, verify as source_guard
from tools.qms01_baseline import GUIDE, GUIDE_SHA, ROUTES


def check_tests(paths):
    groups = {f"E02-T{i:02}": set() for i in range(1, 7)}
    cases = set()
    for path in paths:
        tree = ET.parse(path).getroot()
        for suite in tree.iter("testsuite"):
            if any(int(suite.get(key, 0)) for key in ("errors", "failures", "skipped")):
                raise ValueError("E02 non-passing JUnit")
        for case in tree.iter("testcase"):
            if any(case.find(key) is not None for key in ("error", "failure", "skipped")):
                raise ValueError("E02 non-passing case")
            identity = case.get("classname"), case.get("name")
            if not all(identity):
                raise ValueError("E02 missing test identity")
            cases.add(identity)
            for i in range(1, 7):
                if identity[1].startswith(f"test_e02_t{i:02}_"):
                    groups[f"E02-T{i:02}"].add(identity)
    if not cases or any(not members for members in groups.values()):
        raise ValueError("E02 required executed test group missing")
    return dict(unique_tests=len(cases), groups={k: len(v) for k, v in groups.items()})


def check_parity(old, new):
    if (new.get("exact_parity") is not True
            or [(r["mode"], r["schedule"]) for r in old["native"]["lanes"]] != list(ROUTES)
            or set(old["scalar"]) != {"off-False", "shadow-False", "shadow-True", "active-True"}
            or set(old["reactive"]) != {"None", "shadow", "active"}):
        raise ValueError("E02 actual parity lane/flag missing")
    compare(old, new)
    before_source = subprocess.check_output(["git", "show", f"{ENTRY}:src/quantbt/walkforward.py"], cwd=ROOT)
    after_source = (ROOT / "src/quantbt/walkforward.py").read_bytes()
    if (old["native"]["walkforward_sha256"] != sha256(before_source).hexdigest()
            or new["native"]["walkforward_sha256"] != sha256(after_source).hexdigest()):
        raise ValueError("E02 snapshots do not bind actual source")
    for name, expected in old["native"]["historical_receipts"].items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT / "benchmarks/optimization/meta_selection") or file_hash(path) != expected:
            raise ValueError("E02 immutable receipt changed")
    if file_hash(ROOT / GUIDE) != GUIDE_SHA:
        raise ValueError("E02 protected guide changed")
    return dict(native_routes=8, scalar_lanes=4, reactive_lanes=3,
        search_pool_anchor_params_account_rng_exact=True,
        measured_clock_revision_bytes="not compared; availability clocks vary per wall-time run; ordered counts and selected decisions compared",
        historical_receipts_unchanged=True, guide_sha256=GUIDE_SHA)


def check_resources(receipt):
    rows, repeats = receipt.get("rows", []), receipt.get("repeats")
    if receipt.get("schema") != "qms-e02-matched-resources-v1" or repeats != 3 or len(rows) != 18:
        raise ValueError("E02 matched resource matrix missing")
    for row in rows:
        log = (ROOT / row["log"]).resolve()
        if not log.is_relative_to(ROOT / ".maturin/qms08") or file_hash(log) != row["log_sha256"]:
            raise ValueError("E02 resource log changed")
        actual = json.loads(next(line for line in reversed(log.read_text().splitlines()) if line.startswith("{")))
        if actual != {k: v for k, v in row.items() if k not in ("source", "repeat", "log", "log_sha256")}:
            raise ValueError("E02 resource row is not logged output")
        if any(row[k] <= 0 for k in ("seconds", "cpu_seconds", "fresh_process_peak_rss_mib")):
            raise ValueError("E02 measured resources missing")
    for repeat in range(repeats):
        for lane in ("scalar-off", "scalar-active", "reactive-active"):
            pair = [r for r in rows if r["repeat"] == repeat and r["lane"] == lane]
            if len(pair) != 2 or {r["source"] for r in pair} != {"baseline", "current"}:
                raise ValueError("E02 same-work resource pair missing")
            a, b = pair
            for key in ("scientific_signature", "logical_trials", "retained_bars", "observer_attempts", "observer_failures"):
                if a[key] != b[key]:
                    raise ValueError("E02 resource work/account mismatch")
            current = next(r for r in pair if r["source"] == "current")
            adapter = current["adapter"]
            if lane == "scalar-off":
                if adapter is not None:
                    raise ValueError("E02 disabled adapter unexpectedly instantiated")
            elif (not adapter or adapter["financial_delegate_calls"] != current["observer_attempts"]
                    or adapter["original_observations"] != current["observer_attempts"]
                    or any(adapter[k] != 0 for k in ("financial_replays", "adapter_market_array_copies",
                        "adapter_owned_market_bytes", "adapter_pyo3_calls"))):
                raise ValueError("E02 hidden adapter financial/copy/FFI work")
    return dict(repeats=3, fresh_process_runs=18, work_and_accounts_exact=True,
        disabled_adapter_absent=True, added_market_copies_ffi_replays=0, summary=receipt["summary"],
        performance_claim="small engineering fixture; no speed-promotion or p95 budget claim")


def check_adapter_consumers(directory):
    result = {}
    for label in ("wheel", "sdist"):
        log = directory / f"e02-{label}-adapter-v2.log"
        record = json.loads(next(line for line in reversed(log.read_text().splitlines()) if line.startswith("{")))
        telemetry = record["telemetry"]
        if (record.get("schema") != "qms-e02-installed-adapter-v1"
                or (record["core"], record["native"]) != ("1.1.2", "0.4.3")
                or "site-packages" not in Path(record["installed_origin"]).parts
                or record["off_shadow_account_exact"] is not True or record["observer_attempts"] <= 0
                or not telemetry["closed"] or telemetry["financial_delegate_calls"] != record["observer_attempts"]
                or telemetry["original_observations"] != record["observer_attempts"]
                or set(record["pending_routes_rejected"]) != {"portfolio", "basket", "intrabar", "order_commands", "options", "nautilus_validation"}
                or record["example_sha256"] != file_hash(ROOT / "examples/wfo_meta_selection.py")):
            raise ValueError("E02 actual installed adapter proof missing")
        result[label] = dict(log=str(log.resolve().relative_to(ROOT)), log_sha256=file_hash(log), record=record)
    return result


def verify(*, before, after, package, resources, junit):
    source = source_guard()
    tests = check_tests(junit)
    parity = check_parity(json.loads(before.read_text()), json.loads(after.read_text()))
    if json.loads(after.read_text())["baseline_sha256"] != file_hash(before):
        raise ValueError("E02 baseline binding mismatch")
    installed = check_package(json.loads(package.read_text()))
    adapter = check_adapter_consumers(package.parent)
    measured = check_resources(json.loads(resources.read_text()))
    files = (before, after, package, resources, *junit, MANIFEST,
             ROOT / "tools/qms_e02_audit.py", ROOT / "tools/qms_e02_consumer.py",
             ROOT / "tools/qms_e02_measure.py", ROOT / "tools/qms_e02_gate.py")
    return dict(schema="qms-e02-gate-v1", status="PASS_LOCAL_APPROVED_SCOPE",
        source_guard=source, regression=tests, parity=parity, installed=installed,
        installed_adapter=adapter, resources=measured, inventory=inventory(),
        gates={f"E02-T{i:02}": "PASS" for i in range(1, 7)},
        inputs={str(p.resolve().relative_to(ROOT)): file_hash(p) for p in files},
        remote="NOT_RUN_FINAL_SOURCE_E08", public="PENDING_OWNER_RELEASE",
        new_domains="NOT_ACTIVATED_E03_E07", empirical="NOT_ASSESSED_NO_NEW_STUDY", publication=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("before", "after", "package", "resources", "output"):
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--junit", action="append", type=Path, required=True)
    args = vars(parser.parse_args())
    output = args.pop("output")
    if output.exists():
        raise ValueError("sealed E02 gate exists; choose a fresh output")
    receipt = verify(**args)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True)+"\n")
    print(json.dumps(dict(status=receipt["status"], tests=receipt["regression"]["unique_tests"], publication=False)))
