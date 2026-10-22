"""Receipt schema fails closed; an artifact install is not economic promotion."""

from copy import deepcopy

import pytest

from tools.qms_e05_installed import validate_consumer


def evidence():
    return dict(schema="qms-e05-installed-package-v1", core="1.1.2", native="0.4.3",
        cells=[dict(kind=k, off_shadow_account_exact=True, original_witness=True,
                    observer_attempts=1) for k in ("basket", "basis", "stat_pair")],
        empirical_promotion=False, publication=False)


def test_e05_t06_installed_requires_every_bounded_cell():
    validate_consumer(evidence(), ("1.1.2", "0.4.3"))


@pytest.mark.parametrize("field", ["pair", "missing", "duplicate", "witness", "account", "observer", "promotion", "publication"])
def test_e05_t06_incomplete_or_false_receipt_is_rejected(field):
    row = deepcopy(evidence())
    if field == "pair": row["native"] = "0.4.2"
    if field == "missing": row["cells"].pop()
    if field == "duplicate": row["cells"][0] = row["cells"][1]
    if field == "witness": row["cells"][0]["original_witness"] = False
    if field == "account": row["cells"][0]["off_shadow_account_exact"] = False
    if field == "observer": row["cells"][0]["observer_attempts"] = 0
    if field == "promotion": row["empirical_promotion"] = True
    if field == "publication": row["publication"] = True
    with pytest.raises(ValueError): validate_consumer(row, ("1.1.2", "0.4.3"))
