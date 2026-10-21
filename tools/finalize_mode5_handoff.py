"""Cold local receipt and exact owned scratch cleanup for M5-11.14 only."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

from quantbt.diagnostics import CalibrationRunReport, Mode5RunPack
from quantbt.diagnostics.calibration.verification import policy_mismatches
from quantbt.mode5.artifacts import write_json
from quantbt.mode5.dossier.records import Record
from tools.mode5_research.handoff_readback import readback
from tools.mode5_research.handoff_readback_report import render


LANE = Path("upgrade/private/mode5_upgrade_v1/m5-11-14/attempt-01")


def pin(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("regular protected file required: " + str(path))
    raw = path.read_bytes()
    return dict(path=str(path), bytes=len(raw), sha256=sha256(raw).hexdigest())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cleanup", action="store_true", help="remove only the registered inactive scratch root")
    args = parser.parse_args(argv)
    root = Path.cwd()
    lane = root / LANE
    if not (root / "AGENTS.md").is_file() or lane.is_symlink():
        raise ValueError("repository root and original regular phase lane required")
    current = readback(root)
    previous = Record.of(json.loads((lane / "retained-readback.json").read_text()))
    if previous != current:
        raise ValueError("retained evidence changed since source-bound cold readback")
    if not args.cleanup:
        with (lane / "retained-readback-final.md").open("x") as stream:
            stream.write(render(current, private=True))
        cases = []
        for directory, pack_path, report_path, identity in (
            ("synthetic-02", "no-archive/run-pack/run_pack.json", "no-archive-initial-result.json", None),
            ("synthetic-02", "archive/run-pack/run_pack.json", "archive-initial-result.json", None),
            ("synthetic-final", "run-pack/run_pack.json", "actual-report.json", None),
        ):
            base = lane / directory
            report = CalibrationRunReport(Record.of(json.loads((base / report_path).read_text())))
            pack = Mode5RunPack.read(base / pack_path, expected_identity=identity or report.record.data["pack_id"])
            if (report.record.data["status"] != "RECONCILED_RETAINED_RUN"
                    or policy_mismatches(pack, report.record.data["actual_decision"]["runtime"])):
                raise ValueError("source-final retained report no longer reconciles")
            cases.append(dict(pack=pin(base / pack_path), report=pin(base / report_path),
                status="COLD_RELOAD_POLICY_AGREEMENT_NOT_NEW_EXECUTION"))
        original, final = (CalibrationRunReport(Record.of(json.loads(path.read_text()))).record.data["actual_decision"]["runtime"]
            for path in (lane / "synthetic-02/no-archive-initial-result.json", lane / "synthetic-final/actual-report.json"))
        for old, new in zip(original["trial_ledger"][:2], final["trial_ledger"], strict=True):
            if any(old[k] != new[k] for k in ("trial_id", "state", "candidate_id", "objective", "whole_observation")):
                raise ValueError("original deterministic trial prefix changed")
        registration = json.loads((lane / "registration.json").read_text())
        for path, expected in registration["protected_files"].items():
            if pin(root / path)["sha256"] != expected:
                raise ValueError("original financial owner changed: " + path)
        diff = subprocess.check_output(["git", "diff", "cec8e49", "--", "src/quantbt/mode5", "src/quantbt/optimization", "src/quantbt/endpoint.py"])
        if diff:
            raise ValueError("original scientific/runtime owners changed")
        suite = ET.parse(lane / "source-final-05.xml").getroot().find("testsuite")
        if suite is None or any(int(suite.get(k, "0")) for k in ("errors", "failures", "skipped")):
            raise ValueError("final unique source regression suite is not clean")
        work = json.loads((lane / "synthetic-final/qualification.json").read_text())["work"]
        if work != dict(proposal_slots=14, financial_invocations=23, private_alpha_optimizers=0, model_fits=0):
            raise ValueError("cumulative work differs from retained controls")
        receipt = dict(schema="quantbt.m5_11_14.cold_exit_verification.v1",
            status="PASS_LOCAL_DECLARED_SCOPE_NOT_PARENT_ACCEPTANCE", work=work,
            unique_final_tests=int(suite.get("tests")), final_test_seconds=float(suite.get("time")),
            original_trial_prefix="EXACT_FIRST_TWO_OBSERVATIONS_AND_OBJECTIVES", retained_cases=cases,
            sources=current.data["sources"], readback_id=current.identity,
            scientific_and_financial_owner_diff="EMPTY_AGAINST_CEC8E49", parent_accepted=False,
            m5_12_started=False, remote_or_release=False)
        write_json(lane / "verification.json", receipt)
        print(json.dumps(receipt, indent=2))
        return
    if not (lane / "verification.json").is_file():
        raise ValueError("terminal cold verification required before cleanup")
    scratch = lane / "scratch"
    if scratch.is_symlink() or scratch.resolve() != scratch or not scratch.is_dir():
        raise ValueError("exact original inactive scratch directory required")
    subprocess.run(["git", "check-ignore", "-q", str(LANE / "scratch")], check=True)
    protected = [pin(p) for p in lane.rglob("*") if p.is_file() and scratch not in p.parents]
    protected += [pin(root / s["path"]) for s in current.data["sources"]]
    protected += [pin(root / p) for p in (
        "upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md",
        "upgrade/QUANTBT_MODE4_MODE5_CROSS_MODE_RESEARCH_GUIDE_V1.md",
        "upgrade/QUANTBT_MODE4_META_LEARNER_RESEARCH_GUIDE_V1.md",
        *json.loads((lane / "registration.json").read_text())["protected_files"],
    )]
    protected += [pin(p) for p in (root / "upgrade/alphas").glob("*.py")]
    allocated = sum(p.lstat().st_blocks * 512 for p in (scratch, *scratch.rglob("*")))
    if allocated > 64 * 1024**2:
        raise ValueError("registered allocated scratch cap exceeded; retain and report")
    before = shutil.disk_usage(root).free
    shutil.rmtree(scratch)
    after = shutil.disk_usage(root).free
    for value in protected:
        if pin(Path(value["path"])) != value:
            raise ValueError("protected input changed during cleanup")
    st = root.stat().st_dev
    receipt = dict(schema="quantbt.m5_11_14.cleanup.v1", status="PASS_EXACT_INACTIVE_SCRATCH_ONLY",
        removed_path=str(LANE / "scratch"), allocated_scratch_bytes=allocated,
        filesystem_available_before=before, filesystem_available_after=after,
        observed_available_delta=after-before, protected_files=len(protected), protected=protected,
        filesystem_device=st, host_process_visibility="Sandbox only; all registered tool sessions terminal; no service controlled",
        no_environment_or_artifact_removal=True)
    write_json(lane / "cleanup.json", receipt)
    print(json.dumps({k: v for k, v in receipt.items() if k != "protected"}, indent=2))


if __name__ == "__main__":
    main()
