//! Common deterministic bar execution and cost contracts.
//!
//! `FullSession` owns order lifecycle and account mutation.  This module owns
//! only two separate concerns which every native workload can reuse:
//!
//! - whether an order touches an OHLC bar and at which raw execution price;
//! - how a touched quantity consumes declared bar liquidity and incurs cost.
//!
//! No latent order book is implied.  The V1 models are deterministic OHLCV
//! approximations and therefore remain suitable for reproducible research and
//! parity testing, not a claim of L2 queue simulation.

use quantbt_domain::generated_contracts::{
    CONTRACT_EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE, CONTRACT_EVENT_LIFECYCLE_V3_NEXT_OPEN,
};

pub const ORDER_MARKET_V1: i64 = 0;
pub const ORDER_LIMIT_V1: i64 = 1;
pub const ORDER_STOP_MARKET_V1: i64 = 2;
pub const ORDER_STOP_LIMIT_V1: i64 = 3;
pub const SIDE_BUY_V1: i8 = 1;
pub const SIDE_SELL_V1: i8 = -1;

pub const FILL_REASON_NONE_V1: i64 = 0;
pub const FILL_REASON_NEXT_BAR_CLOSE_V1: i64 = 1;
pub const FILL_REASON_NEXT_OPEN_V1: i64 = 2;
pub const FILL_REASON_LIMIT_TRIGGER_V1: i64 = 3;
pub const FILL_REASON_LIMIT_OPEN_IMPROVEMENT_V1: i64 = 4;
pub const FILL_REASON_STOP_TRIGGER_LEGACY_V1: i64 = 5;
pub const FILL_REASON_STOP_TRIGGER_V1: i64 = 6;
pub const FILL_REASON_STOP_OPEN_WORSE_V1: i64 = 7;
pub const FILL_REASON_STOP_LIMIT_LEGACY_V1: i64 = 8;
pub const FILL_REASON_STOP_LIMIT_OPEN_IMPROVEMENT_V1: i64 = 9;
pub const FILL_REASON_STOP_LIMIT_AFTER_OPEN_TRIGGER_V1: i64 = 10;
pub const FILL_REASON_TRIGGERED_LIMIT_NOT_TOUCHED_V1: i64 = 11;
pub const FILL_REASON_TRIGGERED_AWAIT_NEXT_BAR_V1: i64 = 12;

pub const FILL_AMBIGUITY_NONE_V1: i64 = 0;
pub const FILL_AMBIGUITY_UNORDERED_OHLC_RANGE_V1: i64 = 1;
pub const FILL_AMBIGUITY_STOP_LIMIT_PATH_UNKNOWN_V1: i64 = 2;

/// Minimal immutable market view needed by deterministic OHLC touch logic.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct MarketBarViewV1 {
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub volume: f64,
}

impl MarketBarViewV1 {
    #[must_use]
    pub fn is_valid(self) -> bool {
        self.open.is_finite()
            && self.high.is_finite()
            && self.low.is_finite()
            && self.close.is_finite()
            && self.volume.is_finite()
            && self.volume >= 0.0
    }
}

/// Immutable order fields relevant to bar-touch evaluation. Lifecycle state,
/// TIF and account acceptance stay in `FullSession`.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct OrderTouchViewV1 {
    pub side: i8,
    pub order_type: i64,
    pub limit_price: f64,
    pub stop_price: f64,
    pub trigger_armed: bool,
}

impl OrderTouchViewV1 {
    #[must_use]
    pub fn is_valid(self) -> bool {
        (self.side == SIDE_BUY_V1 || self.side == SIDE_SELL_V1)
            && matches!(
                self.order_type,
                ORDER_MARKET_V1 | ORDER_LIMIT_V1 | ORDER_STOP_MARKET_V1 | ORDER_STOP_LIMIT_V1
            )
            && self.limit_price.is_finite()
            && self.stop_price.is_finite()
    }
}

/// Frozen event-clock selection for one command lifecycle run.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ExecutionClockStateV1 {
    pub event_contract_code: i64,
}

impl ExecutionClockStateV1 {
    pub fn new(event_contract_code: i64) -> Result<Self, String> {
        if !matches!(
            event_contract_code,
            CONTRACT_EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE | CONTRACT_EVENT_LIFECYCLE_V3_NEXT_OPEN
        ) {
            return Err(format!(
                "unsupported deterministic execution clock {event_contract_code}"
            ));
        }
        Ok(Self {
            event_contract_code,
        })
    }
}

/// A touch decision before quantity, liquidity, fee, and account acceptance.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct FillDecisionV1 {
    pub raw_price: Option<f64>,
    pub triggered: bool,
    pub reason: i64,
    pub ambiguity: i64,
    /// Market and stop-market raw prices receive the selected execution
    /// model's price cost. Passive limits preserve their frozen touch price.
    pub apply_price_cost: bool,
}

impl FillDecisionV1 {
    #[must_use]
    pub const fn no_fill(triggered: bool, reason: i64, ambiguity: i64) -> Self {
        Self {
            raw_price: None,
            triggered,
            reason,
            ambiguity,
            apply_price_cost: false,
        }
    }

    #[must_use]
    pub const fn fill(
        raw_price: f64,
        triggered: bool,
        reason: i64,
        ambiguity: i64,
        apply_price_cost: bool,
    ) -> Self {
        Self {
            raw_price: Some(raw_price),
            triggered,
            reason,
            ambiguity,
            apply_price_cost,
        }
    }
}

/// Deterministic OHLC touch/gap authority.  This intentionally freezes the
/// Phase-57 V2/V3 behavior while leaving execution costs to a separate plan.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct BarTouchV1;

impl BarTouchV1 {
    #[must_use]
    pub fn evaluate(
        self,
        order: OrderTouchViewV1,
        market: MarketBarViewV1,
        clock: ExecutionClockStateV1,
    ) -> FillDecisionV1 {
        if !order.is_valid() || !market.is_valid() {
            return FillDecisionV1::no_fill(
                order.trigger_armed,
                FILL_REASON_NONE_V1,
                FILL_AMBIGUITY_NONE_V1,
            );
        }
        let side = order.side;
        if clock.event_contract_code == CONTRACT_EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE {
            return match order.order_type {
                ORDER_MARKET_V1 => FillDecisionV1::fill(
                    market.close,
                    order.trigger_armed,
                    FILL_REASON_NEXT_BAR_CLOSE_V1,
                    FILL_AMBIGUITY_NONE_V1,
                    true,
                ),
                ORDER_LIMIT_V1 if side == SIDE_BUY_V1 && market.low <= order.limit_price => {
                    FillDecisionV1::fill(
                        order.limit_price,
                        order.trigger_armed,
                        FILL_REASON_LIMIT_TRIGGER_V1,
                        FILL_AMBIGUITY_NONE_V1,
                        false,
                    )
                }
                ORDER_LIMIT_V1 if side == SIDE_SELL_V1 && market.high >= order.limit_price => {
                    FillDecisionV1::fill(
                        order.limit_price,
                        order.trigger_armed,
                        FILL_REASON_LIMIT_TRIGGER_V1,
                        FILL_AMBIGUITY_NONE_V1,
                        false,
                    )
                }
                ORDER_STOP_MARKET_V1 if side == SIDE_BUY_V1 && market.high >= order.stop_price => {
                    FillDecisionV1::fill(
                        order.stop_price,
                        true,
                        FILL_REASON_STOP_TRIGGER_LEGACY_V1,
                        FILL_AMBIGUITY_NONE_V1,
                        true,
                    )
                }
                ORDER_STOP_MARKET_V1 if side == SIDE_SELL_V1 && market.low <= order.stop_price => {
                    FillDecisionV1::fill(
                        order.stop_price,
                        true,
                        FILL_REASON_STOP_TRIGGER_LEGACY_V1,
                        FILL_AMBIGUITY_NONE_V1,
                        true,
                    )
                }
                ORDER_STOP_LIMIT_V1
                    if side == SIDE_BUY_V1
                        && market.high >= order.stop_price
                        && market.low <= order.limit_price =>
                {
                    FillDecisionV1::fill(
                        order.limit_price,
                        true,
                        FILL_REASON_STOP_LIMIT_LEGACY_V1,
                        FILL_AMBIGUITY_UNORDERED_OHLC_RANGE_V1,
                        false,
                    )
                }
                ORDER_STOP_LIMIT_V1
                    if side == SIDE_SELL_V1
                        && market.low <= order.stop_price
                        && market.high >= order.limit_price =>
                {
                    FillDecisionV1::fill(
                        order.limit_price,
                        true,
                        FILL_REASON_STOP_LIMIT_LEGACY_V1,
                        FILL_AMBIGUITY_UNORDERED_OHLC_RANGE_V1,
                        false,
                    )
                }
                _ => FillDecisionV1::no_fill(
                    order.trigger_armed,
                    FILL_REASON_NONE_V1,
                    FILL_AMBIGUITY_NONE_V1,
                ),
            };
        }

        match order.order_type {
            ORDER_MARKET_V1 => FillDecisionV1::fill(
                market.open,
                order.trigger_armed,
                FILL_REASON_NEXT_OPEN_V1,
                FILL_AMBIGUITY_NONE_V1,
                true,
            ),
            ORDER_LIMIT_V1 => {
                let favorable_gap = if side == SIDE_BUY_V1 {
                    market.open <= order.limit_price
                } else {
                    market.open >= order.limit_price
                };
                let touched = if side == SIDE_BUY_V1 {
                    market.low <= order.limit_price
                } else {
                    market.high >= order.limit_price
                };
                if favorable_gap {
                    FillDecisionV1::fill(
                        market.open,
                        order.trigger_armed,
                        FILL_REASON_LIMIT_OPEN_IMPROVEMENT_V1,
                        FILL_AMBIGUITY_NONE_V1,
                        false,
                    )
                } else if touched {
                    FillDecisionV1::fill(
                        order.limit_price,
                        order.trigger_armed,
                        FILL_REASON_LIMIT_TRIGGER_V1,
                        FILL_AMBIGUITY_NONE_V1,
                        false,
                    )
                } else {
                    FillDecisionV1::no_fill(
                        order.trigger_armed,
                        FILL_REASON_NONE_V1,
                        FILL_AMBIGUITY_NONE_V1,
                    )
                }
            }
            ORDER_STOP_MARKET_V1 => {
                let gap_trigger = if side == SIDE_BUY_V1 {
                    market.open >= order.stop_price
                } else {
                    market.open <= order.stop_price
                };
                let trigger_touched = if side == SIDE_BUY_V1 {
                    market.high >= order.stop_price
                } else {
                    market.low <= order.stop_price
                };
                if gap_trigger {
                    FillDecisionV1::fill(
                        market.open,
                        true,
                        FILL_REASON_STOP_OPEN_WORSE_V1,
                        FILL_AMBIGUITY_NONE_V1,
                        true,
                    )
                } else if trigger_touched {
                    FillDecisionV1::fill(
                        order.stop_price,
                        true,
                        FILL_REASON_STOP_TRIGGER_V1,
                        FILL_AMBIGUITY_NONE_V1,
                        true,
                    )
                } else {
                    FillDecisionV1::no_fill(false, FILL_REASON_NONE_V1, FILL_AMBIGUITY_NONE_V1)
                }
            }
            ORDER_STOP_LIMIT_V1 if order.trigger_armed => {
                let favorable_gap = if side == SIDE_BUY_V1 {
                    market.open <= order.limit_price
                } else {
                    market.open >= order.limit_price
                };
                let limit_touched = if side == SIDE_BUY_V1 {
                    market.low <= order.limit_price
                } else {
                    market.high >= order.limit_price
                };
                if favorable_gap {
                    FillDecisionV1::fill(
                        market.open,
                        true,
                        FILL_REASON_STOP_LIMIT_OPEN_IMPROVEMENT_V1,
                        FILL_AMBIGUITY_NONE_V1,
                        false,
                    )
                } else if limit_touched {
                    FillDecisionV1::fill(
                        order.limit_price,
                        true,
                        FILL_REASON_LIMIT_TRIGGER_V1,
                        FILL_AMBIGUITY_NONE_V1,
                        false,
                    )
                } else {
                    FillDecisionV1::no_fill(
                        true,
                        FILL_REASON_TRIGGERED_LIMIT_NOT_TOUCHED_V1,
                        FILL_AMBIGUITY_NONE_V1,
                    )
                }
            }
            ORDER_STOP_LIMIT_V1 => {
                let gap_trigger = if side == SIDE_BUY_V1 {
                    market.open >= order.stop_price
                } else {
                    market.open <= order.stop_price
                };
                let trigger_touched = if side == SIDE_BUY_V1 {
                    market.high >= order.stop_price
                } else {
                    market.low <= order.stop_price
                };
                let limit_touched = if side == SIDE_BUY_V1 {
                    market.low <= order.limit_price
                } else {
                    market.high >= order.limit_price
                };
                if !trigger_touched {
                    FillDecisionV1::no_fill(false, FILL_REASON_NONE_V1, FILL_AMBIGUITY_NONE_V1)
                } else if gap_trigger {
                    let favorable_gap = if side == SIDE_BUY_V1 {
                        market.open <= order.limit_price
                    } else {
                        market.open >= order.limit_price
                    };
                    if favorable_gap {
                        FillDecisionV1::fill(
                            market.open,
                            true,
                            FILL_REASON_STOP_LIMIT_OPEN_IMPROVEMENT_V1,
                            FILL_AMBIGUITY_NONE_V1,
                            false,
                        )
                    } else if limit_touched {
                        FillDecisionV1::fill(
                            order.limit_price,
                            true,
                            FILL_REASON_STOP_LIMIT_AFTER_OPEN_TRIGGER_V1,
                            FILL_AMBIGUITY_NONE_V1,
                            false,
                        )
                    } else {
                        FillDecisionV1::no_fill(
                            true,
                            FILL_REASON_TRIGGERED_LIMIT_NOT_TOUCHED_V1,
                            FILL_AMBIGUITY_NONE_V1,
                        )
                    }
                } else if limit_touched {
                    FillDecisionV1::no_fill(
                        true,
                        FILL_REASON_TRIGGERED_AWAIT_NEXT_BAR_V1,
                        FILL_AMBIGUITY_STOP_LIMIT_PATH_UNKNOWN_V1,
                    )
                } else {
                    FillDecisionV1::no_fill(
                        true,
                        FILL_REASON_TRIGGERED_LIMIT_NOT_TOUCHED_V1,
                        FILL_AMBIGUITY_NONE_V1,
                    )
                }
            }
            _ => FillDecisionV1::no_fill(
                order.trigger_armed,
                FILL_REASON_NONE_V1,
                FILL_AMBIGUITY_NONE_V1,
            ),
        }
    }
}

/// Per-bar synthetic liquidity.  A finite capacity is only enabled when the
/// declared model explicitly sets a participation cap; otherwise every symbol
/// has infinite bar liquidity and preserves the legacy full-fill contract.
#[derive(Clone, Debug, PartialEq)]
pub struct LiquidityLedgerV1 {
    capacity: Vec<f64>,
    consumed: Vec<f64>,
}

impl LiquidityLedgerV1 {
    #[must_use]
    pub fn unlimited(n_symbols: usize) -> Self {
        Self {
            capacity: vec![f64::INFINITY; n_symbols],
            consumed: vec![0.0; n_symbols],
        }
    }

    pub fn begin_bar(
        &mut self,
        volumes: &[f64],
        participation_rate: Option<f64>,
    ) -> Result<(), String> {
        if self.capacity.len() != volumes.len() || self.consumed.len() != volumes.len() {
            return Err("liquidity ledger shape does not match market symbols".to_owned());
        }
        let cap = participation_rate.unwrap_or(f64::INFINITY);
        if !(cap.is_finite() && (0.0..=1.0).contains(&cap)) && !cap.is_infinite() {
            return Err("participation rate must be in [0, 1] when enabled".to_owned());
        }
        for (index, volume) in volumes.iter().copied().enumerate() {
            if !volume.is_finite() || volume < 0.0 {
                return Err("bar liquidity volume must be finite and non-negative".to_owned());
            }
            self.capacity[index] = if cap.is_infinite() {
                f64::INFINITY
            } else {
                volume * cap
            };
            self.consumed[index] = 0.0;
        }
        Ok(())
    }

    /// Restore the declared no-participation-cap baseline without allocating.
    /// `FullSession::reset` calls this even though the next bar will overwrite
    /// the ledger, so an idle reusable session has no residual fill capacity
    /// or consumed-liquidity state from its predecessor.
    pub fn reset_unlimited(&mut self) {
        self.capacity.fill(f64::INFINITY);
        self.consumed.fill(0.0);
    }

    #[must_use]
    pub fn available(&self, symbol: usize) -> f64 {
        self.capacity
            .get(symbol)
            .zip(self.consumed.get(symbol))
            .map_or(0.0, |(capacity, consumed)| (capacity - consumed).max(0.0))
    }

    pub fn commit(&mut self, symbol: usize, quantity: f64) -> Result<(), String> {
        if symbol >= self.consumed.len() || !quantity.is_finite() || quantity < 0.0 {
            return Err("invalid liquidity consumption".to_owned());
        }
        if quantity > self.available(symbol) + 1e-12 {
            return Err("liquidity consumption exceeds the declared bar capacity".to_owned());
        }
        self.consumed[symbol] += quantity;
        Ok(())
    }

    #[must_use]
    pub fn consumed(&self, symbol: usize) -> f64 {
        self.consumed.get(symbol).copied().unwrap_or(0.0)
    }
}

/// Immutable cost parameters for deterministic OHLCV execution.  `spread_bps`
/// is a full bid/ask spread; half is applied on the selected execution side.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct CostModelV1 {
    pub proportional_slippage: f64,
    pub spread_bps: f64,
    pub fixed_slippage: f64,
    pub impact_coefficient: f64,
    pub participation_rate: Option<f64>,
}

impl CostModelV1 {
    pub fn new(
        proportional_slippage: f64,
        spread_bps: f64,
        fixed_slippage: f64,
        impact_coefficient: f64,
        participation_rate: Option<f64>,
    ) -> Result<Self, String> {
        if [
            proportional_slippage,
            spread_bps,
            fixed_slippage,
            impact_coefficient,
        ]
        .iter()
        .any(|value| !value.is_finite() || *value < 0.0)
            || participation_rate
                .is_some_and(|value| !value.is_finite() || !(0.0..=1.0).contains(&value))
        {
            return Err("execution cost model contains an invalid non-negative value".to_owned());
        }
        Ok(Self {
            proportional_slippage,
            spread_bps,
            fixed_slippage,
            impact_coefficient,
            participation_rate,
        })
    }

    pub fn legacy(proportional_slippage: f64) -> Result<Self, String> {
        Self::new(proportional_slippage, 0.0, 0.0, 0.0, None)
    }
}

/// Execution model plan resolved before a run.  `BarTouch` is the frozen
/// legacy-compatible default.  `Cost` adds declared deterministic cost and
/// participation semantics without changing touch eligibility.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum ExecutionModelPlanV1 {
    BarTouch { proportional_slippage: f64 },
    Cost(CostModelV1),
}

impl ExecutionModelPlanV1 {
    pub fn legacy(proportional_slippage: f64) -> Result<Self, String> {
        CostModelV1::legacy(proportional_slippage)?;
        Ok(Self::BarTouch {
            proportional_slippage,
        })
    }

    #[must_use]
    pub const fn id(self) -> &'static str {
        match self {
            Self::BarTouch { .. } => "bar_touch_v1",
            Self::Cost(_) => "cost_model_v1",
        }
    }

    #[must_use]
    pub const fn participation_rate(self) -> Option<f64> {
        match self {
            Self::BarTouch { .. } => None,
            Self::Cost(model) => model.participation_rate,
        }
    }

    #[must_use]
    pub const fn is_legacy_equivalent(self) -> bool {
        matches!(self, Self::BarTouch { .. })
    }
}

/// Input to a fill-cost preview.  It does not mutate account or liquidity.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct FillCostInputV1 {
    pub symbol: usize,
    pub side: i8,
    pub raw_price: f64,
    pub requested_qty: f64,
    pub bar_volume: f64,
    pub contract_multiplier: f64,
    pub one_way_fee_rate: f64,
    pub apply_price_cost: bool,
}

/// One previewed fill. The caller must call `commit_fill` only after account
/// margin acceptance; rejected fills cannot consume shared bar liquidity.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ExecutionFillV1 {
    pub quantity: f64,
    pub price: f64,
    pub fee: f64,
    pub turnover: f64,
    pub slippage_cost: f64,
    pub partial: bool,
}

/// Common execution model interface. `begin_bar` resets the ledger once for
/// the whole shared session, guaranteeing that package legs and sibling orders
/// cannot consume the same synthetic liquidity twice.
pub trait ExecutionModelV1 {
    fn id(&self) -> &'static str;

    fn begin_bar(&self, volumes: &[f64], ledger: &mut LiquidityLedgerV1) -> Result<(), String>;

    fn evaluate_order(
        &self,
        order: OrderTouchViewV1,
        market: MarketBarViewV1,
        clock: ExecutionClockStateV1,
    ) -> FillDecisionV1;

    fn preview_fill(
        &self,
        input: FillCostInputV1,
        ledger: &LiquidityLedgerV1,
    ) -> Result<Option<ExecutionFillV1>, String>;

    fn commit_fill(
        &self,
        fill: ExecutionFillV1,
        symbol: usize,
        ledger: &mut LiquidityLedgerV1,
    ) -> Result<(), String>;
}

impl ExecutionModelV1 for ExecutionModelPlanV1 {
    fn id(&self) -> &'static str {
        (*self).id()
    }

    fn begin_bar(&self, volumes: &[f64], ledger: &mut LiquidityLedgerV1) -> Result<(), String> {
        ledger.begin_bar(volumes, (*self).participation_rate())
    }

    fn evaluate_order(
        &self,
        order: OrderTouchViewV1,
        market: MarketBarViewV1,
        clock: ExecutionClockStateV1,
    ) -> FillDecisionV1 {
        BarTouchV1.evaluate(order, market, clock)
    }

    fn preview_fill(
        &self,
        input: FillCostInputV1,
        ledger: &LiquidityLedgerV1,
    ) -> Result<Option<ExecutionFillV1>, String> {
        if input.side != SIDE_BUY_V1 && input.side != SIDE_SELL_V1
            || !input.raw_price.is_finite()
            || input.raw_price <= 0.0
            || !input.requested_qty.is_finite()
            || input.requested_qty <= 0.0
            || !input.bar_volume.is_finite()
            || input.bar_volume < 0.0
            || !input.contract_multiplier.is_finite()
            || input.contract_multiplier <= 0.0
            || !input.one_way_fee_rate.is_finite()
            || input.one_way_fee_rate < 0.0
        {
            return Err("execution fill cost input is invalid".to_owned());
        }
        let quantity = input.requested_qty.min(ledger.available(input.symbol));
        if quantity <= 0.0 {
            return Ok(None);
        }
        let (proportional, fixed) = match self {
            Self::BarTouch {
                proportional_slippage,
            } if input.apply_price_cost => (*proportional_slippage, 0.0),
            Self::BarTouch { .. } => (0.0, 0.0),
            Self::Cost(model) if input.apply_price_cost => {
                let realized_participation = if input.bar_volume > 0.0 {
                    quantity / input.bar_volume
                } else {
                    0.0
                };
                (
                    model.proportional_slippage
                        + model.spread_bps / 20_000.0
                        + model.impact_coefficient * realized_participation,
                    model.fixed_slippage,
                )
            }
            Self::Cost(_) => (0.0, 0.0),
        };
        let direction = f64::from(input.side);
        let price = input.raw_price * (1.0 + direction * proportional) + direction * fixed;
        if !price.is_finite() || price <= 0.0 {
            return Err("execution model produced a non-positive fill price".to_owned());
        }
        let turnover = quantity * price * input.contract_multiplier;
        Ok(Some(ExecutionFillV1 {
            quantity,
            price,
            fee: turnover * input.one_way_fee_rate,
            turnover,
            slippage_cost: (price - input.raw_price).abs() * quantity * input.contract_multiplier,
            partial: quantity + 1e-12 < input.requested_qty,
        }))
    }

    fn commit_fill(
        &self,
        fill: ExecutionFillV1,
        symbol: usize,
        ledger: &mut LiquidityLedgerV1,
    ) -> Result<(), String> {
        ledger.commit(symbol, fill.quantity)
    }
}

#[cfg(test)]
mod tests {
    use super::{
        BarTouchV1, CostModelV1, ExecutionClockStateV1, ExecutionModelPlanV1, ExecutionModelV1,
        FILL_AMBIGUITY_STOP_LIMIT_PATH_UNKNOWN_V1, FILL_REASON_LIMIT_OPEN_IMPROVEMENT_V1,
        FILL_REASON_STOP_OPEN_WORSE_V1, FillCostInputV1, LiquidityLedgerV1, MarketBarViewV1,
        ORDER_LIMIT_V1, ORDER_STOP_LIMIT_V1, ORDER_STOP_MARKET_V1, OrderTouchViewV1, SIDE_BUY_V1,
        SIDE_SELL_V1,
    };
    use quantbt_domain::generated_contracts::{
        CONTRACT_EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE, CONTRACT_EVENT_LIFECYCLE_V3_NEXT_OPEN,
    };

    fn market() -> MarketBarViewV1 {
        MarketBarViewV1 {
            open: 99.0,
            high: 105.0,
            low: 95.0,
            close: 101.0,
            volume: 10.0,
        }
    }

    #[test]
    fn bar_touch_v3_preserves_favorable_limit_and_stop_gap_contract() {
        let clock = ExecutionClockStateV1::new(CONTRACT_EVENT_LIFECYCLE_V3_NEXT_OPEN).unwrap();
        let limit = BarTouchV1.evaluate(
            OrderTouchViewV1 {
                side: SIDE_BUY_V1,
                order_type: ORDER_LIMIT_V1,
                limit_price: 100.0,
                stop_price: 0.0,
                trigger_armed: false,
            },
            market(),
            clock,
        );
        assert_eq!(limit.raw_price, Some(99.0));
        assert_eq!(limit.reason, FILL_REASON_LIMIT_OPEN_IMPROVEMENT_V1);
        assert!(!limit.apply_price_cost);

        let stop = BarTouchV1.evaluate(
            OrderTouchViewV1 {
                side: SIDE_SELL_V1,
                order_type: ORDER_STOP_MARKET_V1,
                limit_price: 0.0,
                stop_price: 100.0,
                trigger_armed: false,
            },
            market(),
            clock,
        );
        assert_eq!(stop.raw_price, Some(99.0));
        assert_eq!(stop.reason, FILL_REASON_STOP_OPEN_WORSE_V1);
        assert!(stop.apply_price_cost);
    }

    #[test]
    fn bar_touch_v3_keeps_stop_limit_ambiguity_explicit() {
        let decision = BarTouchV1.evaluate(
            OrderTouchViewV1 {
                side: SIDE_BUY_V1,
                order_type: ORDER_STOP_LIMIT_V1,
                limit_price: 98.0,
                stop_price: 102.0,
                trigger_armed: false,
            },
            market(),
            ExecutionClockStateV1::new(CONTRACT_EVENT_LIFECYCLE_V3_NEXT_OPEN).unwrap(),
        );
        assert!(decision.raw_price.is_none());
        assert!(decision.triggered);
        assert_eq!(
            decision.ambiguity,
            FILL_AMBIGUITY_STOP_LIMIT_PATH_UNKNOWN_V1
        );
    }

    #[test]
    fn default_cost_model_matches_legacy_slippage_and_fee() {
        let plan = ExecutionModelPlanV1::legacy(0.002).unwrap();
        let mut ledger = LiquidityLedgerV1::unlimited(1);
        plan.begin_bar(&[10.0], &mut ledger).unwrap();
        let fill = plan
            .preview_fill(
                FillCostInputV1 {
                    symbol: 0,
                    side: SIDE_BUY_V1,
                    raw_price: 100.0,
                    requested_qty: 2.0,
                    bar_volume: 10.0,
                    contract_multiplier: 1.0,
                    one_way_fee_rate: 0.0005,
                    apply_price_cost: true,
                },
                &ledger,
            )
            .unwrap()
            .unwrap();
        assert_eq!(fill.price, 100.2);
        assert_eq!(fill.turnover, 200.4);
        assert!((fill.fee - 0.1002).abs() <= 1e-15);
        assert!(!fill.partial);
    }

    #[test]
    fn shared_participation_conserves_one_bar_liquidity_across_orders() {
        let plan =
            ExecutionModelPlanV1::Cost(CostModelV1::new(0.0, 0.0, 0.0, 0.0, Some(0.25)).unwrap());
        let mut ledger = LiquidityLedgerV1::unlimited(1);
        plan.begin_bar(&[100.0], &mut ledger).unwrap();
        let first = plan
            .preview_fill(
                FillCostInputV1 {
                    symbol: 0,
                    side: SIDE_BUY_V1,
                    raw_price: 100.0,
                    requested_qty: 20.0,
                    bar_volume: 100.0,
                    contract_multiplier: 1.0,
                    one_way_fee_rate: 0.0,
                    apply_price_cost: true,
                },
                &ledger,
            )
            .unwrap()
            .unwrap();
        assert_eq!(first.quantity, 20.0);
        plan.commit_fill(first, 0, &mut ledger).unwrap();
        let second = plan
            .preview_fill(
                FillCostInputV1 {
                    symbol: 0,
                    side: SIDE_BUY_V1,
                    raw_price: 100.0,
                    requested_qty: 20.0,
                    bar_volume: 100.0,
                    contract_multiplier: 1.0,
                    one_way_fee_rate: 0.0,
                    apply_price_cost: true,
                },
                &ledger,
            )
            .unwrap()
            .unwrap();
        assert_eq!(second.quantity, 5.0);
        assert!(second.partial);
        plan.commit_fill(second, 0, &mut ledger).unwrap();
        assert_eq!(ledger.consumed(0), 25.0);
        assert!(
            plan.preview_fill(
                FillCostInputV1 {
                    symbol: 0,
                    side: SIDE_BUY_V1,
                    raw_price: 100.0,
                    requested_qty: 1.0,
                    bar_volume: 100.0,
                    contract_multiplier: 1.0,
                    one_way_fee_rate: 0.0,
                    apply_price_cost: true,
                },
                &ledger,
            )
            .unwrap()
            .is_none()
        );
    }

    #[test]
    fn explicit_cost_fixture_combines_spread_impact_fixed_slippage_and_fee() {
        let model = ExecutionModelPlanV1::Cost(
            CostModelV1::new(0.001, 10.0, 0.25, 0.02, Some(0.5)).unwrap(),
        );
        let mut ledger = LiquidityLedgerV1::unlimited(1);
        model.begin_bar(&[100.0], &mut ledger).unwrap();
        let fill = model
            .preview_fill(
                FillCostInputV1 {
                    symbol: 0,
                    side: SIDE_BUY_V1,
                    raw_price: 100.0,
                    requested_qty: 20.0,
                    bar_volume: 100.0,
                    contract_multiplier: 1.0,
                    one_way_fee_rate: 0.0005,
                    apply_price_cost: true,
                },
                &ledger,
            )
            .unwrap()
            .unwrap();

        // 100 * (1 + 0.001 proportional + 0.0005 half spread
        // + 0.02 * 20/100 impact) + 0.25 fixed = 100.8.
        assert_eq!(fill.quantity, 20.0);
        assert!((fill.price - 100.8).abs() < 1e-12);
        assert!((fill.turnover - 2_016.0).abs() < 1e-12);
        assert!((fill.fee - 1.008).abs() < 1e-12);
        assert!((fill.slippage_cost - 16.0).abs() < 1e-12);
        assert!(!fill.partial);
        model.commit_fill(fill, 0, &mut ledger).unwrap();
        assert!((ledger.available(0) - 30.0).abs() < 1e-12);
    }

    #[test]
    fn v2_clock_is_explicit_not_a_silent_default() {
        let clock = ExecutionClockStateV1::new(CONTRACT_EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE).unwrap();
        assert_eq!(
            clock.event_contract_code,
            CONTRACT_EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE
        );
        assert!(ExecutionClockStateV1::new(999).is_err());
    }
}
