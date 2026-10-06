"""Independent saved-param application proof, no optimization or learner calls."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter

from tools.qms_e04_study import SYMBOLS, make_endpoint, read_registration
from tools.qms_real_review import PRIVATE_ROOT, dump, load_inputs, private_path, validate_market


def regenerate_positions(data, params, folds, alpha):
    import pandas as pd

    index = data[SYMBOLS[0]].index
    positions = pd.DataFrame(0., index=index, columns=list(SYMBOLS))
    for fold in folds:
        values = params[str(fold.fold_id)]
        for symbol in SYMBOLS:
            history = data[symbol].loc[:fold.test_index[-1]]
            generated = alpha.generate_delta_rsi_signals(history, dict(values))
            positions.loc[fold.test_index, symbol] = generated["pos_weight"].reindex(
                fold.test_index).fillna(0.).astype(float)
    return positions


def verify(output):
    import numpy as np
    import pandas as pd
    import quantbt
    from quantbt import QuantBTEndpoint, WalkForwardEngine
    from quantbt.endpoint import _walkforward_scoring_config

    output = private_path(output)
    target = output/"param-application-proof.json"
    if target.exists():
        raise ValueError("never overwrite a sealed conformance proof")
    record, registered_hash = read_registration(output)
    assert "site-packages" in Path(quantbt.__file__).resolve().parts
    assert quantbt.__version__ == "1.1.2"
    for source, expected in record["source"]["source_sha256"].items():
        installed = Path(quantbt.__file__).resolve().parent/source.removeprefix("src/quantbt/")
        assert sha256(installed.read_bytes()).hexdigest() == expected
    _, alpha, eth, _ = load_inputs(PRIVATE_ROOT)
    assert sha256((output/"btc.csv.gz").read_bytes()).hexdigest() == record["btc_file_sha256"]
    btc = pd.read_csv(output/"btc.csv.gz", index_col="datetime", parse_dates=["datetime"])
    assert btc.index.equals(eth.index) and validate_market(btc) == record["market"]["BTCUSDT"]
    data = dict(zip(SYMBOLS, (eth, btc), strict=True))
    def unused(*args, **kwargs):
        raise AssertionError("fold construction must not evaluate strategy or scorer")

    endpoint = make_endpoint(unused, "off", record)
    folds = WalkForwardEngine(strategy=unused, scorer=unused,
        config=endpoint.config.walkforward_config).build_folds(eth.index)
    assert len(folds) == record["expected_folds"]
    rows = {}
    for arm in record["paired_arms"]:
        sample_path = output/f"{arm}.json"
        sample = json.loads(sample_path.read_text())
        assert sample["registration_sha256"] == registered_hash
        started = perf_counter()
        positions = regenerate_positions(data, sample["params"], folds, alpha)
        financial = QuantBTEndpoint(_walkforward_scoring_config(endpoint.config, "portfolio"))
        result = financial.backtest(data=data, positions=positions, symbols=list(SYMBOLS))
        buffers_path = output/f"{arm}.npz"
        with np.load(buffers_path) as buffers:
            for key in buffers.files:
                np.testing.assert_array_equal(np.asarray(getattr(result, key), dtype=float), buffers[key], err_msg=key)
            checked = list(buffers.files)
        rows[arm] = dict(original_arm_sha256=sha256(sample_path.read_bytes()).hexdigest(),
            original_buffers_sha256=sha256(buffers_path.read_bytes()).hexdigest(),
            checked_buffers=checked, maximum_absolute_difference=0.,
            param_regeneration_and_account_seconds=perf_counter()-started,
            optimizer_calls=0, learner_calls=0, original_account_calls=1,
            signal_sha256=sha256(pd.util.hash_pandas_object(positions, index=True).to_numpy().tobytes()).hexdigest())
    receipt = dict(schema="qms-e04-independent-params-v1", registration_sha256=registered_hash,
        arms=rows, original_account=True, no_observer_or_learning_replay=True,
        costs_separate_from_primary_study=True, publication=False)
    dump(target, receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.study), sort_keys=True))
