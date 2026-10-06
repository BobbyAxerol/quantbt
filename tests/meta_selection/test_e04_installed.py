"""E04 installed admission is fail-closed, distinct from economic promotion."""

from copy import deepcopy
import inspect

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
    from tools.qms_e04_consumer import consume
    from tools.qms_e04_installed import qualify
    assert '"site-packages"' in inspect.getsource(consume)
    source = inspect.getsource(qualify)
    assert '"-I"' in source and 'environment.pop("PYTHONPATH"' in source
    assert 'verify_pair(proof)' in source
