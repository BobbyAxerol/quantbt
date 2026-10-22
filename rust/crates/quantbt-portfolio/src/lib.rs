//! Typed portfolio target planning over the shared Rust event/account core.
//!
//! Research-layer allocation remains Python/Numba territory. This crate owns a
//! narrow, replayable target-units contract: validate targets, apply the frozen
//! P0 margin allocation policy, and compile accepted deltas into canonical
//! ABI-0.5 market commands for `quantbt-engine` to execute.

use quantbt_domain::commands::{CommandTapeV5, OrderCommandV5};
use quantbt_domain::enums::{ActivationPolicy, CommandAction, OrderType, Side, TimeInForce};
use quantbt_domain::errors::DomainError;
use quantbt_domain::ids::{ExternalOrderId, SymbolId};

const EPSILON: f64 = 1e-12;

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct PortfolioTarget {
    pub symbol: SymbolId,
    pub target_qty: f64,
}

#[derive(Clone, Debug, PartialEq)]
pub struct PortfolioTargetRow {
    pub bar: u32,
    pub targets: Box<[PortfolioTarget]>,
}

impl PortfolioTargetRow {
    pub fn new(bar: u32, targets: Vec<PortfolioTarget>) -> Result<Self, DomainError> {
        if targets.iter().any(|target| !target.target_qty.is_finite()) {
            return Err(DomainError::InvalidCommand {
                command: bar as usize,
                reason: "portfolio target quantity must be finite",
            });
        }
        Ok(Self {
            bar,
            targets: targets.into_boxed_slice(),
        })
    }
}

/// Bar-major target-units tape. The tape contains no fills, account mutation,
/// or report data; it is an immutable research-to-execution boundary.
#[derive(Clone, Debug, PartialEq)]
pub struct PortfolioTargetTape {
    n_bars: usize,
    n_symbols: usize,
    target_units: Box<[f64]>,
}

impl PortfolioTargetTape {
    pub fn new(n_bars: usize, n_symbols: usize, target_units: Vec<f64>) -> Result<Self, String> {
        if n_bars == 0 || n_symbols == 0 || target_units.len() != n_bars * n_symbols {
            return Err("portfolio target tape has invalid dimensions".to_owned());
        }
        if target_units.iter().any(|value| !value.is_finite()) {
            return Err("portfolio target tape values must be finite".to_owned());
        }
        Ok(Self {
            n_bars,
            n_symbols,
            target_units: target_units.into_boxed_slice(),
        })
    }

    #[must_use]
    pub const fn n_bars(&self) -> usize {
        self.n_bars
    }

    #[must_use]
    pub const fn n_symbols(&self) -> usize {
        self.n_symbols
    }

    #[must_use]
    pub fn targets_at(&self, bar: usize) -> &[f64] {
        let start = bar * self.n_symbols;
        &self.target_units[start..start + self.n_symbols]
    }
}

#[repr(u8)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PortfolioMarginAllocationPolicy {
    SequentialLegacy = 0,
    ProRataToAvailableMargin = 1,
    AllOrNoneTarget = 2,
    ReduceFirstThenIncrease = 3,
}

impl TryFrom<u8> for PortfolioMarginAllocationPolicy {
    type Error = String;

    fn try_from(value: u8) -> Result<Self, Self::Error> {
        match value {
            0 => Ok(Self::SequentialLegacy),
            1 => Ok(Self::ProRataToAvailableMargin),
            2 => Ok(Self::AllOrNoneTarget),
            3 => Ok(Self::ReduceFirstThenIncrease),
            _ => Err("unsupported portfolio margin allocation policy".to_owned()),
        }
    }
}

#[repr(u8)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PortfolioTargetRejectReason {
    Accepted = 0,
    NonTradable = 1,
    StalePrice = 2,
    InvalidTarget = 3,
    MinQty = 4,
    MinNotional = 5,
    PostCostMargin = 6,
    AtomicRollback = 7,
}

impl PortfolioTargetRejectReason {
    #[must_use]
    pub const fn name(self) -> &'static str {
        match self {
            Self::Accepted => "ACCEPTED",
            Self::NonTradable => "NON_TRADABLE",
            Self::StalePrice => "STALE_PRICE",
            Self::InvalidTarget => "INVALID_TARGET",
            Self::MinQty => "MIN_QTY",
            Self::MinNotional => "MIN_NOTIONAL",
            Self::PostCostMargin => "POST_COST_MARGIN",
            Self::AtomicRollback => "ATOMIC_ROLLBACK",
        }
    }
}

#[derive(Clone, Debug)]
pub struct PortfolioTargetRequest<'a> {
    pub previous_units: &'a [f64],
    pub requested_units: &'a [f64],
    pub prices: &'a [f64],
    pub equity: f64,
    pub contract_sizes: &'a [f64],
    pub leverages: &'a [f64],
    pub fee_rates: &'a [f64],
    pub slippage_rates: &'a [f64],
    pub tradable: &'a [bool],
    pub stale: &'a [bool],
    /// Minimum actual delta-order size at the close mark. Pure reductions and
    /// closes are exempt; these are not minimum retained-position sizes.
    pub min_qty: &'a [f64],
    pub min_notional: &'a [f64],
    pub reserved_margin: f64,
    pub policy: PortfolioMarginAllocationPolicy,
}

#[derive(Clone, Debug, PartialEq)]
pub struct PortfolioTargetExecution {
    pub requested_units: Vec<f64>,
    pub accepted_units: Vec<f64>,
    pub delta_qty: Vec<f64>,
    pub traded_notional: Vec<f64>,
    pub fees: Vec<f64>,
    pub slippage: Vec<f64>,
    pub initial_margin: Vec<f64>,
    pub rejection_reasons: Vec<PortfolioTargetRejectReason>,
    pub policy: PortfolioMarginAllocationPolicy,
    pub available_equity_after: f64,
}

impl PortfolioTargetExecution {
    #[must_use]
    pub fn rejection_codes(&self) -> Vec<u8> {
        self.rejection_reasons
            .iter()
            .map(|reason| *reason as u8)
            .collect()
    }

    #[must_use]
    pub fn invariant_passes(&self, tolerance: f64) -> bool {
        // A carried IM deficit is allowed for affordable pure reductions, not
        // for new exposure. Do not mislabel that accepted repair as invalid.
        let reductions_only = self
            .accepted_units
            .iter()
            .zip(&self.delta_qty)
            .all(|(accepted, delta)| is_reduction(accepted - delta, *accepted));
        let margin_valid = self.available_equity_after >= -tolerance
            || (reductions_only
                && self.available_equity_after + sum(&self.initial_margin) >= -tolerance);
        self.delta_qty
            .iter()
            .zip(self.accepted_units.iter().zip(self.requested_units.iter()))
            .all(|(delta, (accepted, _))| delta.is_finite() && accepted.is_finite())
            && self
                .traded_notional
                .iter()
                .zip(self.fees.iter().zip(self.slippage.iter()))
                .all(|(notional, (fee, slippage))| {
                    notional.is_finite() && fee.is_finite() && slippage.is_finite()
                })
            && margin_valid
    }
}

/// Apply the same P0 target acceptance arithmetic as the Python reference.
/// It intentionally does not mutate positions; callers must compile the
/// resulting delta into commands and execute through `quantbt-engine`.
pub fn execute_portfolio_target(
    request: PortfolioTargetRequest<'_>,
) -> Result<PortfolioTargetExecution, String> {
    let n = request.previous_units.len();
    let vectors = [
        request.requested_units.len(),
        request.prices.len(),
        request.contract_sizes.len(),
        request.leverages.len(),
        request.fee_rates.len(),
        request.slippage_rates.len(),
        request.tradable.len(),
        request.stale.len(),
        request.min_qty.len(),
        request.min_notional.len(),
    ];
    if n == 0 || vectors.iter().any(|length| *length != n) {
        return Err("portfolio target vectors must be non-empty and equal length".to_owned());
    }
    if !request.equity.is_finite() || request.equity <= 0.0 || request.reserved_margin < 0.0 {
        return Err("portfolio target equity/reserved margin is invalid".to_owned());
    }
    if request
        .previous_units
        .iter()
        .any(|value| !value.is_finite())
        || request
            .contract_sizes
            .iter()
            .any(|value| !value.is_finite() || *value <= 0.0)
        || request
            .leverages
            .iter()
            .any(|value| !value.is_finite() || *value <= 0.0)
        || request
            .fee_rates
            .iter()
            .any(|value| !value.is_finite() || *value < 0.0)
        || request
            .slippage_rates
            .iter()
            .any(|value| !value.is_finite() || *value < 0.0)
        || request
            .min_qty
            .iter()
            .any(|value| !value.is_finite() || *value < 0.0)
        || request
            .min_notional
            .iter()
            .any(|value| !value.is_finite() || *value < 0.0)
    {
        return Err("portfolio target constraints are invalid".to_owned());
    }

    let valuation_prices = request
        .prices
        .iter()
        .map(|price| {
            if price.is_finite() && *price > 0.0 {
                *price
            } else {
                0.0
            }
        })
        .collect::<Vec<_>>();
    let mut accepted = request.previous_units.to_vec();
    let mut reasons = (0..n)
        .map(|index| validation_reason(&request, index))
        .collect::<Vec<_>>();
    // A market sell with an invalidly large slippage rate could otherwise
    // create a non-positive fill price after the ordinary target validation.
    // Treat that as an invalid target row and preserve all-or-none admission
    // rather than letting a later arithmetic error partially escape the gate.
    for (index, reason) in reasons.iter_mut().enumerate() {
        let delta = request.requested_units[index] - request.previous_units[index];
        if *reason == PortfolioTargetRejectReason::Accepted && delta.abs() > EPSILON {
            let execution_price =
                market_execution_price(request.prices[index], delta, request.slippage_rates[index]);
            if !execution_price.is_finite() || execution_price <= 0.0 {
                *reason = PortfolioTargetRejectReason::InvalidTarget;
            }
        }
    }
    let valid = reasons
        .iter()
        .map(|reason| *reason == PortfolioTargetRejectReason::Accepted)
        .collect::<Vec<_>>();

    match request.policy {
        PortfolioMarginAllocationPolicy::AllOrNoneTarget => {
            let candidate = request.requested_units.to_vec();
            let delta = subtract(&candidate, request.previous_units);
            let costs = cost_vector(
                &delta,
                &valuation_prices,
                request.contract_sizes,
                request.fee_rates,
                request.slippage_rates,
            );
            let margin = margin_vector(
                &candidate,
                &valuation_prices,
                request.contract_sizes,
                request.leverages,
            );
            let reductions_only = request
                .previous_units
                .iter()
                .zip(&candidate)
                .all(|(previous, target)| is_reduction(*previous, *target));
            let required = sum(&costs)
                + request.reserved_margin
                + if reductions_only { 0.0 } else { sum(&margin) };
            if !valid.iter().all(|value| *value) || required > request.equity + EPSILON {
                for index in 0..n {
                    if valid[index] {
                        reasons[index] = PortfolioTargetRejectReason::AtomicRollback;
                    }
                }
            } else {
                accepted = candidate;
            }
        }
        PortfolioMarginAllocationPolicy::ProRataToAvailableMargin => {
            let (baseline, reduction_costs) =
                reduction_baseline(&request, &valuation_prices, &valid, &mut reasons);
            accepted = baseline;
            let remaining = (request.equity
                - request.reserved_margin
                - reduction_costs
                - sum(&margin_vector(
                    &accepted,
                    &valuation_prices,
                    request.contract_sizes,
                    request.leverages,
                )))
            .max(0.0);
            let increase = subtract(request.requested_units, &accepted);
            let required = (0..n)
                .map(|index| {
                    increase[index].abs() * valuation_prices[index] * request.contract_sizes[index]
                        / request.leverages[index]
                        + increase[index].abs()
                            * valuation_prices[index]
                            * request.contract_sizes[index]
                            * (request.fee_rates[index] + request.slippage_rates[index])
                })
                .collect::<Vec<_>>();
            let total_required = required
                .iter()
                .enumerate()
                .filter(|(index, _)| reasons[*index] == PortfolioTargetRejectReason::Accepted)
                .map(|(_, value)| *value)
                .sum::<f64>();
            let scale = if total_required > 0.0 {
                (remaining / total_required).min(1.0)
            } else {
                1.0
            };
            for index in 0..n {
                if reasons[index] == PortfolioTargetRejectReason::Accepted {
                    let candidate = accepted[index] + increase[index] * scale;
                    let reason = target_delta_validation_reason(
                        request.previous_units[index],
                        candidate,
                        valuation_prices[index],
                        request.contract_sizes[index],
                        request.min_qty[index],
                        request.min_notional[index],
                    );
                    if reason != PortfolioTargetRejectReason::Accepted {
                        reasons[index] = reason;
                    } else if scale < 1.0 && increase[index].abs() > EPSILON {
                        accepted[index] = candidate;
                        reasons[index] = PortfolioTargetRejectReason::PostCostMargin;
                    } else {
                        accepted[index] = candidate;
                    }
                }
            }
        }
        PortfolioMarginAllocationPolicy::SequentialLegacy
        | PortfolioMarginAllocationPolicy::ReduceFirstThenIncrease => {
            let mut order = (0..n).collect::<Vec<_>>();
            if request.policy == PortfolioMarginAllocationPolicy::ReduceFirstThenIncrease {
                order.sort_by_key(|index| {
                    (
                        !is_reduction(
                            request.previous_units[*index],
                            request.requested_units[*index],
                        ),
                        *index,
                    )
                });
            }
            for index in order {
                if !valid[index] {
                    continue;
                }
                let mut candidate = accepted.clone();
                candidate[index] = request.requested_units[index];
                let delta = subtract(&candidate, request.previous_units);
                let costs = cost_vector(
                    &delta,
                    &valuation_prices,
                    request.contract_sizes,
                    request.fee_rates,
                    request.slippage_rates,
                );
                let costs_required = sum(&costs) + request.reserved_margin;
                let required = if is_reduction(accepted[index], candidate[index]) {
                    // A pure reduction need not restore initial-margin
                    // coverage. It must still be affordable after prior fills.
                    costs_required
                } else {
                    sum(&margin_vector(
                        &candidate,
                        &valuation_prices,
                        request.contract_sizes,
                        request.leverages,
                    )) + costs_required
                };
                if required <= request.equity + EPSILON {
                    accepted[index] = request.requested_units[index];
                } else {
                    reasons[index] = PortfolioTargetRejectReason::PostCostMargin;
                }
            }
        }
    }

    let delta_qty = subtract(&accepted, request.previous_units);
    let traded_notional = (0..n)
        .map(|index| {
            delta_qty[index].abs() * valuation_prices[index] * request.contract_sizes[index]
        })
        .collect::<Vec<_>>();
    let fees = (0..n)
        .map(|index| traded_notional[index] * request.fee_rates[index])
        .collect::<Vec<_>>();
    let slippage = (0..n)
        .map(|index| traded_notional[index] * request.slippage_rates[index])
        .collect::<Vec<_>>();
    let initial_margin = margin_vector(
        &accepted,
        &valuation_prices,
        request.contract_sizes,
        request.leverages,
    );
    let available_equity_after = request.equity
        - request.reserved_margin
        - sum(&initial_margin)
        - sum(&fees)
        - sum(&slippage);
    Ok(PortfolioTargetExecution {
        requested_units: request.requested_units.to_vec(),
        accepted_units: accepted,
        delta_qty,
        traded_notional,
        fees,
        slippage,
        initial_margin,
        rejection_reasons: reasons,
        policy: request.policy,
        available_equity_after,
    })
}

/// Resolve one all-or-none target row against the exact market-order cost and
/// margin gate used by `quantbt-engine::FullSession`.
///
/// Unlike [`execute_portfolio_target`], this bounded execution helper models
/// the actual V2 market fill price (`close * (1 +/- slippage)`), fee charged at
/// that fill price, and the engine's sequential free-margin check.  It is the
/// Rust-owned bridge for the promoted `target_units` route; legacy planner
/// policies intentionally keep their historical arithmetic unchanged.
///
/// The result is still only an immutable acceptance decision.  Accepted deltas
/// must be compiled into canonical commands and executed by `FullSession`;
/// this function never changes positions or cash itself.
pub fn execute_portfolio_target_market_all_or_none(
    request: PortfolioTargetRequest<'_>,
) -> Result<PortfolioTargetExecution, String> {
    if request.policy != PortfolioMarginAllocationPolicy::AllOrNoneTarget {
        return Err("market target execution supports only all_or_none_target policy".to_owned());
    }
    let n = request.previous_units.len();
    let vectors = [
        request.requested_units.len(),
        request.prices.len(),
        request.contract_sizes.len(),
        request.leverages.len(),
        request.fee_rates.len(),
        request.slippage_rates.len(),
        request.tradable.len(),
        request.stale.len(),
        request.min_qty.len(),
        request.min_notional.len(),
    ];
    if n == 0 || vectors.iter().any(|length| *length != n) {
        return Err("portfolio target vectors must be non-empty and equal length".to_owned());
    }
    if !request.equity.is_finite() || request.equity <= 0.0 || request.reserved_margin < 0.0 {
        return Err("portfolio target equity/reserved margin is invalid".to_owned());
    }
    if request
        .previous_units
        .iter()
        .any(|value| !value.is_finite())
        || request
            .contract_sizes
            .iter()
            .any(|value| !value.is_finite() || *value <= 0.0)
        || request
            .leverages
            .iter()
            .any(|value| !value.is_finite() || *value <= 0.0)
        || request
            .fee_rates
            .iter()
            .any(|value| !value.is_finite() || *value < 0.0)
        || request
            .slippage_rates
            .iter()
            .any(|value| !value.is_finite() || *value < 0.0)
        || request
            .min_qty
            .iter()
            .any(|value| !value.is_finite() || *value < 0.0)
        || request
            .min_notional
            .iter()
            .any(|value| !value.is_finite() || *value < 0.0)
    {
        return Err("portfolio target constraints are invalid".to_owned());
    }

    let mut reasons = (0..n)
        .map(|index| validation_reason(&request, index))
        .collect::<Vec<_>>();
    let valid = reasons
        .iter()
        .map(|reason| *reason == PortfolioTargetRejectReason::Accepted)
        .collect::<Vec<_>>();
    if !valid.iter().all(|value| *value) {
        for (index, reason) in reasons.iter_mut().enumerate() {
            if valid[index] {
                *reason = PortfolioTargetRejectReason::AtomicRollback;
            }
        }
        return Ok(rejected_market_target_execution(&request, reasons));
    }

    let mut simulated_units = request.previous_units.to_vec();
    let mut equity = request.equity - request.reserved_margin;
    let mut traded_notional = vec![0.0; n];
    let mut fees = vec![0.0; n];
    let mut slippage = vec![0.0; n];
    for index in 0..n {
        let delta = request.requested_units[index] - simulated_units[index];
        if delta.abs() <= EPSILON {
            continue;
        }
        let close = request.prices[index];
        let execution_price = market_execution_price(close, delta, request.slippage_rates[index]);
        let contract_size = request.contract_sizes[index];
        let old_initial =
            simulated_units[index].abs() * close * contract_size / request.leverages[index];
        let new_initial = (simulated_units[index] + delta).abs() * execution_price * contract_size
            / request.leverages[index];
        let notional = delta.abs() * execution_price * contract_size;
        let fee = notional * request.fee_rates[index];
        let current_initial = total_initial_margin(
            &simulated_units,
            request.prices,
            request.contract_sizes,
            request.leverages,
        );
        let required = fee + (new_initial - old_initial).max(0.0);
        if required > equity - current_initial + EPSILON {
            for reason in &mut reasons {
                if *reason == PortfolioTargetRejectReason::Accepted {
                    *reason = PortfolioTargetRejectReason::PostCostMargin;
                }
            }
            return Ok(rejected_market_target_execution(&request, reasons));
        }
        equity += delta * (close - execution_price) * contract_size - fee;
        simulated_units[index] += delta;
        traded_notional[index] = notional;
        fees[index] = fee;
        slippage[index] = delta.abs() * (execution_price - close).abs() * contract_size;
    }

    let initial_margin = margin_vector(
        &simulated_units,
        request.prices,
        request.contract_sizes,
        request.leverages,
    );
    // Maintenance is enforced by FullSession after commands. The target
    // contract deliberately leaves that canonical runtime gate in the engine
    // rather than inventing a second maintenance-ratio input here.
    let delta_qty = subtract(&simulated_units, request.previous_units);
    Ok(PortfolioTargetExecution {
        requested_units: request.requested_units.to_vec(),
        accepted_units: simulated_units,
        delta_qty,
        traded_notional,
        fees,
        slippage,
        initial_margin,
        rejection_reasons: reasons,
        policy: request.policy,
        available_equity_after: equity
            - sum(&margin_vector(
                request.requested_units,
                request.prices,
                request.contract_sizes,
                request.leverages,
            )),
    })
}

fn rejected_market_target_execution(
    request: &PortfolioTargetRequest<'_>,
    reasons: Vec<PortfolioTargetRejectReason>,
) -> PortfolioTargetExecution {
    let initial_margin = margin_vector(
        request.previous_units,
        request.prices,
        request.contract_sizes,
        request.leverages,
    );
    PortfolioTargetExecution {
        requested_units: request.requested_units.to_vec(),
        accepted_units: request.previous_units.to_vec(),
        delta_qty: vec![0.0; request.previous_units.len()],
        traded_notional: vec![0.0; request.previous_units.len()],
        fees: vec![0.0; request.previous_units.len()],
        slippage: vec![0.0; request.previous_units.len()],
        initial_margin: initial_margin.clone(),
        rejection_reasons: reasons,
        policy: request.policy,
        available_equity_after: request.equity - request.reserved_margin - sum(&initial_margin),
    }
}

fn total_initial_margin(
    units: &[f64],
    prices: &[f64],
    contract_sizes: &[f64],
    leverages: &[f64],
) -> f64 {
    margin_vector(units, prices, contract_sizes, leverages)
        .iter()
        .sum()
}

fn market_execution_price(close: f64, delta: f64, slippage_rate: f64) -> f64 {
    if delta > 0.0 {
        close * (1.0 + slippage_rate)
    } else {
        close * (1.0 - slippage_rate)
    }
}

/// Compile an accepted target result into canonical event commands. Direct
/// position mutation is deliberately impossible from this crate.
pub fn compile_target_delta_commands(
    symbols: &[SymbolId],
    previous_units: &[f64],
    execution: &PortfolioTargetExecution,
    external_id_start: i64,
) -> Result<Vec<OrderCommandV5>, String> {
    if symbols.len() != previous_units.len() || symbols.len() != execution.delta_qty.len() {
        return Err("portfolio command compiler vectors do not match".to_owned());
    }
    let mut commands = Vec::with_capacity(symbols.len());
    for index in 0..symbols.len() {
        let delta = execution.delta_qty[index];
        if delta.abs() <= EPSILON {
            continue;
        }
        let previous = previous_units[index];
        let accepted = execution.accepted_units[index];
        let reduce_only = is_reduction(previous, accepted);
        commands.push(OrderCommandV5 {
            action: CommandAction::Place,
            symbol: Some(symbols[index]),
            side: Some(if delta > 0.0 { Side::Buy } else { Side::Sell }),
            order_type: Some(OrderType::Market),
            tif: Some(TimeInForce::Gtc),
            reduce_only,
            external_id: ExternalOrderId(external_id_start + index as i64),
            target_id: ExternalOrderId(-1),
            parent_id: ExternalOrderId(-1),
            group_id: -1,
            oco_id: -1,
            activation: Some(ActivationPolicy::Immediate),
            command_index: index as u32,
            qty: delta.abs(),
            limit_price: 0.0,
            stop_price: 0.0,
            expire_bar: None,
        });
    }
    Ok(commands)
}

/// Materialize one accepted target delta into the shared ABI-0.5 event tape.
///
/// Targets are deliberately planned before command compilation, but accepted
/// deltas never mutate portfolio state directly: the returned tape is consumed
/// by `quantbt-engine::FullSession`, which owns matching, fees, slippage,
/// funding, margin, and lifecycle transitions. Bar zero is a frozen initial
/// snapshot in the P0 contract, so a rebalance command must target bar >= 1.
pub fn compile_target_delta_tape(
    n_bars: usize,
    command_bar: usize,
    symbols: &[SymbolId],
    previous_units: &[f64],
    execution: &PortfolioTargetExecution,
    external_id_start: i64,
) -> Result<CommandTapeV5, String> {
    if n_bars == 0 || command_bar == 0 || command_bar >= n_bars {
        return Err(
            "portfolio target tape requires command_bar in 1..prepared_market_bars".to_owned(),
        );
    }
    let commands =
        compile_target_delta_commands(symbols, previous_units, execution, external_id_start)?;
    let command_count = u32::try_from(commands.len())
        .map_err(|_| "portfolio target command count exceeds ABI range".to_owned())?;
    let mut offsets = vec![0_u32; n_bars + 1];
    for offset in offsets.iter_mut().skip(command_bar + 1) {
        *offset = command_count;
    }
    CommandTapeV5::new(offsets, commands).map_err(|error| error.to_string())
}

fn validation_reason(
    request: &PortfolioTargetRequest<'_>,
    index: usize,
) -> PortfolioTargetRejectReason {
    let target = request.requested_units[index];
    let price = request.prices[index];
    if !request.tradable[index] {
        PortfolioTargetRejectReason::NonTradable
    } else if request.stale[index] || !price.is_finite() || price <= 0.0 {
        PortfolioTargetRejectReason::StalePrice
    } else if !target.is_finite() {
        PortfolioTargetRejectReason::InvalidTarget
    } else {
        target_delta_validation_reason(
            request.previous_units[index],
            target,
            price,
            request.contract_sizes[index],
            request.min_qty[index],
            request.min_notional[index],
        )
    }
}

/// Whether a target only closes or reduces the existing signed inventory.
/// A reversal is not a pure reduction, even when its final magnitude is lower.
#[must_use]
pub fn is_reduction(previous: f64, target: f64) -> bool {
    target == 0.0 || (previous.signum() == target.signum() && target.abs() <= previous.abs())
}

/// Validate the actual delta of an already resolved/quantized target. Call
/// again after resizing or splitting a rebalance into separate orders. The
/// notional filter uses the close mark and the declared contract multiplier.
#[must_use]
pub fn target_delta_validation_reason(
    previous: f64,
    target: f64,
    price: f64,
    contract_size: f64,
    min_qty: f64,
    min_notional: f64,
) -> PortfolioTargetRejectReason {
    let quantity = (target - previous).abs();
    if quantity < EPSILON || is_reduction(previous, target) {
        PortfolioTargetRejectReason::Accepted
    } else if quantity + EPSILON < min_qty {
        PortfolioTargetRejectReason::MinQty
    } else if quantity * price * contract_size + EPSILON < min_notional {
        PortfolioTargetRejectReason::MinNotional
    } else {
        PortfolioTargetRejectReason::Accepted
    }
}

fn reduction_baseline(
    request: &PortfolioTargetRequest<'_>,
    prices: &[f64],
    valid: &[bool],
    reasons: &mut [PortfolioTargetRejectReason],
) -> (Vec<f64>, f64) {
    let previous = request.previous_units;
    let requested = request.requested_units;
    let mut accepted = previous.to_vec();
    let mut costs = 0.0;
    for index in 0..previous.len() {
        if valid[index]
            && (is_reduction(previous[index], requested[index])
                || (previous[index] != 0.0
                    && previous[index].signum() != requested[index].signum()))
        {
            let target = if is_reduction(previous[index], requested[index]) {
                requested[index]
            } else {
                0.0
            };
            let cost = (target - previous[index]).abs()
                * prices[index]
                * request.contract_sizes[index]
                * (request.fee_rates[index] + request.slippage_rates[index]);
            // Admit reductions in the existing symbol order. Keep affordable
            // earlier legs, and never fund a later leg from released IM alone.
            if costs + cost + request.reserved_margin <= request.equity + EPSILON {
                accepted[index] = target;
                costs += cost;
            } else {
                reasons[index] = PortfolioTargetRejectReason::PostCostMargin;
            }
        }
    }
    (accepted, costs)
}

fn subtract(left: &[f64], right: &[f64]) -> Vec<f64> {
    left.iter().zip(right).map(|(a, b)| a - b).collect()
}

fn margin_vector(
    units: &[f64],
    prices: &[f64],
    contract_sizes: &[f64],
    leverages: &[f64],
) -> Vec<f64> {
    (0..units.len())
        .map(|index| units[index].abs() * prices[index] * contract_sizes[index] / leverages[index])
        .collect()
}

fn cost_vector(
    delta: &[f64],
    prices: &[f64],
    contract_sizes: &[f64],
    fee_rates: &[f64],
    slippage_rates: &[f64],
) -> Vec<f64> {
    (0..delta.len())
        .map(|index| {
            delta[index].abs()
                * prices[index]
                * contract_sizes[index]
                * (fee_rates[index] + slippage_rates[index])
        })
        .collect()
}

fn sum(values: &[f64]) -> f64 {
    values.iter().sum()
}

#[cfg(test)]
mod tests {
    use super::*;
    use quantbt_engine::{FullMarketData, FullSession};
    use std::sync::Arc;

    fn request(policy: PortfolioMarginAllocationPolicy) -> PortfolioTargetRequest<'static> {
        PortfolioTargetRequest {
            previous_units: Box::leak(vec![1.0, -1.0].into_boxed_slice()),
            requested_units: Box::leak(vec![-1.0, 2.0].into_boxed_slice()),
            prices: Box::leak(vec![100.0, 50.0].into_boxed_slice()),
            equity: 1_000.0,
            contract_sizes: Box::leak(vec![1.0, 1.0].into_boxed_slice()),
            leverages: Box::leak(vec![5.0, 5.0].into_boxed_slice()),
            fee_rates: Box::leak(vec![0.001, 0.001].into_boxed_slice()),
            slippage_rates: Box::leak(vec![0.001, 0.001].into_boxed_slice()),
            tradable: Box::leak(vec![true, true].into_boxed_slice()),
            stale: Box::leak(vec![false, false].into_boxed_slice()),
            min_qty: Box::leak(vec![0.0, 0.0].into_boxed_slice()),
            min_notional: Box::leak(vec![0.0, 0.0].into_boxed_slice()),
            reserved_margin: 0.0,
            policy,
        }
    }

    fn single_request(
        previous: f64,
        target: f64,
        min_qty: f64,
        min_notional: f64,
        policy: PortfolioMarginAllocationPolicy,
    ) -> PortfolioTargetRequest<'static> {
        PortfolioTargetRequest {
            previous_units: Box::leak(vec![previous].into_boxed_slice()),
            requested_units: Box::leak(vec![target].into_boxed_slice()),
            prices: &[100.0],
            equity: 1_000.0,
            contract_sizes: &[1.0],
            leverages: &[1.0],
            fee_rates: &[0.0],
            slippage_rates: &[0.0],
            tradable: &[true],
            stale: &[false],
            min_qty: Box::leak(vec![min_qty].into_boxed_slice()),
            min_notional: Box::leak(vec![min_notional].into_boxed_slice()),
            reserved_margin: 0.0,
            policy,
        }
    }

    #[test]
    fn sequential_reduction_below_im_is_affordable_but_increases_remain_strict() {
        for target in [-18.0, -20.0] {
            let mut request = single_request(
                -19.0,
                target,
                0.0,
                0.0,
                PortfolioMarginAllocationPolicy::SequentialLegacy,
            );
            request.prices = &[110.0];
            request.equity = 1_809.24;
            request.fee_rates = &[0.0004];
            let result = execute_portfolio_target(request).unwrap();
            if target == -18.0 {
                assert_eq!(result.accepted_units, vec![-18.0]);
                assert!((result.fees[0] - 0.044).abs() < EPSILON);
                assert!((result.available_equity_after + 170.804).abs() < EPSILON);
                assert!(result.invariant_passes(EPSILON));
            } else {
                assert_eq!(result.accepted_units, vec![-19.0]);
                assert_eq!(
                    result.rejection_reasons,
                    vec![PortfolioTargetRejectReason::PostCostMargin]
                );
            }
        }
        let mut request = single_request(
            -19.0,
            -18.0,
            0.0,
            0.0,
            PortfolioMarginAllocationPolicy::SequentialLegacy,
        );
        request.equity = 0.01;
        request.fee_rates = &[0.0004];
        let result = execute_portfolio_target(request).unwrap();
        assert_eq!(result.accepted_units, vec![-19.0]);
        assert_eq!(result.fees, vec![0.0]);
        assert_eq!(
            result.rejection_reasons,
            vec![PortfolioTargetRejectReason::PostCostMargin]
        );
    }

    #[test]
    fn all_policies_accept_affordable_pure_reductions_below_im() {
        for policy in [
            PortfolioMarginAllocationPolicy::SequentialLegacy,
            PortfolioMarginAllocationPolicy::ReduceFirstThenIncrease,
            PortfolioMarginAllocationPolicy::ProRataToAvailableMargin,
            PortfolioMarginAllocationPolicy::AllOrNoneTarget,
        ] {
            let mut request = single_request(-19.0, -18.0, 18.5, 1_850.0, policy);
            request.prices = &[110.0];
            request.equity = 1_809.24;
            request.fee_rates = &[0.0004];
            let result = execute_portfolio_target(request).unwrap();
            assert_eq!(result.accepted_units, vec![-18.0], "{policy:?}");
            assert_eq!(
                result.rejection_reasons,
                vec![PortfolioTargetRejectReason::Accepted]
            );
            assert!((result.fees[0] - 0.044).abs() < EPSILON);
            assert!((result.available_equity_after + 170.804).abs() < EPSILON);
            assert!(result.invariant_passes(EPSILON));
        }
    }

    #[test]
    fn all_policies_require_reduction_fees_and_slippage_to_fit_equity() {
        for policy in [
            PortfolioMarginAllocationPolicy::SequentialLegacy,
            PortfolioMarginAllocationPolicy::ReduceFirstThenIncrease,
            PortfolioMarginAllocationPolicy::ProRataToAvailableMargin,
            PortfolioMarginAllocationPolicy::AllOrNoneTarget,
        ] {
            for equity in [39.0, 40.0] {
                let mut request = single_request(-1.0, -0.5, 0.0, 0.0, policy);
                request.prices = &[200.0];
                request.equity = equity;
                request.fee_rates = &[0.3];
                request.slippage_rates = &[0.1];
                let result = execute_portfolio_target(request).unwrap();
                if equity == 40.0 {
                    assert_eq!(result.accepted_units, vec![-0.5], "{policy:?}");
                    assert_eq!(result.fees, vec![30.0]);
                    assert_eq!(result.slippage, vec![10.0]);
                    assert!(result.invariant_passes(EPSILON));
                } else {
                    assert_eq!(result.accepted_units, vec![-1.0], "{policy:?}");
                    assert_eq!(result.fees, vec![0.0]);
                    assert_eq!(result.slippage, vec![0.0]);
                    assert_eq!(
                        result.rejection_reasons,
                        vec![
                            if policy == PortfolioMarginAllocationPolicy::AllOrNoneTarget {
                                PortfolioTargetRejectReason::AtomicRollback
                            } else {
                                PortfolioTargetRejectReason::PostCostMargin
                            }
                        ]
                    );
                }
            }
        }
    }

    #[test]
    fn reduction_cost_budget_preserves_prior_admissions_unless_policy_is_atomic() {
        for policy in [
            PortfolioMarginAllocationPolicy::SequentialLegacy,
            PortfolioMarginAllocationPolicy::ReduceFirstThenIncrease,
            PortfolioMarginAllocationPolicy::ProRataToAvailableMargin,
            PortfolioMarginAllocationPolicy::AllOrNoneTarget,
        ] {
            let mut request = request(policy);
            request.previous_units = &[1.0, 1.0];
            request.requested_units = &[0.5, 0.5];
            request.prices = &[100.0, 100.0];
            request.leverages = &[1.0, 1.0];
            request.equity = 60.0;
            request.reserved_margin = 10.0;
            request.fee_rates = &[0.6, 0.6];
            request.slippage_rates = &[0.1, 0.1];
            let result = execute_portfolio_target(request).unwrap();
            if policy == PortfolioMarginAllocationPolicy::AllOrNoneTarget {
                assert_eq!(result.accepted_units, vec![1.0, 1.0]);
                assert_eq!(result.fees, vec![0.0, 0.0]);
                assert_eq!(
                    result.rejection_reasons,
                    vec![PortfolioTargetRejectReason::AtomicRollback; 2]
                );
            } else {
                assert_eq!(result.accepted_units, vec![0.5, 1.0], "{policy:?}");
                assert_eq!(result.fees, vec![30.0, 0.0]);
                assert_eq!(result.slippage, vec![5.0, 0.0]);
                assert_eq!(
                    result.rejection_reasons,
                    vec![
                        PortfolioTargetRejectReason::Accepted,
                        PortfolioTargetRejectReason::PostCostMargin,
                    ]
                );
            }
            assert!(result.invariant_passes(EPSILON));
        }
    }

    #[test]
    fn pro_rata_reserves_reduction_costs_before_scaling_increases() {
        let mut request = request(PortfolioMarginAllocationPolicy::ProRataToAvailableMargin);
        request.previous_units = &[1.0, 0.0];
        request.requested_units = &[0.0, 2.0];
        request.prices = &[100.0, 100.0];
        request.leverages = &[1.0, 1.0];
        request.equity = 220.0;
        request.fee_rates = &[0.1, 0.1];
        request.slippage_rates = &[0.1, 0.1];
        let result = execute_portfolio_target(request).unwrap();
        assert_eq!(result.accepted_units[0], 0.0);
        assert!((result.accepted_units[1] - 5.0 / 3.0).abs() < EPSILON);
        assert_eq!(result.fees[0], 10.0);
        assert_eq!(result.slippage[0], 10.0);
        assert!(result.available_equity_after.abs() < EPSILON);
        assert!(result.invariant_passes(EPSILON));
    }

    #[test]
    fn pro_rata_unaffordable_reversal_close_preserves_existing_position() {
        let mut request = single_request(
            1.0,
            -0.5,
            0.0,
            0.0,
            PortfolioMarginAllocationPolicy::ProRataToAvailableMargin,
        );
        request.equity = 40.0;
        request.fee_rates = &[0.6];
        let result = execute_portfolio_target(request).unwrap();
        assert_eq!(result.accepted_units, vec![1.0]);
        assert_eq!(result.fees, vec![0.0]);
        assert_eq!(
            result.rejection_reasons,
            vec![PortfolioTargetRejectReason::PostCostMargin]
        );
    }

    #[test]
    fn planner_policies_validate_actual_increasing_delta_and_exempt_reductions() {
        for policy in [
            PortfolioMarginAllocationPolicy::SequentialLegacy,
            PortfolioMarginAllocationPolicy::ReduceFirstThenIncrease,
            PortfolioMarginAllocationPolicy::ProRataToAvailableMargin,
            PortfolioMarginAllocationPolicy::AllOrNoneTarget,
        ] {
            for sign in [-1.0, 1.0] {
                for (min_qty, min_notional, reason) in [
                    (0.5, 0.0, PortfolioTargetRejectReason::MinQty),
                    (0.0, 50.0, PortfolioTargetRejectReason::MinNotional),
                ] {
                    for next in [1.1, 0.1, 0.0, 1.5, -0.1] {
                        let result = execute_portfolio_target(single_request(
                            sign,
                            sign * next,
                            min_qty,
                            min_notional,
                            policy,
                        ))
                        .unwrap();
                        let expected = sign * if next == 1.1 { 1.0 } else { next };
                        assert!((result.accepted_units[0] - expected).abs() < EPSILON);
                        assert_eq!(
                            result.rejection_reasons[0],
                            if next == 1.1 {
                                reason
                            } else {
                                PortfolioTargetRejectReason::Accepted
                            }
                        );
                    }
                }
            }
        }
    }

    #[test]
    fn pro_rata_resizing_rechecks_the_final_delta_minimums() {
        for (min_qty, min_notional, reason) in [
            (0.5, 0.0, PortfolioTargetRejectReason::MinQty),
            (0.0, 50.0, PortfolioTargetRejectReason::MinNotional),
        ] {
            let mut request = single_request(
                1.0,
                2.0,
                min_qty,
                min_notional,
                PortfolioMarginAllocationPolicy::ProRataToAvailableMargin,
            );
            request.equity = 130.0;
            let result = execute_portfolio_target(request).unwrap();
            assert_eq!(result.accepted_units, vec![1.0]);
            assert_eq!(result.rejection_reasons, vec![reason]);
        }
    }

    #[test]
    fn market_target_helper_uses_the_same_delta_filters() {
        for (min_qty, min_notional, reason) in [
            (0.5, 0.0, PortfolioTargetRejectReason::MinQty),
            (0.0, 50.0, PortfolioTargetRejectReason::MinNotional),
        ] {
            // Eighth-unit targets keep the engine's position += delta exact.
            for target in [1.125, 0.125, 0.0, -0.125] {
                let result = execute_portfolio_target_market_all_or_none(single_request(
                    1.0,
                    target,
                    min_qty,
                    min_notional,
                    PortfolioMarginAllocationPolicy::AllOrNoneTarget,
                ))
                .unwrap();
                assert_eq!(
                    result.accepted_units,
                    vec![if target == 1.125 { 1.0 } else { target }]
                );
                assert_eq!(
                    result.rejection_reasons[0],
                    if target == 1.125 {
                        reason
                    } else {
                        PortfolioTargetRejectReason::Accepted
                    }
                );
            }
        }
    }

    #[test]
    fn minimum_notional_uses_delta_and_contract_multiplier() {
        assert_eq!(
            target_delta_validation_reason(1.0, 1.1, 100.0, 10.0, 0.0, 50.0),
            PortfolioTargetRejectReason::Accepted,
        );
        assert_eq!(
            target_delta_validation_reason(1.0, 1.01, 100.0, 10.0, 0.0, 50.0),
            PortfolioTargetRejectReason::MinNotional,
        );
    }

    #[test]
    fn sequential_planner_keeps_symbol_order_and_does_not_fund_increases_from_im_deficit() {
        let mut request = request(PortfolioMarginAllocationPolicy::SequentialLegacy);
        request.previous_units = &[-19.0, 0.0];
        request.requested_units = &[-18.0, 0.1];
        request.prices = &[110.0, 100.0];
        request.leverages = &[1.0, 1.0];
        request.fee_rates = &[0.0004, 0.0004];
        request.slippage_rates = &[0.0, 0.0];
        request.equity = 1_809.24;
        let result = execute_portfolio_target(request.clone()).unwrap();
        assert_eq!(result.accepted_units, vec![-18.0, 0.0]);
        assert_eq!(
            result.rejection_reasons[1],
            PortfolioTargetRejectReason::PostCostMargin
        );
        request.previous_units = &[0.0, 9.0];
        request.requested_units = &[5.0, 0.0];
        request.prices = &[100.0, 100.0];
        request.fee_rates = &[0.0, 0.0];
        request.equity = 1_000.0;
        let sequential = execute_portfolio_target(request.clone()).unwrap();
        assert_eq!(sequential.accepted_units, vec![0.0, 0.0]);
        request.policy = PortfolioMarginAllocationPolicy::ReduceFirstThenIncrease;
        let reduce_first = execute_portfolio_target(request).unwrap();
        assert_eq!(reduce_first.accepted_units, vec![5.0, 0.0]);
    }

    #[test]
    fn target_execution_preserves_delta_fee_and_margin_identities() {
        let result =
            execute_portfolio_target(request(PortfolioMarginAllocationPolicy::SequentialLegacy))
                .unwrap();
        assert_eq!(result.delta_qty, vec![-2.0, 3.0]);
        assert_eq!(result.traded_notional, vec![200.0, 150.0]);
        assert_eq!(result.fees, vec![0.2, 0.15]);
        assert!(result.invariant_passes(EPSILON));
        let commands =
            compile_target_delta_commands(&[SymbolId(0), SymbolId(1)], &[1.0, -1.0], &result, 10)
                .unwrap();
        assert_eq!(commands.len(), 2);
        assert!(!commands[0].reduce_only);
    }

    #[test]
    fn atomic_target_rejects_all_siblings_after_post_cost_margin_failure() {
        let mut request = request(PortfolioMarginAllocationPolicy::AllOrNoneTarget);
        request.equity = 10.0;
        let result = execute_portfolio_target(request).unwrap();
        assert_eq!(result.accepted_units, vec![1.0, -1.0]);
        assert!(
            result
                .rejection_reasons
                .iter()
                .all(|reason| *reason == PortfolioTargetRejectReason::AtomicRollback)
        );
    }

    #[test]
    fn stale_price_is_explicit_and_never_becomes_a_zero_price_trade() {
        let mut request = request(PortfolioMarginAllocationPolicy::SequentialLegacy);
        request.prices = Box::leak(vec![f64::NAN, 50.0].into_boxed_slice());
        let result = execute_portfolio_target(request).unwrap();
        assert_eq!(
            result.rejection_reasons[0],
            PortfolioTargetRejectReason::StalePrice
        );
        assert_eq!(result.accepted_units[0], 1.0);
    }

    #[test]
    fn accepted_target_tape_executes_through_the_shared_event_account_core() {
        let execution =
            execute_portfolio_target(request(PortfolioMarginAllocationPolicy::SequentialLegacy))
                .unwrap();
        let tape = compile_target_delta_tape(
            3,
            1,
            &[SymbolId(0), SymbolId(1)],
            &[1.0, -1.0],
            &execution,
            10,
        )
        .unwrap();
        assert_eq!(tape.command_count(), 2);
        let market = FullMarketData::new(
            vec![0, 1, 2],
            vec![100.0, 50.0, 100.0, 50.0, 100.0, 50.0],
            vec![101.0, 51.0, 101.0, 51.0, 101.0, 51.0],
            vec![99.0, 49.0, 99.0, 49.0, 99.0, 49.0],
            vec![100.0, 50.0, 100.0, 50.0, 100.0, 50.0],
            vec![1_000.0; 6],
            vec![0.0; 6],
            vec![false; 3],
            2,
        )
        .unwrap();
        let mut session = FullSession::new(
            Arc::new(market),
            vec![1.0, 1.0],
            vec![5.0, 5.0],
            vec![0.001, 0.001],
            1_000.0,
            0.005,
            0.001,
            false,
        )
        .unwrap();
        let output = session.run_typed_audit(&tape).unwrap();
        assert_eq!(output.fill_count, 2);
        assert!(output.total_fee > 0.0);
        assert!(output.total_turnover > 0.0);
        assert_eq!(output.final_positions, vec![-2.0, 3.0]);
    }
}
