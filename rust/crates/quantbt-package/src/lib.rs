//! Transactional multi-leg package planning over the shared event core.
//!
//! Package planning does not mutate a separate account. It performs the
//! deterministic reservation/preflight contract, then compiles accepted legs
//! to canonical typed order commands for `quantbt-engine` to execute.

use quantbt_domain::commands::{CommandTapeV5, OrderCommandV5};
use quantbt_domain::enums::{ActivationPolicy, CommandAction, OrderType, Side, TimeInForce};
use quantbt_domain::ids::{ExternalOrderId, SymbolId};

pub mod v2;
pub use v2::{
    LegQuantitySourceV1, PackageExecutionCommandV2, PackageExecutionPolicyV2,
    PackageExecutionResultV2, PackageIntentV2, PackageLegExecutionV2, PackageLegIntentV2,
    PackageMarketExecutionRequestV2, PackageRejectReasonV2, PackageStateV2, ResidualExposureV1,
    ResidualReasonCodeV1, ResidualRiskPolicyV1, abort_package_market_v2,
    compile_package_commands_v2, execute_package_market_v2,
};

const EPSILON: f64 = 1e-12;

#[repr(transparent)]
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
pub struct PackageId(pub u64);

#[repr(u8)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PackagePolicy {
    Sequential = 0,
    BestEffort = 1,
    AtomicBarSimulation = 2,
    HedgeAfterPrimary = 3,
}

impl TryFrom<u8> for PackagePolicy {
    type Error = String;

    fn try_from(value: u8) -> Result<Self, Self::Error> {
        match value {
            0 => Ok(Self::Sequential),
            1 => Ok(Self::BestEffort),
            2 => Ok(Self::AtomicBarSimulation),
            3 => Ok(Self::HedgeAfterPrimary),
            _ => Err("unsupported package policy".to_owned()),
        }
    }
}

#[repr(u8)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PackageState {
    Planned = 0,
    PreflightAccepted = 1,
    PreflightRejected = 2,
    Reserved = 3,
    Committing = 4,
    Filled = 5,
    Partial = 6,
    Aborted = 7,
    Compensating = 8,
    Closed = 9,
}

#[repr(u8)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PackageRejectReason {
    Accepted = 0,
    InvalidLeg = 1,
    StaleMarket = 2,
    MinQty = 3,
    MinNotional = 4,
    PostCostMargin = 5,
    AtomicRollback = 6,
    SiblingPreflightRejected = 7,
    PrimaryRejected = 8,
}

impl PackageRejectReason {
    #[must_use]
    pub const fn name(self) -> &'static str {
        match self {
            Self::Accepted => "ACCEPTED",
            Self::InvalidLeg => "INVALID_LEG",
            Self::StaleMarket => "STALE_MARKET",
            Self::MinQty => "MIN_QTY",
            Self::MinNotional => "MIN_NOTIONAL",
            Self::PostCostMargin => "POST_COST_MARGIN",
            Self::AtomicRollback => "ATOMIC_ROLLBACK",
            Self::SiblingPreflightRejected => "SIBLING_PREFLIGHT_REJECTED",
            Self::PrimaryRejected => "PRIMARY_REJECTED",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PackageEventKind {
    Plan,
    PreflightAccepted,
    PreflightRejected,
    Reserve,
    Commit,
    Filled,
    Partial,
    Compensating,
    Abort,
    Release,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PackageLegRef {
    pub order_id: ExternalOrderId,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PackagePlan {
    pub id: PackageId,
    pub policy: PackagePolicy,
    pub legs: Box<[PackageLegRef]>,
}

impl PackagePlan {
    #[must_use]
    pub fn is_multi_leg(&self) -> bool {
        self.legs.len() > 1
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct PackageLegRequest {
    pub order_id: ExternalOrderId,
    pub symbol: SymbolId,
    pub signed_qty: f64,
    pub price: f64,
    pub initial_margin: f64,
    pub fee_rate: f64,
    pub source_age_ns: i64,
    pub venue_code: u16,
    pub venue_sequence: u32,
    pub min_qty: f64,
    pub min_notional: f64,
    pub contract_size: f64,
}

#[derive(Clone, Debug, PartialEq)]
pub struct PackageExecutionResult {
    pub package_id: PackageId,
    pub policy: PackagePolicy,
    pub final_state: PackageState,
    pub accepted: Vec<bool>,
    pub rejection_reasons: Vec<PackageRejectReason>,
    pub transitions: Vec<PackageEventKind>,
    pub reserved_margin: f64,
    pub released_margin: f64,
    pub package_fee: f64,
    pub residual_notional: f64,
}

/// Exact, bounded market-order request used by the promoted native atomic
/// package route.  The caller supplies close valuation prices from the shared
/// `FullSession` and the current account position vector; this crate performs
/// no account mutation and never owns a second ledger.
#[derive(Clone, Debug)]
pub struct PackageMarketExecutionRequest<'a> {
    pub package_id: PackageId,
    pub legs: &'a [PackageLegRequest],
    pub previous_units: &'a [f64],
    pub close_prices: &'a [f64],
    pub contract_sizes: &'a [f64],
    pub leverages: &'a [f64],
    pub fee_rates: &'a [f64],
    pub slippage_rate: f64,
    pub equity: f64,
    pub policy: PackagePolicy,
    pub max_staleness_ns: i64,
}

impl PackageExecutionResult {
    #[must_use]
    pub fn invariants_pass(&self, tolerance: f64) -> bool {
        let atomic_clean = !(self.policy == PackagePolicy::AtomicBarSimulation
            && matches!(
                self.final_state,
                PackageState::Aborted | PackageState::PreflightRejected
            )
            && self.accepted.iter().any(|accepted| *accepted));
        atomic_clean
            && (self.reserved_margin - self.released_margin).abs() <= tolerance
            && self.package_fee.is_finite()
            && self.residual_notional.is_finite()
    }
}

/// Execute deterministic package preflight/reservation/commit planning. This
/// is an OHLC bar-transaction model, not a venue-native atomicity guarantee.
pub fn execute_package_transaction(
    package_id: PackageId,
    legs: &[PackageLegRequest],
    available_equity: f64,
    policy: PackagePolicy,
    max_staleness_ns: i64,
) -> Result<PackageExecutionResult, String> {
    if legs.is_empty() || !available_equity.is_finite() || available_equity < 0.0 {
        return Err("package requires legs and finite non-negative available equity".to_owned());
    }
    let mut transitions = vec![PackageEventKind::Plan];
    let mut reasons = legs
        .iter()
        .map(|leg| validate_leg(leg, max_staleness_ns))
        .collect::<Vec<_>>();
    let valid = reasons
        .iter()
        .map(|reason| *reason == PackageRejectReason::Accepted)
        .collect::<Vec<_>>();
    let margins = legs
        .iter()
        .map(|leg| leg.initial_margin.max(0.0))
        .collect::<Vec<_>>();
    let fees = legs
        .iter()
        .map(|leg| leg.signed_qty.abs() * leg.price * leg.contract_size * leg.fee_rate)
        .collect::<Vec<_>>();
    let required = margins
        .iter()
        .zip(fees.iter())
        .map(|(margin, fee)| margin + fee)
        .collect::<Vec<_>>();

    let mut accepted = vec![false; legs.len()];
    if policy == PackagePolicy::AtomicBarSimulation {
        if valid.iter().all(|value| *value)
            && required.iter().sum::<f64>() <= available_equity + EPSILON
        {
            accepted.fill(true);
        } else {
            for index in 0..legs.len() {
                if valid[index] {
                    reasons[index] = if valid.iter().all(|value| *value) {
                        PackageRejectReason::AtomicRollback
                    } else {
                        PackageRejectReason::SiblingPreflightRejected
                    };
                }
            }
        }
    } else {
        let mut remaining = available_equity;
        for index in 0..legs.len() {
            if valid[index] && required[index] <= remaining + EPSILON {
                accepted[index] = true;
                remaining -= required[index];
            } else if valid[index] {
                reasons[index] = PackageRejectReason::PostCostMargin;
            }
        }
        if policy == PackagePolicy::HedgeAfterPrimary && !accepted[0] {
            for index in 1..legs.len() {
                accepted[index] = false;
                reasons[index] = PackageRejectReason::PrimaryRejected;
            }
        }
    }

    let (final_state, reserved_margin, released_margin) = if !accepted.iter().any(|value| *value) {
        transitions.push(PackageEventKind::PreflightRejected);
        transitions.push(PackageEventKind::Abort);
        (PackageState::Aborted, 0.0, 0.0)
    } else {
        transitions.push(PackageEventKind::PreflightAccepted);
        let reserved = margins
            .iter()
            .enumerate()
            .filter(|(index, _)| accepted[*index])
            .map(|(_, margin)| *margin)
            .sum::<f64>();
        transitions.push(PackageEventKind::Reserve);
        transitions.push(PackageEventKind::Commit);
        let state = if accepted.iter().all(|value| *value) {
            transitions.push(PackageEventKind::Filled);
            PackageState::Filled
        } else {
            transitions.push(PackageEventKind::Partial);
            if policy == PackagePolicy::HedgeAfterPrimary {
                transitions.push(PackageEventKind::Compensating);
            }
            PackageState::Partial
        };
        transitions.push(PackageEventKind::Release);
        (state, reserved, reserved)
    };
    let package_fee = fees
        .iter()
        .enumerate()
        .filter(|(index, _)| accepted[*index])
        .map(|(_, fee)| *fee)
        .sum::<f64>();
    let residual_notional = legs
        .iter()
        .enumerate()
        .filter(|(index, _)| accepted[*index])
        .map(|(_, leg)| leg.signed_qty * leg.price * leg.contract_size)
        .sum::<f64>();
    Ok(PackageExecutionResult {
        package_id,
        policy,
        final_state,
        accepted,
        rejection_reasons: reasons,
        transitions,
        reserved_margin,
        released_margin,
        package_fee,
        residual_notional,
    })
}

/// Resolve one same-bar all-or-none package against the exact sequential
/// market-order margin gate used by the native event engine.
///
/// Atomicity here is explicitly *bar-transaction atomicity*: all legs are
/// accepted and submitted together, or no leg is submitted. It is not a claim
/// of exchange-native order-list atomicity, partial fills, queue priority, or
/// cross-venue settlement guarantees.
pub fn execute_package_market_atomic(
    request: PackageMarketExecutionRequest<'_>,
) -> Result<PackageExecutionResult, String> {
    if request.policy != PackagePolicy::AtomicBarSimulation {
        return Err(
            "native market package execution supports only atomic_bar_simulation".to_owned(),
        );
    }
    let n_symbols = request.previous_units.len();
    if request.legs.is_empty()
        || request.close_prices.len() != n_symbols
        || request.contract_sizes.len() != n_symbols
        || request.leverages.len() != n_symbols
        || request.fee_rates.len() != n_symbols
        || !request.equity.is_finite()
        || request.equity <= 0.0
        || !request.slippage_rate.is_finite()
        || request.slippage_rate < 0.0
    {
        return Err("native market package request has invalid account dimensions".to_owned());
    }
    if request
        .previous_units
        .iter()
        .any(|value| !value.is_finite())
        || request
            .close_prices
            .iter()
            .any(|value| !value.is_finite() || *value <= 0.0)
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
    {
        return Err("native market package request has invalid instrument inputs".to_owned());
    }
    if request
        .legs
        .iter()
        .any(|leg| leg.symbol.0 as usize >= n_symbols)
        || request
            .legs
            .windows(2)
            .any(|pair| pair[0].venue_sequence > pair[1].venue_sequence)
    {
        return Err(
            "native atomic package legs must use known symbols and deterministic sequence"
                .to_owned(),
        );
    }

    let mut reasons = request
        .legs
        .iter()
        .map(|leg| validate_leg(leg, request.max_staleness_ns))
        .collect::<Vec<_>>();
    let valid = reasons
        .iter()
        .map(|reason| *reason == PackageRejectReason::Accepted)
        .collect::<Vec<_>>();
    if !valid.iter().all(|accepted| *accepted) {
        for (index, reason) in reasons.iter_mut().enumerate() {
            if valid[index] {
                *reason = PackageRejectReason::SiblingPreflightRejected;
            }
        }
        return Ok(rejected_market_package(request.package_id, reasons));
    }

    let mut units = request.previous_units.to_vec();
    let mut equity = request.equity;
    let mut fees = 0.0;
    for leg in request.legs {
        let symbol = leg.symbol.0 as usize;
        let close = request.close_prices[symbol];
        let execution_price = if leg.signed_qty > 0.0 {
            close * (1.0 + request.slippage_rate)
        } else {
            close * (1.0 - request.slippage_rate)
        };
        if !execution_price.is_finite() || execution_price <= 0.0 {
            return Err("native market package execution price is invalid".to_owned());
        }
        let contract_size = request.contract_sizes[symbol];
        let old_initial = units[symbol].abs() * close * contract_size / request.leverages[symbol];
        let new_initial = (units[symbol] + leg.signed_qty).abs() * execution_price * contract_size
            / request.leverages[symbol];
        let fee =
            leg.signed_qty.abs() * execution_price * contract_size * request.fee_rates[symbol];
        let current_initial = total_initial_margin(
            &units,
            request.close_prices,
            request.contract_sizes,
            request.leverages,
        );
        if fee + (new_initial - old_initial).max(0.0) > equity - current_initial + EPSILON {
            reasons.fill(PackageRejectReason::PostCostMargin);
            return Ok(rejected_market_package(request.package_id, reasons));
        }
        equity += leg.signed_qty * (close - execution_price) * contract_size - fee;
        units[symbol] += leg.signed_qty;
        fees += fee;
    }
    let reserved_margin = total_initial_margin(
        &units,
        request.close_prices,
        request.contract_sizes,
        request.leverages,
    );
    let residual_notional = request
        .legs
        .iter()
        .map(|leg| {
            leg.signed_qty
                * request.close_prices[leg.symbol.0 as usize]
                * request.contract_sizes[leg.symbol.0 as usize]
        })
        .sum();
    Ok(PackageExecutionResult {
        package_id: request.package_id,
        policy: request.policy,
        final_state: PackageState::Filled,
        accepted: vec![true; request.legs.len()],
        rejection_reasons: vec![PackageRejectReason::Accepted; request.legs.len()],
        transitions: vec![
            PackageEventKind::Plan,
            PackageEventKind::PreflightAccepted,
            PackageEventKind::Reserve,
            PackageEventKind::Commit,
            PackageEventKind::Filled,
            PackageEventKind::Release,
        ],
        reserved_margin,
        released_margin: reserved_margin,
        package_fee: fees,
        residual_notional,
    })
}

fn rejected_market_package(
    package_id: PackageId,
    reasons: Vec<PackageRejectReason>,
) -> PackageExecutionResult {
    PackageExecutionResult {
        package_id,
        policy: PackagePolicy::AtomicBarSimulation,
        final_state: PackageState::Aborted,
        accepted: vec![false; reasons.len()],
        rejection_reasons: reasons,
        transitions: vec![
            PackageEventKind::Plan,
            PackageEventKind::PreflightRejected,
            PackageEventKind::Abort,
            PackageEventKind::Release,
        ],
        reserved_margin: 0.0,
        released_margin: 0.0,
        package_fee: 0.0,
        residual_notional: 0.0,
    }
}

fn total_initial_margin(
    units: &[f64],
    close_prices: &[f64],
    contract_sizes: &[f64],
    leverages: &[f64],
) -> f64 {
    units
        .iter()
        .enumerate()
        .map(|(symbol, units)| {
            units.abs() * close_prices[symbol] * contract_sizes[symbol] / leverages[symbol]
        })
        .sum()
}

/// Compile only accepted preflight legs to canonical market commands. The
/// execution core decides actual fill price/fee/lifecycle from the market tape.
pub fn compile_package_commands(
    package_id: PackageId,
    legs: &[PackageLegRequest],
    result: &PackageExecutionResult,
) -> Result<Vec<OrderCommandV5>, String> {
    if result.package_id != package_id || result.accepted.len() != legs.len() {
        return Err("package command compiler result does not match legs".to_owned());
    }
    let mut commands = Vec::new();
    for (index, leg) in legs.iter().enumerate() {
        if !result.accepted[index] {
            continue;
        }
        commands.push(OrderCommandV5 {
            action: CommandAction::Place,
            symbol: Some(leg.symbol),
            side: Some(if leg.signed_qty > 0.0 {
                Side::Buy
            } else {
                Side::Sell
            }),
            order_type: Some(OrderType::Market),
            tif: Some(TimeInForce::Gtc),
            reduce_only: false,
            external_id: leg.order_id,
            target_id: ExternalOrderId(-1),
            parent_id: ExternalOrderId(-1),
            group_id: package_id.0 as i64,
            oco_id: -1,
            activation: Some(ActivationPolicy::Immediate),
            command_index: index as u32,
            qty: leg.signed_qty.abs(),
            limit_price: 0.0,
            stop_price: 0.0,
            expire_bar: None,
        });
    }
    Ok(commands)
}

/// Compile an accepted package transaction into one canonical event tape.
///
/// The package planner owns reservation and policy decisions; the shared
/// `FullSession` then owns actual OHLC fills, costs, and order lifecycle. This
/// remains an explicit bar-transaction simulation contract, never a claim of
/// exchange-native atomic execution. Bar zero is intentionally unavailable
/// because the P0 engine treats it as an initial snapshot.
pub fn compile_package_tape(
    n_bars: usize,
    command_bar: usize,
    package_id: PackageId,
    legs: &[PackageLegRequest],
    result: &PackageExecutionResult,
) -> Result<CommandTapeV5, String> {
    if n_bars == 0 || command_bar == 0 || command_bar >= n_bars {
        return Err("package tape requires command_bar in 1..prepared_market_bars".to_owned());
    }
    let commands = compile_package_commands(package_id, legs, result)?;
    let command_count = u32::try_from(commands.len())
        .map_err(|_| "package command count exceeds ABI range".to_owned())?;
    let mut offsets = vec![0_u32; n_bars + 1];
    for offset in offsets.iter_mut().skip(command_bar + 1) {
        *offset = command_count;
    }
    CommandTapeV5::new(offsets, commands).map_err(|error| error.to_string())
}

fn validate_leg(leg: &PackageLegRequest, max_staleness_ns: i64) -> PackageRejectReason {
    let values = [
        leg.signed_qty,
        leg.price,
        leg.initial_margin,
        leg.fee_rate,
        leg.contract_size,
        leg.min_qty,
        leg.min_notional,
    ];
    if values.iter().any(|value| !value.is_finite())
        || leg.signed_qty == 0.0
        || leg.price <= 0.0
        || leg.initial_margin < 0.0
        || leg.fee_rate < 0.0
        || leg.contract_size <= 0.0
        || leg.min_qty < 0.0
        || leg.min_notional < 0.0
    {
        PackageRejectReason::InvalidLeg
    } else if max_staleness_ns >= 0 && leg.source_age_ns > max_staleness_ns {
        PackageRejectReason::StaleMarket
    } else if leg.signed_qty.abs() + EPSILON < leg.min_qty {
        PackageRejectReason::MinQty
    } else if leg.signed_qty.abs() * leg.price * leg.contract_size + EPSILON < leg.min_notional {
        PackageRejectReason::MinNotional
    } else {
        PackageRejectReason::Accepted
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use quantbt_engine::{FullMarketData, FullSession};
    use std::sync::Arc;

    fn legs() -> [PackageLegRequest; 2] {
        [
            PackageLegRequest {
                order_id: ExternalOrderId(10),
                symbol: SymbolId(0),
                signed_qty: 1.0,
                price: 100.0,
                initial_margin: 20.0,
                fee_rate: 0.001,
                source_age_ns: 0,
                venue_code: 1,
                venue_sequence: 0,
                min_qty: 0.0,
                min_notional: 0.0,
                contract_size: 1.0,
            },
            PackageLegRequest {
                order_id: ExternalOrderId(11),
                symbol: SymbolId(1),
                signed_qty: -2.0,
                price: 50.0,
                initial_margin: 20.0,
                fee_rate: 0.001,
                source_age_ns: 0,
                venue_code: 2,
                venue_sequence: 0,
                min_qty: 0.0,
                min_notional: 0.0,
                contract_size: 1.0,
            },
        ]
    }

    #[test]
    fn atomic_package_is_all_or_none_and_reservation_reconciles() {
        let legs = legs();
        let result = execute_package_transaction(
            PackageId(7),
            &legs,
            100.0,
            PackagePolicy::AtomicBarSimulation,
            0,
        )
        .unwrap();
        assert_eq!(result.final_state, PackageState::Filled);
        assert_eq!(result.accepted, vec![true, true]);
        assert!(result.invariants_pass(EPSILON));
        assert_eq!(
            compile_package_commands(PackageId(7), &legs, &result)
                .unwrap()
                .len(),
            2
        );
    }

    #[test]
    fn atomic_package_does_not_leak_a_partial_leg_when_preflight_fails() {
        let mut legs = legs();
        legs[1].source_age_ns = 10;
        let result = execute_package_transaction(
            PackageId(8),
            &legs,
            100.0,
            PackagePolicy::AtomicBarSimulation,
            0,
        )
        .unwrap();
        assert_eq!(result.final_state, PackageState::Aborted);
        assert_eq!(result.accepted, vec![false, false]);
        assert_eq!(
            result.rejection_reasons[0],
            PackageRejectReason::SiblingPreflightRejected
        );
        assert_eq!(
            result.rejection_reasons[1],
            PackageRejectReason::StaleMarket
        );
    }

    #[test]
    fn best_effort_records_residual_and_hedge_after_primary_does_not_open_orphans() {
        let legs = legs();
        let best_effort =
            execute_package_transaction(PackageId(9), &legs, 20.2, PackagePolicy::BestEffort, 0)
                .unwrap();
        assert_eq!(best_effort.final_state, PackageState::Partial);
        assert_eq!(best_effort.accepted, vec![true, false]);
        assert_eq!(best_effort.residual_notional, 100.0);

        let hedge = execute_package_transaction(
            PackageId(10),
            &legs,
            0.0,
            PackagePolicy::HedgeAfterPrimary,
            0,
        )
        .unwrap();
        assert_eq!(hedge.accepted, vec![false, false]);
        assert_eq!(
            hedge.rejection_reasons[1],
            PackageRejectReason::PrimaryRejected
        );
    }

    #[test]
    fn accepted_package_tape_executes_through_the_shared_event_account_core() {
        let legs = legs();
        let result = execute_package_transaction(
            PackageId(11),
            &legs,
            100.0,
            PackagePolicy::AtomicBarSimulation,
            0,
        )
        .unwrap();
        let tape = compile_package_tape(3, 1, PackageId(11), &legs, &result).unwrap();
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
        assert_eq!(output.final_positions, vec![1.0, -2.0]);
        assert!(output.total_fee > 0.0);
        assert!(output.total_turnover > 0.0);
    }
}
