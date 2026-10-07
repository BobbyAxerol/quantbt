"""Registered local regression shards with immutable logs and exact skip gates."""

import argparse
import os
import subprocess
import time
import xml.etree.ElementTree as ET

from tools.qms08_package import ROOT, file_hash
from tools.qms_pre06_contract import LANE, write_once
from tools.qms_pre05_qualification import REGISTERED_NA, passed_cases

PYTHON = ROOT / ".maturin/qms08/g01-package-v1/consumer/bin/python"
EXTENSION = PYTHON.parent.parent / "lib/python3.12/site-packages/_quantbt_native/_quantbt_native.cpython-312-x86_64-linux-gnu.so"
EXTERNAL = (
    "test_optimization_samplers", "test_walkforward_phase1", "test_phase49a_walkforward_schedules",
    "test_phase49b_wfo_performance", "test_phase64_wfo_correctness", "test_phase74_public_wfo_native",
    "test_phase76_reactive_wfo", "test_perf_05_wfo_evaluation_reuse", "test_perf_08_wfo_preparation",
)
ACCOUNT = (
    "test_metrics_intraday_scope", "test_phase31b_market_tape_intrabar_oracle",
    "test_phase31c_intrabar_kernel", "test_phase31h_intrabar_session_reference",
    "test_phase31_merge_blockers", "test_phase30b_native_event_lifecycle_kernel",
    "test_phase30c_native_event_endpoint_lifecycle", "native_event/test_reactive_accounting_parity",
    "native_event/test_reactive_lifecycle_parity", "test_phase60_execution_metrics_native_result",
    "test_phase59_linear_accounting_fill_replay", "test_phase67_rust_shared_portfolio",
    "test_phase68_rust_package_authority", "test_phase69_rust_intrabar_authority",
)
PLOT = "test_walkforward_result_quick_plot_accepts_default_oos_scope"


def commands():
    return {
        "meta": [PYTHON, "-m", "pytest", "-q", "tests/meta_selection",
                 "--ignore=tests/meta_selection/test_g01_study_replay.py"],
        "wfo": [PYTHON, "-m", "pytest", "-q", *("tests/"+n+".py" for n in EXTERNAL), "-k", "not "+PLOT],
        "account": [PYTHON, "-m", "pytest", "-q", *("tests/"+n+".py" for n in ACCOUNT)],
        "plot": [ROOT / ".venv/bin/python", "-m", "pytest", "-q",
                 "tests/test_walkforward_phase1.py::"+PLOT],
    }


def run():
    plan = commands()
    if not (LANE / "regression-registration.json").exists():
        write_once(LANE / "regression-registration.json", dict(
            schema="qms-pre06-regression-registration-v1", commands={k: list(map(str, v)) for k, v in plan.items()},
            ignored_private_study="test_g01_study_replay.py", admitted_na=sorted(REGISTERED_NA),
            plotting_is_separate=True, numeric_threads=1))
    union, seen_na, records = set(), set(), {}
    for label, command in plan.items():
        xml, log = LANE / (label+"-regression.xml"), LANE / (label+"-regression.log")
        if xml.exists() or log.exists():
            raise ValueError("refuse to overwrite regression; use explicit retained rerun")
        env = dict(os.environ, PYTHONPATH="src:.", OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
                   MKL_NUM_THREADS="1", NUMBA_NUM_THREADS="1", MPLBACKEND="Agg",
                   QMS06_NATIVE_EXTENSION=str(EXTENSION), QMS06_NATIVE_VERSION="0.4.3")
        start = time.perf_counter()
        with log.open("x") as stream:
            stream.write("$ "+" ".join(map(str, command))+"\n")
            stream.flush()
            completed = subprocess.run([*map(str, command), "--junitxml="+str(xml)],
                                       cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT)
        records[label] = dict(returncode=completed.returncode, elapsed_seconds=time.perf_counter()-start,
                              xml_sha256=file_hash(xml) if xml.exists() else None, log_sha256=file_hash(log))
        write_once(LANE / (label+"-regression-result.json"), records[label])
        if completed.returncode:
            raise ValueError(f"regression failed; preserve and inspect {log}")
        union.update(passed_cases(xml, admitted_na=REGISTERED_NA))
        seen_na.update((c.get("classname"), c.get("name")) for c in ET.parse(xml).iter("testcase")
                       if c.find("skipped") is not None)
        print(f"{label}: PASS; cumulative distinct cases {len(union)}", flush=True)
    if seen_na != REGISTERED_NA:
        raise ValueError("unexpected/missing registered N/A coverage")
    write_once(LANE / "regression-proof.json", dict(schema="qms-pre06-regression-v1",
        status="PASS_AFFECTED_SOURCE_REGRESSION", distinct_pass=len(union),
        admitted_na=sorted(seen_na), cases=sorted(union), shards=records, publication=False))


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()
