"""Installed-only original-account liquidation compatibility proof."""

from hashlib import sha256
import importlib.util
import json
from pathlib import Path


def main():
    import _quantbt_native as native
    import quantbt
    import pytest
    root = Path(__file__).resolve().parents[1]
    assert "site-packages" in Path(quantbt.__file__).resolve().parts
    assert quantbt.__version__ == "1.1.2" and native.version() == "0.4.3"
    path = root/"tests/meta_selection/test_g01_metric_compatibility.py"
    spec = importlib.util.spec_from_file_location("installed_g01_tests", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.test_g01_policy_changes_metric_fingerprint_but_default_is_stable()
    for profile in (0, 1, 2):
        module.test_g01_liquidation_score_compact_audit_and_prepared_parity(profile)
    module.test_g01_guard_rejects_an_unsupported_policy_before_execution()
    with pytest.MonkeyPatch.context() as patch:
        module.test_g01_old_extension_cannot_relabel_a_cached_request(patch)
    import _quantbt_native._quantbt_native as extension
    print(json.dumps(dict(schema="qms-g01-installed-metric-v1", checks=6, skipped=0,
        core_origin=str(Path(quantbt.__file__).resolve()), native_origin=str(Path(extension.__file__).resolve()),
        native_sha256=sha256(Path(extension.__file__).read_bytes()).hexdigest(),
        financial_profile_parity=True, sample_policy="legacy_zero_base_v1", publication=False)))


if __name__ == "__main__":
    main()
