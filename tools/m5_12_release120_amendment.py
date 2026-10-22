"""Exact reporting-cost and release-metadata amendment, not an artifact proof."""

import ast
from hashlib import sha256
import json


MANIFEST_NAME = "docs/maintenance/evidence/m5-12-release120-source-amendment.json"
MANIFEST_SHA256 = "5af75e58db354688b5c9b939316cf01fb4d6856c6583180177919a85d1d8dcdc"
BASELINE_COMMIT = "bf3f919550a82ac97d6c4c81073a52880d5e3331"
SOURCE_COMMIT = "67f75bfbbf06932235e30d9d5ebebb0f7cb0aa0f"
REPORT_PATHS = frozenset(("src/quantbt/metrics/report_contracts.py",
    "src/quantbt/metrics/reporting/account.py", "src/quantbt/metrics/reporting/drawdown.py",
    "src/quantbt/metrics/reporting/ledger.py"))
SOURCE_PATHS = REPORT_PATHS | frozenset(("pyproject.toml", "uv.lock", "src/quantbt/__init__.py",
    "src/quantbt/core/generated_product_contracts.py",
    "rust/crates/quantbt-domain/src/generated_product_contracts.rs",
    "contracts/native_event_product_registry.json", "contracts/generated_product_manifest.json",
    "contracts/generated_public_api_inventory.json"))


def manifest(guard):
    assert len(MANIFEST_SHA256) == 64 and len(SOURCE_COMMIT) == 40, "release120 amendment must be sealed"
    path = guard.ROOT/MANIFEST_NAME
    assert path.is_file() and not path.is_symlink(), "regular release120 manifest required"
    raw = path.read_bytes()
    assert sha256(raw).hexdigest() == MANIFEST_SHA256, "release120 manifest digest"
    value = json.loads(raw)
    assert value["schema"] == "quantbt.m5_12.release120_source.v1"
    assert (value["baseline_commit"], value["source_commit"]) == (BASELINE_COMMIT, SOURCE_COMMIT)
    assert set(value["sources"]) == SOURCE_PATHS, "release120 exact reviewed scope"
    assert value["core"] == "1.2.0" and value["native"] == "0.4.3"
    assert value["source_only"] is True
    for key in ("native_artifacts_qualified", "publication", "historical_financial_invariance_claim_reissued",
                "financial_kernel_changed", "metric_formulas_changed"):
        assert value[key] is False, "release120 cannot expand claims: " + key
    return value


def without_release120(source, name, guard):
    entry = manifest(guard)["sources"].get(name)
    if entry is None or sha256(source).hexdigest() != entry["after_sha256"]:
        return source
    assert source == guard._blob(SOURCE_COMMIT, name, entry["after_sha256"])
    return guard._blob(BASELINE_COMMIT, name, entry["before_sha256"])


def _report_scope(before, after, name):
    old, new = ast.parse(before), ast.parse(after)
    methods = {
        "src/quantbt/metrics/reporting/account.py": {"_period_scan"},
        "src/quantbt/metrics/reporting/drawdown.py": {"_scan"},
        "src/quantbt/metrics/reporting/ledger.py": {"reduce_ledger"},
    }
    if name in methods:
        allowed = methods[name]
        for tree in (old,new):
            tree.body = [node for node in tree.body if not isinstance(node,ast.FunctionDef) or node.name not in allowed]
        if name.endswith("ledger.py"):
            new.body = [node for node in new.body if not (isinstance(node,ast.ImportFrom)
                and node.module == "collections" and len(node.names) == 1 and node.names[0].name == "Counter")]
    else:
        for tree in (old,new):
            for node in tree.body:
                if isinstance(node,ast.ClassDef) and node.name in {"ReportingContractV1", "ReportingMetricV1"}:
                    node.body = [item for item in node.body if not (isinstance(item,ast.FunctionDef) and item.name == "to_metadata")]
        new.body = [node for node in new.body if not (isinstance(node,ast.FunctionDef) and node.name == "_scalar_metadata")
            and not (isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id == "_SCALAR_METADATA_TYPES" for t in node.targets))]
    assert ast.dump(old,include_attributes=False) == ast.dump(new,include_attributes=False), "reporting scope drift: " + name


def apply_release120(guard, expected, scopes):
    value = manifest(guard)
    assert scopes == value["scopes"]
    before = guard._committed_source_hashes(BASELINE_COMMIT, scopes)
    assert expected == before, "release120 must follow exact snapshot baseline"
    after = guard._committed_source_hashes(SOURCE_COMMIT, scopes)
    assert len(after) == len(before) == 466 and set(after) == set(before), "release120 source inventory drift"
    changed = guard._verify_repair_delta(value,before,after,value)
    assert set(changed) == SOURCE_PATHS
    blobs = {name: (guard._blob(BASELINE_COMMIT,name,entry["before_sha256"]),
                    guard._blob(SOURCE_COMMIT,name,entry["after_sha256"])) for name,entry in value["sources"].items()}
    for name in REPORT_PATHS:
        _report_scope(*blobs[name],name)
    for name, old_token, new_token in (
        ("pyproject.toml", b'version = "1.1.2"', b'version = "1.2.0"'),
        ("src/quantbt/__init__.py", b'__version__ = "1.1.2"', b'__version__ = "1.2.0"'),
        ("uv.lock", b'name = "quantbt-engine"\nversion = "1.1.2"', b'name = "quantbt-engine"\nversion = "1.2.0"')):
        old,new = blobs[name]
        assert old.count(old_token) == 1 and old.replace(old_token,new_token,1) == new, "release metadata drift: " + name
    registry = "contracts/native_event_product_registry.json"
    old_registry,new_registry = [json.loads(content) for content in blobs[registry]]
    assert new_registry["versions"]["core_package"]["version"] == "1.2.0"
    new_registry["versions"]["core_package"]["version"] = "1.1.2"
    assert len(new_registry["compatibility"]) == len(old_registry["compatibility"]) == 1
    assert new_registry["compatibility"][0]["core_version"] == "1.2.0"
    new_registry["compatibility"][0]["core_version"] = "1.1.2"
    assert new_registry == old_registry, "product registry semantics drift"
    fingerprint = lambda raw: sha256(json.dumps(json.loads(raw),sort_keys=True,separators=(",",":"),ensure_ascii=True).encode()).hexdigest().encode()
    old_fp,new_fp = map(fingerprint,blobs[registry])
    for name in ("src/quantbt/core/generated_product_contracts.py", "rust/crates/quantbt-domain/src/generated_product_contracts.rs"):
        old,new = blobs[name]
        assert new.replace(new_fp,old_fp).replace(b'1.2.0',b'1.1.2') == old, "generated product must change metadata only: " + name
    return value, after, changed
