"""Current-source local qualification, independently retained from QMS08 seals."""

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

from tools.qms08_gate import CHECKS, TEST_IDS, verify_pair

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/local/qms-real-review/debt-closure"
LANES = ROOT / ".maturin/qms08/local-closure-v1"


def qualify():
    import sys

    OUTPUT.mkdir(parents=True, exist_ok=True)
    cases = list(ET.parse(OUTPUT / "regression.xml").getroot().iter("testcase"))
    assert cases and not any(c.find(k) is not None for c in cases for k in ("failure", "error"))
    required = {test: [c for c in cases if c.get("name", "").startswith(
        "test_" + test.lower().replace("-", "_") + "_")] for test in TEST_IDS}
    assert all(required.values()) and not any(c.find("skipped") is not None
                                               for rows in required.values() for c in rows)
    consumers = {}
    for version in ("311", "312", "313"):
        lane = LANES / ("cp" + version)
        verify_pair(json.loads((lane / "proof.json").read_text()))
        command = [str(lane / "pair/bin/python"), "-I", str(ROOT / "tools/qms_local_consumer.py")]
        process = subprocess.run(command, cwd=lane, text=True, capture_output=True)
        log = OUTPUT / ("installed-w3-cp" + version + ".log")
        log.write_text("$ " + " ".join(command) + "\n" + process.stdout + process.stderr)
        if process.returncode:
            raise ValueError(f"installed W3 qualification failed; see {log}")
        record = json.loads(process.stdout.splitlines()[-1])
        assert record["off_shadow_exact"] and record["same_pass"] and record["observer_failures"] == 0
        consumers[version] = dict(consumer=record, log_sha256=sha256(log.read_bytes()).hexdigest(),
            artifact_proof_sha256=sha256((lane / "proof.json").read_bytes()).hexdigest())
    checks = {}
    for name in CHECKS:
        command = [sys.executable, str(ROOT / "tools" / name)]
        if name.startswith("generate_") or name == "check_canonical_source_layout.py":
            command.append("--check")
        process = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        log = OUTPUT / (name + ".log")
        log.write_text("$ " + " ".join(command) + "\n" + process.stdout + process.stderr)
        if process.returncode:
            raise ValueError(f"current source/document gate failed; see {log}")
        checks[name] = sha256(log.read_bytes()).hexdigest()
    result = dict(schema="qms-local-installed-gate-v1", required_test_ids=len(required),
        regression_passed=sum(c.find("skipped") is None for c in cases),
        explicit_posix_skips=sum(c.find("skipped") is not None for c in cases),
        regression_sha256=sha256((OUTPUT / "regression.xml").read_bytes()).hexdigest(),
        installed_consumers=consumers, current_checks=checks, remote_qualified=False,
        release_authorized=False)
    (OUTPUT / "qualification.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    proof = qualify()
    print(json.dumps(dict(required_ids=proof["required_test_ids"],
        passed=proof["regression_passed"], skips=proof["explicit_posix_skips"],
        interpreters=list(proof["installed_consumers"]), checks=list(proof["current_checks"]))))
