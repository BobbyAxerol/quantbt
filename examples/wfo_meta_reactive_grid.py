"""Public synthetic fill-feedback grid for reset-flat W3 software checks."""

from quantbt import OrderSide, StrategyContextRequirements
from quantbt.strategies.reactive_wfo import STRICT_CAUSAL_CACHE_CONTRACT_V1


class FillFeedbackGrid:
    quantbt_reactive_numeric_v1 = True
    quantbt_requirements = StrategyContextRequirements(
        market=("open", "high", "low", "close"), positions=("qty",),
        account=("equity", "available_equity", "initial_margin", "maintenance_margin", "liquidated"),
        fills="new_only", events="new_only", active_orders="snapshot", context_mode="numeric")

    def __init__(self, *, task, window):
        self.task, self.window = task, int(window)
        self.fill_feedback_count = 0

    def reset(self, *, seed, task):
        self.task = task
        self.fill_feedback_count = 0

    def on_bar_close(self, context, out):
        elapsed = int(context.bar_index) - int(self.task.start_bar)
        for row in range(context.new_fill_count):
            self.fill_feedback_count += 1
            if context.fill_side(row) > 0:
                out.limit(0, OrderSide.SELL, context.fill_qty(row),
                          context.fill_price(row) * 1.003, reduce_only=True)
        if elapsed % (2 * self.window) == 0:
            out.cancel_all(symbol_id=0)
            qty = context.position_qty(0)
            if qty > 0:
                out.market(0, OrderSide.SELL, qty, reduce_only=True)
            else:
                out.limit(0, OrderSide.BUY, .5, context.close(0) * .998)

    def quantbt_state_fingerprint(self):
        return self.window, self.fill_feedback_count


class PreparedGrid:
    causal_cache_contract = STRICT_CAUSAL_CACHE_CONTRACT_V1

    def build_strategy(self, *, params, task):
        return FillFeedbackGrid(task=task, window=params["window"])

    def close(self):
        pass


class GridFactory:
    def prepare_reactive_wfo(self, *, data, folds, static_config):
        return PreparedGrid()
