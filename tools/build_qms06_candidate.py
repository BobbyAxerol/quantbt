"""Build the isolated prepared-witness candidate; leave installed 0.4.2 intact."""

from pathlib import Path

from tools.build_qms04_candidate import ROOT, build, load_candidate


CANDIDATE = "0.4.3.dev2"
OUTPUT = ROOT / ".maturin/qms06"


def load(path):
    module = load_candidate(Path(path), candidate=CANDIDATE)
    if module.QMS_PREPARED_METRIC_SUPPORT_V1 != "same-pass-ddof1-daily-first-mark-v1":
        raise ValueError("prepared metric witness ABI mismatch")
    return module


if __name__ == "__main__":
    extension, proof = build(
        OUTPUT,
        candidate=CANDIDATE,
        features="qms-numeric-candidate,qms-prepared-witness-candidate",
    )
    print(proof)
    print(f"QMS06_NATIVE_EXTENSION={extension}")
