import numpy as np

from tools.mode5_economics import DailyAccount, EconomicProtocol

DAY = 86_400_000_000_000


def path(values, *, year=2021, vector="baseline", **overrides):
    start = np.datetime64(str(year)+"-01-01", "ns").astype(np.int64)
    options = dict(execution_id=f"actual-{year}-{vector}", economic_contract="same-net-costs-v1",
        params_digest=vector, fills=40, campaigns=30, accounting_verified=True,
        terminal_policy="original-flat-v1", role="synthetic")
    options.update(overrides)
    return DailyAccount.from_arrays(start+np.arange(len(values))*DAY, values, **options)


def protocol(**overrides):
    return EconomicProtocol("public-synthetic-oracle-not-real-study", **{**dict(
        development_days=64, forward_days=64, minimum_fills=1, minimum_campaigns=1,
        minimum_origins=1, block_days=7, draws=64, family_size=5), **overrides})


def returns(days=365, mean=.001):
    return mean+.004*np.sin(np.arange(days)*.31)+.001*np.cos(np.arange(days)*.83)
