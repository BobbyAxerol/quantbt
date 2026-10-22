"""Materialize historical test inputs without rewriting the research freeze."""

from hashlib import sha256
import subprocess

from tools.meta_model_research.admission import PUBLIC, ROOT, read

BASELINE = "3370baf7b9f74441e8523f742b9c81489f5a5adf"


def materialize(root):
    manifest = read(PUBLIC / "ridge_v1_freeze.json")
    assert manifest["source_commit"] == BASELINE
    for field in ("source_sha256", "existing_evidence_sha256"):
        for name, expected in manifest[field].items():
            payload = subprocess.check_output(["git", "show", f"{BASELINE}:{name}"], cwd=ROOT)
            assert sha256(payload).hexdigest() == expected, "historical frozen input drift: " + name
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
    return root
