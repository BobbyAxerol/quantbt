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
            && self.available_equity_after >= -tolerance
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
            if !valid.iter().all(|value| *value)
                || sum(&margin) + sum(&costs) + request.reserved_margin > request.equity + EPSILON
            {
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
            accepted = reduction_baseline(request.previous_units, request.requested_units, &valid);
            let remaining = (request.equity
                - request.reserved_margin
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
                .filter(|(index, _)| valid[*index])
                .map(|(_, value)| *value)
                .sum::<f64>();
            let scale = if total_required > 0.0 {
                (remaining / total_required).min(1.0)
            } else {
                1.0
            };
            for index in 0..n {
                if valid[index] {
                    accepted[index] += increase[index] * scale;
                    if scale < 1.0 && increase[index].abs() > EPSILON {
                        reasons[index] = PortfolioTargetRejectReason::PostCostMargin;
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
                let required = sum(&margin_vector(
                    &candidate,
                    &valuation_prices,
                    request.contract_sizes,
                    request.leverages,
                )) + sum(&costs)
                    + request.reserved_margin;
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
    } else if target != 0.0 && target.abs() + EPSILON < request.min_qty[index] {
        PortfolioTargetRejectReason::MinQty
    } else if target != 0.0
        && target.abs() * price * request.contract_sizes[index] + EPSILON
            < request.min_notional[index]
    {
        PortfolioTargetRejectReason::MinNotional
    } else {
        PortfolioTargetRejectReason::Accepted
    }
}

fn is_reduction(previous: f64, target: f64) -> bool {
    target == 0.0 || (previous.signum() == target.signum() && target.abs() <= previous.abs())
}

fn reduction_baseline(previous: &[f64], requested: &[f64], valid: &[bool]) -> Vec<f64> {
    let mut accepted = previous.to_vec();
    for index in 0..previous.len() {
        if valid[index]
            && (is_reduction(previous[index], requested[index])
                || (previous[index] != 0.0
                    && previous[index].signum() != requested[index].signum()))
        {
            accepted[index] = if is_reduction(previous[index], requested[index]) {
                requested[index]
            } else {
                0.0
            };
        }
    }
    accepted
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
