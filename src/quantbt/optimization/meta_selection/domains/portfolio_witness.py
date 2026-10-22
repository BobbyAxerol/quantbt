"""Reuse original per-symbol prefix witnesses in the existing run-owned cache."""

from dataclasses import replace
from hashlib import sha256

import pandas as pd

from ..common import MetaRecordError, digest
from ..witness import PreparedMetricWitness
from .portfolio_contract import funding_for, validate_portfolio_market


def portfolio_market_signature(data, index, *, config):
    from ..observer import market_signature

    symbols = tuple(config.symbols or ())
    return digest({"portfolio_market_v1": [(s, market_signature(data[s], index,
        config=replace(config, funding_rate=funding_for(config, s)))) for s in symbols]})


def funding_signature(config, symbols):
    return digest({s: {"dtype": str(r.dtype), "rows_sha256": sha256(
        pd.util.hash_pandas_object(r, index=True).to_numpy().tobytes()).hexdigest()}
        if isinstance(r := funding_for(config, s), pd.Series) else float(r) for s in symbols})


class PortfolioMetricWitness(PreparedMetricWitness):
    def __init__(self, data, *, config, max_entries=256, max_bytes=8_000_000):
        self.universe = tuple(config.symbols or ())
        if not self.universe:
            raise MetaRecordError("META_DOMAIN_INPUT_MISMATCH: witness requires fixed portfolio universe")
        validate_portfolio_market(data, data[self.universe[0]].index, self.universe)
        first = self.universe[0]
        super().__init__(data[first], config=replace(config, funding_rate=funding_for(config, first)),
                         max_entries=max_entries, max_bytes=max_bytes)
        self.source, self.owner_config = data, config
        # Child witnesses retain immutable row hashes, not another result/cache.
        self.children = {s: PreparedMetricWitness(data[s],
            config=replace(config, funding_rate=funding_for(config, s)),
            max_entries=0, max_bytes=0) for s in self.universe[1:]}
        self.funding_identity = funding_signature(config, self.universe)

    def market_signature(self, data, index):
        self._check_source_shape(data)
        key = ("portfolio_market", tuple(len(data[s]) for s in self.universe), self.calendar_key(index))
        owned = all((self if s == self.universe[0] else self.children[s])._owned_prefix(data[s])
                    for s in self.universe)
        if not owned:
            self.stats["reference_fallbacks"] += 1
            return portfolio_market_signature(data, index, config=self.owner_config)

        def create():
            return digest({"portfolio_market_v1": [(s,
                PreparedMetricWitness.market_signature(self if s == self.universe[0] else self.children[s],
                                                       data[s], index)) for s in self.universe]})

        value, hit = self._get(key, create)
        self.stats["market_hits" if hit else "market_misses"] += 1
        return value

    def _check_source_shape(self, data):
        if self.closed:
            raise MetaRecordError("META_WITNESS_CLOSED")
        if set(data) != set(self.universe):
            raise MetaRecordError("META_DOMAIN_INPUT_MISMATCH: portfolio witness universe changed")

    def validate_source(self):
        if self.closed:
            return
        self._check_source_shape(self.source)
        if any(self.source[s] is not (self.frame if s == self.universe[0] else self.children[s].frame)
               for s in self.universe):
            raise MetaRecordError("META_WITNESS_SOURCE_MUTATED")
        if funding_signature(self.owner_config, self.universe) != self.funding_identity:
            raise MetaRecordError("META_WITNESS_FUNDING_MUTATED")
        super().validate_source()
        for child in self.children.values():
            child.validate_source()

    @property
    def metadata(self):
        return {**super().metadata, "schema": "qms-portfolio-prepared-witness-v1",
                "universe": self.universe, "financial_state_cached": False,
                "owned_row_hash_bytes": self.rows.nbytes + sum(c.rows.nbytes for c in self.children.values())}

    def close(self):
        for child in self.children.values():
            child.close()
        self.children.clear()
        self.source = self.owner_config = None
        super().close()
