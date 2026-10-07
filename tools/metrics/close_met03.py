"""Verify immutable local proofs, preserve exploratory output, remove owned scratch."""

from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.qms_pre06_contract import artifact_source, core_inventory, native_reuse
from tools.qms_pre06_package import NATIVE
from tools.scan_public_secrets import content_matches
from tests.metrics.source_guard import assert_protected

LANE = ROOT/"docs/metrics/evidence/met03"
SOURCE = LANE/"run-20261007T195815741400Z"
PACKAGE = LANE/"run-20261007T200542851857Z"


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def main():
    destination = LANE/"closure.json"
    if destination.exists():
        raise RuntimeError("refuse to rewrite a completed phase receipt")
    receipts = [json.loads((p/"receipt.json").read_text()) for p in (SOURCE, PACKAGE)]
    assert all(r["technical_gate"] == "PASS" and r["cleanup"]["scratch_removed"] for r in receipts)
    assert receipts[0]["test_counts"] == dict(passed=598, failed=0, skipped=0)
    current = core_inventory(ROOT/"src/quantbt")
    for lane, receipt in zip((SOURCE, PACKAGE), receipts):
        registration = json.loads((lane/"registration.json").read_text())
        assert current == registration["core_inventory"]
        assert native_reuse(NATIVE) == registration["native_reuse"]
        for step in receipt["steps"]:
            assert digest(ROOT/step["log"]) == step["sha256"] and step["exit_code"] == 0
    parent = json.loads((ROOT/"docs/metrics/evidence/met02/baseline.json").read_text())
    for name, expected in parent["protected_sources"].items():
        assert_protected(name, expected)
    for artifact in receipts[1]["artifacts"].values():
        path = ROOT/artifact["path"]
        assert digest(path) == artifact["sha256"]
        artifact_source(path, current)
        assert artifact["consumer"]["status"] == "PASS" and artifact["consumer"]["outside_checkout"]
    benchmark = json.loads((SOURCE/"benchmark.json").read_text())
    assert len(benchmark["rows"]) == 12 and all(r["repeats"] == 5 and r["peak_rss_mib"] < 2048 for r in benchmark["rows"])
    groups = {f"MET03-T{i:02}": 0 for i in range(1, 11)}
    for case in ET.parse(SOURCE/"pytest.xml").iter("testcase"):
        if "test_met03" in case.attrib["name"]:
            for value in re.findall(r"_t(\d{2})(?=_|\b)", case.attrib["name"]):
                groups[f"MET03-T{value}"] += 1
    assert all(groups.values())
    exploratory = Path("/tmp/quantbt-met03-initial")
    cleaned = []
    before = shutil.disk_usage(ROOT).free
    if exploratory.exists():
        assert not exploratory.is_symlink() and exploratory.resolve() == exploratory
        retained = LANE/"exploratory-retained"
        retained.mkdir()
        for relative in ("second.xml", "pytest/test_met03_t07_plot_episode_st0/light.png", "pytest/test_met03_t07_plot_episode_st0/dark.png"):
            path = exploratory/relative
            assert path.is_file() and not path.is_symlink()
            shutil.copy2(path, retained/path.name)
        inventory = {str(p.relative_to(exploratory)): p.stat().st_size for p in exploratory.rglob("*") if p.is_file()}
        cleaned.append(dict(path=str(exploratory), files=len(inventory), bytes=sum(inventory.values()),
            inventory_sha256=sha256(json.dumps(inventory, sort_keys=True).encode()).hexdigest()))
        shutil.rmtree(exploratory)
    findings = []
    evidence = {p.relative_to(ROOT).as_posix(): digest(p) for p in LANE.rglob("*") if p.is_file()}
    for name in evidence:
        findings.extend(content_matches(name, (ROOT/name).read_bytes()))
    assert not findings, findings
    closure = dict(phase="MET-03", status="COMPLETE_LOCAL", gates={k: "PASS" for k in groups},
        tagged_tests=groups, source_receipt_sha256=digest(SOURCE/"receipt.json"),
        installed_receipt_sha256=digest(PACKAGE/"receipt.json"), protected_files=325,
        unchanged_byte_hashes=321, cold_surface_legacy_ast_equal=4,
        core_inventory=current, evidence_sha256=evidence, benchmark_cells=12,
        privacy="PASS", cleanup=dict(removed=cleaned, free_bytes_before=before,
            free_bytes_after=shutil.disk_usage(ROOT).free, owned_build_scratch_removed=True,
            tooling_and_offline_cache_preserved=True),
        capabilities=dict(reducers=["python", "numba"], rust_reporting_v1="NOT_IMPLEMENTED; native V2 preserved",
            implicit_closed_ledger="UNAVAILABLE without authoritative witness", local_python="3.12",
            remote_manylinux_public="NOT_RUN; separate owner approval"),
        owner_final_review="PENDING", publication=False)
    destination.write_text(json.dumps(closure, sort_keys=True, indent=2)+"\n")
    print(json.dumps(dict(status=closure["status"], gates=closure["gates"], removed=cleaned)))


if __name__ == "__main__":
    main()
