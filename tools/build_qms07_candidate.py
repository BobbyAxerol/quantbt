"""Isolated numeric optimization candidate; installed native remains unchanged."""

from tools.build_qms04_candidate import ROOT, build, load_candidate

CANDIDATE = "0.4.3.dev3"
OUTPUT = ROOT / ".maturin/qms07"


def load(path):
    return load_candidate(path, candidate=CANDIDATE)


if __name__ == "__main__":
    extension, receipt = build(
        OUTPUT,
        candidate=CANDIDATE,
        features="qms-numeric-candidate,qms-prepared-witness-candidate",
    )
    print(receipt)
    print(f"QMS07_NATIVE_EXTENSION={extension}")
