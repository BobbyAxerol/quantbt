"""Exact generated-API metadata refresh; never normalize financial source."""

from hashlib import sha256


NAME = "contracts/generated_public_api_inventory.json"
BEFORE_SHA256 = "522e7ff87b95e5dba73369f4a0b7395e094d271443c72a31e05be3377a709103"
AFTER_SHA256 = "dc348140142390a81f078d4dcf9562ad032d4a60f99e106e7d63b041f15c439f"
BASELINE_COMMIT = "4236985893342a56868c4cfe10f0bbe7e0017c57"


def without_inventory_refresh(source, name, guard):
    if name != NAME or sha256(source).hexdigest() != AFTER_SHA256:
        return source
    return guard._blob(BASELINE_COMMIT, NAME, BEFORE_SHA256)


def current_inventory_amendment(expected, root):
    """Admit one exact metadata delta while keeping the ACC runtime lock."""
    assert expected[NAME] == BEFORE_SHA256, "API inventory amendment baseline differs"
    raw = (root / NAME).read_bytes()
    if sha256(raw).hexdigest() == BEFORE_SHA256:
        return dict(expected), []
    assert sha256(raw).hexdigest() == AFTER_SHA256, "unreviewed API inventory bytes"
    from tools.generate_public_api_inventory import generated_outputs
    outputs = generated_outputs()
    assert raw == outputs[root / NAME].encode(), "API inventory is not generated from current exports"
    updated = dict(expected, **{NAME: AFTER_SHA256})
    return updated, [dict(path=NAME, before_sha256=BEFORE_SHA256,
                          after_sha256=AFTER_SHA256, financial_source_changed=False)]
