"""R3B original-pass witness primitive; no sampler or public selection activation."""

from ...backends._native_event_rust import RustFullAuditResult, RustReactiveNumericCoRuntime
from ...backends.reactive_wfo_batch import _score_row_from_payload
from ...endpoint import _attach_endpoint_run_config
from .reactive_execution import OriginalReactiveWitnessExecutor
from .reactive_transport import DetachedReactiveWitnessV1


class OriginalReactiveBatchWitnessReducer(OriginalReactiveWitnessExecutor):
    """Reduce existing native account buffers before they leave a bounded chunk."""

    def reduce(self, marker, payload, runner):
        task = marker.task
        binding = self.binding(marker)
        # Reuse the original terminal-liquidation padding contract, not a
        # fabricated continuation/account run for the unprocessed timestamps.
        paths = RustReactiveNumericCoRuntime._pad_terminal_paths(
            runner, payload, total_bars=task.bars)
        audit = RustFullAuditResult.from_compact_payload(paths,
            n_bars=task.bars, n_symbols=len(runner.symbols))
        result = audit.to_backtest_result(
            datetime_index=runner.idx[task.start_bar:task.end_bar],
            closes=runner.market_arrays.closes[task.start_bar:task.end_bar],
            symbols=runner.symbols, initial_capital=runner.initial_capital,
            leverage=float(runner.leverages.mean()), include_audit_reports=False,
            bar_offset=task.start_bar,
            metadata={"quantity_constraints": runner.constraints.as_dict()})
        _attach_endpoint_run_config(result, self.config)
        observation = self.metric_adapter.observe(result,
            expected_index=runner.idx[task.start_bar:task.end_bar], economics_id=self.economics_id,
            input_signature=binding.market_id, prepared_witness=self.witness)
        self.runs += 1
        return DetachedReactiveWitnessV1.prepare(binding, _score_row_from_payload(payload), observation)
