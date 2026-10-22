"""Exact generated-API metadata refresh; never normalize financial source."""

from hashlib import sha256


NAME = "contracts/generated_public_api_inventory.json"
BEFORE_SHA256 = "522e7ff87b95e5dba73369f4a0b7395e094d271443c72a31e05be3377a709103"
AFTER_SHA256 = "dc348140142390a81f078d4dcf9562ad032d4a60f99e106e7d63b041f15c439f"
BASELINE_COMMIT = "4236985893342a56868c4cfe10f0bbe7e0017c57"
EXPORT_NAME = "src/quantbt/__init__.py"
EXPORT_COMMIT = "3370baf7b9f74441e8523f742b9c81489f5a5adf"
EXPORT_SHA256 = "e9a429f600a09de4899e66c682e1f44051c6ce0506f9c5bb8a6fa02824fcd1c3"
EXPORT_PARENT = "f57aef78543cd4784c83e3c95f05be4434387f05"
EXPORT_PARENT_SHA256 = "c853c2c3b244ebd99fff9a45128656988c2dcdbbd792e90f21a69a756751326d"


def without_inventory_refresh(source, name, guard):
    if name != NAME or sha256(source).hexdigest() != AFTER_SHA256:
        return source
    return guard._blob(BASELINE_COMMIT, NAME, BEFORE_SHA256)


def without_diagnostic_root_exports(source, name, guard):
    """Reconcile the already-approved root exports for legacy reporting guards."""
    if name != EXPORT_NAME or sha256(source).hexdigest() != EXPORT_SHA256:
        return source
    assert source == guard._blob(EXPORT_COMMIT, name, EXPORT_SHA256), "diagnostic export committed bytes differ"
    return guard._blob(EXPORT_PARENT, name, EXPORT_PARENT_SHA256)


def current_inventory_amendment(expected, root):
    """Admit one exact metadata delta while keeping the ACC runtime lock."""
    assert expected[NAME] == BEFORE_SHA256, "API inventory amendment baseline differs"
    raw = (root / NAME).read_bytes()
    actual = raw
    from tools import portfolio_repair_source_guard as guard
    from tools.m5_12_release120_amendment import without_release120
    raw = without_release120(raw, NAME, guard)
    assert sha256(raw).hexdigest() == AFTER_SHA256, "unreviewed API inventory bytes"
    from tools.generate_public_api_inventory import generated_outputs
    outputs = generated_outputs()
    assert actual == outputs[root / NAME].encode(), "API inventory is not generated from current exports"
    updated = dict(expected, **{NAME: AFTER_SHA256})
    return updated, [dict(path=NAME, before_sha256=BEFORE_SHA256,
                          after_sha256=AFTER_SHA256, financial_source_changed=False)]
