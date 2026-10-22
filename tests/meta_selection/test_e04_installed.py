"""E04 installed admission is fail-closed, distinct from economic promotion."""

from copy import deepcopy
import inspect
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from tools.qms_e04_installed import validate_consumer


def receipt():
    return dict(schema="qms-e04-installed-portfolio-v1", core="1.1.2", native="0.4.3",
        cells=[dict(sizing=s, off_shadow_account_exact=True, active_original_witness=True,
                    observer_attempts=22) for s in ("target_units", "%_equity")],
        publication=False, empirical_promotion=False)


def test_e04_t06_installed_proof_requires_both_shared_account_sizing_cells():
    validate_consumer(receipt(), ("1.1.2", "0.4.3"))


@pytest.mark.parametrize("field", ["pair", "duplicate", "missing", "account", "witness", "observer", "promotion", "publish"])
def test_e04_t06_installed_proof_rejects_false_or_incomplete_evidence(field):
    value = deepcopy(receipt())
    if field == "pair": value["native"] = "0.4.2"
    if field == "duplicate": value["cells"][1]["sizing"] = "target_units"
    if field == "missing": value["cells"].pop()
    if field == "account": value["cells"][0]["off_shadow_account_exact"] = False
    if field == "witness": value["cells"][0]["active_original_witness"] = False
    if field == "observer": value["cells"][0]["observer_attempts"] = 0
    if field == "promotion": value["empirical_promotion"] = True
    if field == "publish": value["publication"] = True
    with pytest.raises(ValueError): validate_consumer(value, ("1.1.2", "0.4.3"))


def test_e04_t06_proof_runs_isolated_installed_interpreters_not_source_exports():
    from tools.qms_e04_consumer import _installed_pair, consume
    from tools.qms_e04_installed import qualify
    assert "_installed_pair(quantbt, native," in inspect.getsource(consume)
    assert '"site-packages"' in inspect.getsource(_installed_pair)
    source = inspect.getsource(qualify)
    assert '"-I"' in source and 'environment.pop("PYTHONPATH"' in source
    assert 'verify_pair(proof)' in source


def test_e04_t06_consumer_checks_pair_before_opening_example(monkeypatch):
    from tools import qms_e04_consumer as consumer

    quantbt, native = SimpleNamespace(), SimpleNamespace()
    monkeypatch.setitem(sys.modules, "quantbt", quantbt)
    monkeypatch.setitem(sys.modules, "_quantbt_native", native)
    calls = []

    def reject(actual_core, actual_native, **versions):
        calls.append((actual_core, actual_native, versions))
        raise ValueError("unqualified installed pair")

    monkeypatch.setattr(consumer, "_installed_pair", reject)
    with pytest.raises(ValueError, match="unqualified installed pair"):
        consumer.consume(Path("missing-must-not-be-opened.py"), core_version="1.2.0", native_version="0.4.3")
    assert calls == [(quantbt, native, dict(core_version="1.2.0", native_version="0.4.3"))]
