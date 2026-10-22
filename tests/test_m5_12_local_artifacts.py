"""Local qualification cannot borrow old installed or financial-invariance claims."""
from copy import deepcopy
from hashlib import sha256
import json

import pytest

from tools import m5_12_local_artifacts as local


def case(tmp_path,monkeypatch):
    lane=tmp_path/".maturin/qms08/current/cp312"
    (lane/"dist").mkdir(parents=True)
    refs=[]
    for name in ("quantbt_engine-1.1.2.whl","quantbt_engine-1.1.2.tar.gz","quantbt_native-0.4.3.whl"):
        path=lane/"dist"/name
        path.write_bytes(b"SYNTHETIC_ARCHIVE_NOT_EXECUTED")
        refs.append(dict(path=str(path.relative_to(tmp_path)),sha256=local.digest(path),bytes=path.stat().st_size))
    log=lane/"core-build.log"
    log.write_text("synthetic command receipt")
    monkeypatch.setattr(local,"ROOT",tmp_path)
    monkeypatch.setattr(local,"declared_pair",lambda:("1.1.2","0.4.3"))
    monkeypatch.setattr(local,"verify_current_source",lambda:dict(current_source_qualified=True,financial_source_changed=True))
    monkeypatch.setattr(local,"native_reuse",lambda path:dict(policy="EXACT_TEST_NATIVE"))
    for name in local.PACKAGING_INPUTS:
        (tmp_path/name).write_text("synthetic packaging input")
    return dict(schema=local.SCHEMA,core="1.1.2",native="0.4.3",lane=str(lane),
        source=local.verify_current_source(),source_differences={},artifact_refs=refs,
        packaging_inputs={name:local.digest(tmp_path/name) for name in local.PACKAGING_INPUTS},
        logs={str(log.relative_to(tmp_path)):local.digest(log)},native_reuse=dict(policy="EXACT_TEST_NATIVE"),
        publication=False,release_authorized=False)


@pytest.mark.parametrize("defect",[None,"schema","source","packaging","adaptation","promote","pair","path","hash","size","missing","reuse","logs"])
def test_local_provenance_fails_closed(tmp_path,monkeypatch,defect):
    proof=case(tmp_path,monkeypatch)
    if defect=="schema":proof["schema"]="qms08-installed-candidate-v1"
    elif defect=="source":proof["source"]["financial_source_changed"]=False
    elif defect=="packaging":proof["packaging_inputs"]["MANIFEST.in"]="0"*64
    elif defect=="adaptation":proof["source_differences"]={"unapproved":"changed"}
    elif defect=="promote":proof["publication"]=True
    elif defect=="pair":proof["native"]="0.4.2"
    elif defect=="path":proof["lane"]=str(tmp_path/"elsewhere")
    elif defect=="hash":proof["artifact_refs"][0]["sha256"]="0"*64
    elif defect=="size":proof["artifact_refs"][0]["bytes"]+=1
    elif defect=="missing":proof["artifact_refs"].pop()
    elif defect=="reuse":proof["native_reuse"]={}
    elif defect=="logs":proof["logs"]={}
    if defect:
        with pytest.raises(ValueError):local.verify_local_artifacts(proof)
    else:assert local.verify_local_artifacts(proof)


def test_reuse_requires_exact_sealed_receipt_and_native_wheel(tmp_path,monkeypatch):
    receipt=tmp_path/local.ACC_RECEIPT
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps(dict(native=dict(wheel_sha256="0"*64))))
    monkeypatch.setattr(local,"ROOT",tmp_path)
    wheel=tmp_path/"native.whl"
    wheel.write_bytes(b"different artifact")
    with pytest.raises(ValueError,match="receipt changed"):local.native_reuse(wheel)
    monkeypatch.setattr(local,"ACC_RECEIPT_SHA256",local.digest(receipt))
    with pytest.raises(ValueError,match="actually executed"):local.native_reuse(wheel)


def test_registered_non_python_resources_are_manifest_included():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    manifest=(root/"MANIFEST.in").read_text()
    assert "include src/quantbt/benchmarks/README.md" in manifest
    assert "include src/quantbt/benchmarks/phase7_thresholds.json" in manifest
