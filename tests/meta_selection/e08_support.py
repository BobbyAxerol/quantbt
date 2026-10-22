"""Generic v3 mature proof uses existing E07 owners, never a second engine."""

from dataclasses import replace

from quantbt import QuantBTEndpoint
from tests.meta_selection import e07_support as e07

V3_CASES = (("event_driven", "python"), ("event_driven", "rust"))


def run(case, mode="active", **kwargs):
    route, bt, context, data, call = e07.prepare_run(case, mode, **kwargs)
    financial = replace(bt.config.wfo_execution_config, execution_contract="event_lifecycle_v3_next_open")
    bt = QuantBTEndpoint(replace(bt.config, wfo_execution_config=financial))
    return e07.execute((route, bt, context, data, call))
