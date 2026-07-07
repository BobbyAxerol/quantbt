"""
Phase E arbitrage benchmark smoke runner.

Run from repository root:

    PYTHONPATH=/root/bobby/pool_alpha python3 quantbt/benchmarks/run_arbitrage_phase_e.py
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

import pandas as pd

from quantbt import (
    ArbExecutionPolicy,
    ArbitrageLeg,
    BasisArbitrageSpec,
    ContractType,
    HedgePolicy,
    HedgePolicyKind,
    NativeEventBackend,
    NativeEventConfig,
    NativeVectorizedBackend,
    NativeVectorizedConfig,
    PackageExecutionKind,
    SizingPolicy,
    SizingPolicyKind,
    StatArbPairSpec,
)
from quantbt.core.schema import AccountConfig


@dataclass(frozen=True)
class ArbBenchmarkProfile:
    name: str
    bars: int


PROFILES = {
    "smoke": ArbBenchmarkProfile(name="smoke", bars=512),
    "standard": ArbBenchmarkProfile(name="standard", bars=10_000),
}


def run(profile: ArbBenchmarkProfile = PROFILES["smoke"]) -> list[dict]:
    idx = pd.date_range("2024-01-01", periods=profile.bars, freq="1h", tz="UTC")
    records = []
    for name, runner in (
        ("basis_event", _run_basis_event),
        ("basis_vectorized", _run_basis_vectorized),
        ("stat_event", _run_stat_event),
        ("stat_vectorized", _run_stat_vectorized),
    ):
        started = perf_counter()
        result = runner(idx)
        elapsed = perf_counter() - started
        records.append(
            {
                "name": name,
                "bars": profile.bars,
                "seconds": elapsed,
                "final_equity": float(result.equity.iloc[-1]),
                "engine": result.metadata["engine"],
            }
        )
    return records


def _basis_spec():
    return BasisArbitrageSpec(
        arb_id="BENCH_BASIS",
        legs=(
            ArbitrageLeg(
                symbol="PERP",
                ratio=-1.0,
                role="perp",
                contract_type=ContractType.LINEAR,
                qty_step=0.001,
                min_qty=0.001,
            ),
            ArbitrageLeg(
                symbol="QUARTERLY",
                ratio=1.0,
                role="quarterly",
                contract_type=ContractType.LINEAR,
                qty_step=0.001,
                min_qty=0.001,
            ),
        ),
        hedge_policy=HedgePolicy(kind=HedgePolicyKind.BASE_QTY_EQUAL),
        sizing_policy=SizingPolicy(
            kind=SizingPolicyKind.TARGET_NOTIONAL_TO_BASE_QTY,
            notional=10_000.0,
            reference_symbol="PERP",
        ),
        execution_policy=ArbExecutionPolicy(kind=PackageExecutionKind.ATOMIC_ALL_OR_NONE),
    )


def _stat_spec():
    return StatArbPairSpec(
        arb_id="BENCH_STAT",
        legs=(ArbitrageLeg(symbol="BASE", ratio=1.0), ArbitrageLeg(symbol="HEDGE", ratio=-0.5)),
        hedge_policy=HedgePolicy(kind=HedgePolicyKind.BETA_NEUTRAL),
        sizing_policy=SizingPolicy(kind=SizingPolicyKind.TARGET_GROSS_NOTIONAL, notional=10_000.0),
    )


def _basis_data(idx):
    steps = pd.Series(range(len(idx)), index=idx, dtype=float)
    base = 100.0 + (steps % 31) * 0.1
    return {"PERP": base, "QUARTERLY": base + 2.0}


def _stat_data(idx):
    steps = pd.Series(range(len(idx)), index=idx, dtype=float)
    base = 50.0 + (steps % 17) * 0.2
    return {"BASE": base, "HEDGE": base * 2.0 + 1.0}


def _signal(idx):
    signal = pd.Series(0.0, index=idx)
    signal.iloc[1::200] = 1.0
    signal.iloc[100::200] = 0.0
    return signal.ffill()


def _event_backend():
    return NativeEventBackend(
        NativeEventConfig(account=AccountConfig(initial_capital=100_000.0, leverage=10.0), use_funding=False)
    )


def _vectorized_backend():
    return NativeVectorizedBackend(
        NativeVectorizedConfig(account=AccountConfig(initial_capital=100_000.0, leverage=10.0), use_funding=False)
    )


def _run_basis_event(idx):
    return _event_backend().run_basis_arbitrage(idx, _basis_spec(), _signal(idx), _basis_data(idx))


def _run_basis_vectorized(idx):
    return _vectorized_backend().run_basis_arbitrage(idx, _basis_spec(), _signal(idx), _basis_data(idx))


def _run_stat_event(idx):
    return _event_backend().run_stat_arb_pair_arbitrage(idx, _stat_spec(), _signal(idx), _stat_data(idx))


def _run_stat_vectorized(idx):
    return _vectorized_backend().run_stat_arb_pair_arbitrage(idx, _stat_spec(), _signal(idx), _stat_data(idx))


if __name__ == "__main__":
    for record in run(PROFILES["standard"]):
        print(record)
