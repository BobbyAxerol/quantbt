//! Bounded same-account package V2 planning and residual accounting.
//!
//! This module intentionally owns no mutable account. It previews one typed
//! package against a supplied shared-account projection, emits the exact
//! simulated fill quantities as commands, and leaves the authoritative commit
//! to `quantbt-engine::FullSession`. The explicit fill fraction is a bounded
//! deterministic scenario input, not a claim of an order-book fill model.

use quantbt_domain::{
    commands::OrderCommandV5,
    enums::{ActivationPolicy, CommandAction, OrderType, Side, TimeInForce},
    ids::{ExternalOrderId, SymbolId},
};

use super::PackageId;

const EPSILON: f64 = 1e-12;

#[repr(u8)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PackageExecutionPolicyV2 {
    AtomicBarSimulation = 0,
    Sequential = 1,
    BestEffort = 2,
    HedgeAfterPrimary = 3,
}

impl TryFrom<u8> for PackageExecutionPolicyV2 {
    type Error = String;

    fn try_from(value: u8) -> Result<Self, Self::Error> {
        match value {
            0 => Ok(Self::AtomicBarSimulation),
            1 => Ok(Self::Sequential),
            2 => Ok(Self::BestEffort),
            3 => Ok(Self::HedgeAfterPrimary),
            _ => Err("unsupported package V2 execution policy".to_owned()),
        }
    }
}

impl PackageExecutionPolicyV2 {
    #[must_use]
    pub const fn name(self) -> &'static str {
        match self {
            Self::AtomicBarSimulation => "atomic_bar_simulation",
            Self::Sequential => "sequential",
            Self::BestEffort => "best_effort",
            Self::HedgeAfterPrimary => "hedge_after_primary",
        }
    }
}

#[repr(u8)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ResidualRiskPolicyV1 {
    Record = 0,
    UnwindPackage = 1,
}

impl TryFrom<u8> for ResidualRiskPolicyV1 {
    type Error = String;

    fn try_from(value: u8) -> Result<Self, Self::Error> {
        match value {
            0 => Ok(Self::Record),
            1 => Ok(Self::UnwindPackage),
            _ => Err("unsupported package V2 residual risk policy".to_owned()),
        }
    }
}

impl ResidualRiskPolicyV1 {
    #[must_use]
    pub const fn name(self) -> &'static str {
        match self {
            Self::Record => "record",
            Self::UnwindPackage => "unwind_package",
        }
    }
}

#[repr(u8)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LegQuantitySourceV1 {
    Fixed = 0,
    ProportionOfRequested = 1,
    ProportionOfActualFill = 2,
    ConsumePreviousOutput = 3,
}

impl TryFrom<u8> for LegQuantitySourceV1 {
    type Error = String;

    fn try_from(value: u8) -> Result<Self, Self::Error> {
        match value {
            0 => Ok(Self::Fixed),
            1 => Ok(Self::ProportionOfRequested),
            2 => Ok(Self::ProportionOfActualFill),
            3 => Ok(Self::ConsumePreviousOutput),
            _ => Err("unsupported package V2 quantity source".to_owned()),
        }
    }
}

impl LegQuantitySourceV1 {
    #[must_use]
    pub const fn name(self) -> &'static str {
        match self {
            Self::Fixed => "fixed",
            Self::ProportionOfRequested => "proportion_of_requested",
            Self::ProportionOfActualFill => "proportion_of_actual_fill",
            Self::ConsumePreviousOutput => "consume_previous_output",
        }
    }
}

#[repr(u8)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PackageStateV2 {
    Planned = 0,
    Validated = 1,
    PreflightRejected = 2,
    Reserved = 3,
    Submitting = 4,
    PartiallyFilled = 5,
    Filled = 6,
    ResidualDetected = 7,
    Compensating = 8,
    Unwinding = 9,
    CompletedHedged = 10,
    CompletedWithResidual = 11,
    Aborted = 12,
    Closed = 13,
}

impl PackageStateV2 {
    #[must_use]
    pub const fn name(self) -> &'static str {
        match self {
            Self::Planned => "PLANNED",
            Self::Validated => "VALIDATED",
            Self::PreflightRejected => "PREFLIGHT_REJECTED",
            Self::Reserved => "RESERVED",
            Self::Submitting => "SUBMITTING",
            Self::PartiallyFilled => "PARTIALLY_FILLED",
            Self::Filled => "FILLED",
            Self::ResidualDetected => "RESIDUAL_DETECTED",
            Self::Compensating => "COMPENSATING",
            Self::Unwinding => "UNWINDING",
            Self::CompletedHedged => "COMPLETED_HEDGED",
            Self::CompletedWithResidual => "COMPLETED_WITH_RESIDUAL",
            Self::Aborted => "ABORTED",
            Self::Closed => "CLOSED",
        }
    }
}

#[repr(u8)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PackageRejectReasonV2 {
    Accepted = 0,
    InvalidLeg = 1,
    InvalidDependency = 2,
    StaleMarket = 3,
    MinQty = 4,
    MinNotional = 5,
    NoLiquidity = 6,
    PostCostMargin = 7,
    AtomicRollback = 8,
    SiblingPreflightRejected = 9,
    PrimaryRejected = 10,
    Unwound = 11,
}

impl PackageRejectReasonV2 {
    #[must_use]
    pub const fn name(self) -> &'static str {
        match self {
            Self::Accepted => "ACCEPTED",
            Self::InvalidLeg => "INVALID_LEG",
            Self::InvalidDependency => "INVALID_DEPENDENCY",
            Self::StaleMarket => "STALE_MARKET",
            Self::MinQty => "MIN_QTY",
            Self::MinNotional => "MIN_NOTIONAL",
            Self::NoLiquidity => "NO_LIQUIDITY",
            Self::PostCostMargin => "POST_COST_MARGIN",
            Self::AtomicRollback => "ATOMIC_ROLLBACK",
            Self::SiblingPreflightRejected => "SIBLING_PREFLIGHT_REJECTED",
            Self::PrimaryRejected => "PRIMARY_REJECTED",
            Self::Unwound => "UNWOUND",
        }
    }
}

#[repr(u8)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ResidualReasonCodeV1 {
    PartialFill = 0,
    Rejected = 1,
    Quantization = 2,
    Unwound = 3,
}

impl ResidualReasonCodeV1 {
    #[must_use]
    pub const fn name(self) -> &'static str {
        match self {
            Self::PartialFill => "PARTIAL_FILL",
            Self::Rejected => "REJECTED",
            Self::Quantization => "QUANTIZATION",
            Self::Unwound => "UNWOUND",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct PackageLegIntentV2 {
    pub order_id: ExternalOrderId,
    pub symbol: SymbolId,
    pub signed_qty: f64,
    pub quantity_source: LegQuantitySourceV1,
    pub source_leg: i64,
    pub quantity_ratio: f64,
    pub fill_fraction: f64,
    pub qty_step: f64,
    pub min_qty: f64,
    pub min_notional: f64,
    pub source_age_ns: i64,
    pub venue_code: u16,
    pub venue_sequence: u32,
}

#[derive(Clone, Debug, PartialEq)]
pub struct PackageIntentV2 {
    pub package_id: PackageId,
    pub command_bar: usize,
    pub execution_policy: PackageExecutionPolicyV2,
    pub residual_policy: ResidualRiskPolicyV1,
    pub legs: Box<[PackageLegIntentV2]>,
    pub max_staleness_ns: i64,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ResidualExposureV1 {
    pub leg_index: usize,
    pub symbol: SymbolId,
    pub quantity: f64,
    pub notional: f64,
    pub reason: ResidualReasonCodeV1,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct PackageLegExecutionV2 {
    pub order_id: ExternalOrderId,
    pub symbol: SymbolId,
    pub requested_signed_qty: f64,
    pub filled_signed_qty: f64,
    pub compensation_signed_qty: f64,
    pub accepted: bool,
    pub rejection_reason: PackageRejectReasonV2,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct PackageExecutionCommandV2 {
    pub order_id: ExternalOrderId,
    pub symbol: SymbolId,
    pub signed_qty: f64,
    pub leg_index: usize,
    pub compensation: bool,
}

#[derive(Clone, Debug, PartialEq)]
pub struct PackageExecutionResultV2 {
    pub package_id: PackageId,
    pub policy: PackageExecutionPolicyV2,
    pub final_state: PackageStateV2,
    pub transitions: Vec<PackageStateV2>,
    pub legs: Vec<PackageLegExecutionV2>,
    pub residuals: Vec<ResidualExposureV1>,
    pub commands: Vec<PackageExecutionCommandV2>,
    pub reservation_created: f64,
    pub reservation_consumed: f64,
    pub reservation_released: f64,
    pub package_fee: f64,
    pub residual_gross_notional: f64,
    pub outstanding_residual_gross_notional: f64,
}

impl PackageExecutionResultV2 {
    #[must_use]
    pub fn invariants_pass(&self, tolerance: f64) -> bool {
        let reservation_reconciles =
            (self.reservation_created - self.reservation_consumed - self.reservation_released)
                .abs()
                <= tolerance;
        let atomic_clean = !(self.policy == PackageExecutionPolicyV2::AtomicBarSimulation
            && self.final_state == PackageStateV2::Aborted
            && self.legs.iter().any(|leg| leg.accepted));
        reservation_reconciles
            && atomic_clean
            && self.package_fee.is_finite()
            && self.residual_gross_notional.is_finite()
            && self.outstanding_residual_gross_notional.is_finite()
            && self
                .residuals
                .iter()
                .all(|item| item.quantity.is_finite() && item.notional.is_finite())
    }
}

/// Shared-account values needed only for one immutable package preview.
#[derive(Clone, Copy, Debug)]
pub struct PackageMarketExecutionRequestV2<'a> {
    pub intent: &'a PackageIntentV2,
    pub previous_units: &'a [f64],
    pub close_prices: &'a [f64],
    pub contract_sizes: &'a [f64],
    pub leverages: &'a [f64],
    pub fee_rates: &'a [f64],
    pub slippage_rate: f64,
    pub equity: f64,
}

/// Preview one typed V2 package and emit exact deterministic market commands.
/// The caller must pass the commands to the shared execution session; this
/// function intentionally never mutates an account ledger of its own.
pub fn execute_package_market_v2(
    request: PackageMarketExecutionRequestV2<'_>,
) -> Result<PackageExecutionResultV2, String> {
    validate_request(&request)?;
    let intent = request.intent;
    if !validate_leg_order(&intent.legs, request.previous_units.len()) {
        return Ok(atomic_reject(intent, PackageRejectReasonV2::InvalidLeg));
    }
    if intent.execution_policy == PackageExecutionPolicyV2::AtomicBarSimulation
        && intent
            .legs
            .iter()
            .any(|leg| (leg.fill_fraction - 1.0).abs() > EPSILON)
    {
        return Ok(atomic_reject(intent, PackageRejectReasonV2::AtomicRollback));
    }

    let count = intent.legs.len();
    let mut transitions = vec![PackageStateV2::Planned, PackageStateV2::Validated];
    let mut units = request.previous_units.to_vec();
    let mut equity = request.equity;
    let mut requested = vec![0.0; count];
    let mut filled = vec![0.0; count];
    let mut compensation = vec![0.0; count];
    let mut accepted = vec![false; count];
    let mut reasons = vec![PackageRejectReasonV2::Accepted; count];
    let mut residuals = Vec::new();
    let mut commands = Vec::with_capacity(count.saturating_mul(2));
    let mut reservation_created = 0.0;
    let mut reservation_consumed = 0.0;
    let mut package_fee = 0.0;

    if intent.execution_policy == PackageExecutionPolicyV2::AtomicBarSimulation {
        let mut preview_units = units.clone();
        let mut preview_equity = equity;
        for index in 0..count {
            let leg = intent.legs[index];
            let value = match resolve_requested(&intent.legs, index, &requested, &filled) {
                Some(value) => value,
                None => {
                    return Ok(atomic_reject_with_leg(
                        intent,
                        index,
                        PackageRejectReasonV2::InvalidDependency,
                    ));
                }
            };
            requested[index] = value;
            let outcome = match attempt_leg(
                leg,
                value,
                &mut preview_units,
                &mut preview_equity,
                &request,
                false,
            ) {
                Ok(outcome) => outcome,
                Err(reason) => return Ok(atomic_reject_with_leg(intent, index, reason)),
            };
            if (value - outcome.actual).abs() > EPSILON {
                return Ok(atomic_reject_with_leg(
                    intent,
                    index,
                    PackageRejectReasonV2::AtomicRollback,
                ));
            }
            filled[index] = outcome.actual;
            accepted[index] = true;
            reservation_created += outcome.demand;
            reservation_consumed += outcome.demand;
            package_fee += outcome.fee;
        }
        units = preview_units;
        equity = preview_equity;
        transitions.extend([
            PackageStateV2::Reserved,
            PackageStateV2::Submitting,
            PackageStateV2::Filled,
        ]);
        for (index, leg) in intent.legs.iter().copied().enumerate() {
            commands.push(PackageExecutionCommandV2 {
                order_id: leg.order_id,
                symbol: leg.symbol,
                signed_qty: filled[index],
                leg_index: index,
                compensation: false,
            });
        }
    } else {
        transitions.extend([PackageStateV2::Reserved, PackageStateV2::Submitting]);
        for index in 0..count {
            let leg = intent.legs[index];
            let Some(value) = resolve_requested(&intent.legs, index, &requested, &filled) else {
                reasons[index] = if intent.execution_policy
                    == PackageExecutionPolicyV2::HedgeAfterPrimary
                    && index > 0
                {
                    PackageRejectReasonV2::PrimaryRejected
                } else {
                    PackageRejectReasonV2::InvalidDependency
                };
                residuals.push(rejected_residual(
                    index,
                    leg,
                    value_or_signed(leg),
                    &request,
                ));
                continue;
            };
            requested[index] = value;
            if intent.execution_policy == PackageExecutionPolicyV2::HedgeAfterPrimary
                && index > 0
                && !accepted[0]
            {
                reasons[index] = PackageRejectReasonV2::PrimaryRejected;
                residuals.push(rejected_residual(index, leg, value, &request));
                continue;
            }
            match attempt_leg(leg, value, &mut units, &mut equity, &request, false) {
                Ok(outcome) => {
                    filled[index] = outcome.actual;
                    accepted[index] = true;
                    reservation_created += outcome.demand;
                    reservation_consumed += outcome.demand;
                    package_fee += outcome.fee;
                    commands.push(PackageExecutionCommandV2 {
                        order_id: leg.order_id,
                        symbol: leg.symbol,
                        signed_qty: outcome.actual,
                        leg_index: index,
                        compensation: false,
                    });
                    if (value - outcome.actual).abs() > EPSILON {
                        residuals.push(ResidualExposureV1 {
                            leg_index: index,
                            symbol: leg.symbol,
                            quantity: value - outcome.actual,
                            notional: (value - outcome.actual)
                                * request.close_prices[leg.symbol.0 as usize]
                                * request.contract_sizes[leg.symbol.0 as usize],
                            reason: ResidualReasonCodeV1::PartialFill,
                        });
                    }
                }
                Err(reason) => {
                    reasons[index] = reason;
                    residuals.push(rejected_residual(index, leg, value, &request));
                }
            }
        }
    }

    if !accepted.iter().any(|value| *value) {
        transitions.extend([
            PackageStateV2::PreflightRejected,
            PackageStateV2::Aborted,
            PackageStateV2::Closed,
        ]);
        return Ok(build_result(
            intent,
            PackageStateV2::Aborted,
            transitions,
            &requested,
            &filled,
            &compensation,
            &accepted,
            &reasons,
            residuals,
            commands,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
        ));
    }

    let any_residual = !residuals.is_empty();
    let final_state;
    let outstanding;
    if any_residual {
        transitions.extend([
            PackageStateV2::PartiallyFilled,
            PackageStateV2::ResidualDetected,
        ]);
        if intent.residual_policy == ResidualRiskPolicyV1::UnwindPackage {
            transitions.extend([PackageStateV2::Compensating, PackageStateV2::Unwinding]);
            for index in (0..count).rev() {
                if !accepted[index] || filled[index].abs() <= EPSILON {
                    continue;
                }
                let leg = intent.legs[index];
                if let Ok(outcome) =
                    attempt_leg(leg, -filled[index], &mut units, &mut equity, &request, true)
                {
                    compensation[index] += outcome.actual;
                    reservation_created += outcome.demand;
                    reservation_consumed += outcome.demand;
                    package_fee += outcome.fee;
                    commands.push(PackageExecutionCommandV2 {
                        order_id: compensation_order_id(intent.package_id, index)?,
                        symbol: leg.symbol,
                        signed_qty: outcome.actual,
                        leg_index: index,
                        compensation: true,
                    });
                    residuals.push(ResidualExposureV1 {
                        leg_index: index,
                        symbol: leg.symbol,
                        quantity: outcome.actual,
                        notional: outcome.actual
                            * request.close_prices[leg.symbol.0 as usize]
                            * request.contract_sizes[leg.symbol.0 as usize],
                        reason: ResidualReasonCodeV1::Unwound,
                    });
                }
            }
            outstanding =
                outstanding_gross_notional(&intent.legs, &filled, &compensation, &request);
            final_state = if outstanding <= EPSILON {
                PackageStateV2::CompletedHedged
            } else {
                PackageStateV2::CompletedWithResidual
            };
        } else {
            outstanding =
                outstanding_gross_notional(&intent.legs, &filled, &compensation, &request);
            final_state = PackageStateV2::CompletedWithResidual;
        }
    } else {
        if !transitions.contains(&PackageStateV2::Filled) {
            transitions.push(PackageStateV2::Filled);
        }
        outstanding = 0.0;
        final_state = PackageStateV2::CompletedHedged;
    }
    transitions.push(final_state);
    transitions.push(PackageStateV2::Closed);
    Ok(build_result(
        intent,
        final_state,
        transitions,
        &requested,
        &filled,
        &compensation,
        &accepted,
        &reasons,
        residuals,
        commands,
        reservation_created,
        reservation_consumed,
        0.0,
        package_fee,
        outstanding,
    ))
}

/// Compile the package planner's exact deterministic fill quantities into the
/// shared-session command language.  This function deliberately emits only
/// commands accepted by the package preview; `FullSession` remains the sole
/// owner of order lifecycle, fill price, fee, funding, and account mutation.
pub fn compile_package_commands_v2(
    intent: &PackageIntentV2,
    result: &PackageExecutionResultV2,
) -> Result<Vec<OrderCommandV5>, String> {
    if result.package_id != intent.package_id || result.policy != intent.execution_policy {
        return Err("package V2 command compiler result does not match intent".to_owned());
    }
    let group_id = i64::try_from(intent.package_id.0)
        .map_err(|_| "package V2 package_id exceeds canonical group ID range".to_owned())?;
    let mut commands = Vec::with_capacity(result.commands.len());
    for (index, command) in result.commands.iter().enumerate() {
        if !command.signed_qty.is_finite() || command.signed_qty.abs() <= EPSILON {
            return Err("package V2 command has invalid deterministic quantity".to_owned());
        }
        commands.push(OrderCommandV5 {
            action: CommandAction::Place,
            symbol: Some(command.symbol),
            side: Some(if command.signed_qty > 0.0 {
                Side::Buy
            } else {
                Side::Sell
            }),
            order_type: Some(OrderType::Market),
            tif: Some(TimeInForce::Gtc),
            // A compensation command is intentionally not reduce-only. The
            // compact linear account contract permits a signed delta to close
            // only the quantity created by this package; its exact size is
            // validated by the planner and the shared session owns the fill.
            reduce_only: false,
            external_id: command.order_id,
            target_id: ExternalOrderId(-1),
            parent_id: ExternalOrderId(-1),
            group_id,
            oco_id: -1,
            activation: Some(ActivationPolicy::Immediate),
            command_index: u32::try_from(index)
                .map_err(|_| "package V2 command count exceeds ABI range".to_owned())?,
            qty: command.signed_qty.abs(),
            limit_price: 0.0,
            stop_price: 0.0,
            expire_bar: None,
        });
    }
    Ok(commands)
}

/// Construct a terminal package outcome when the common session has already
/// reached an unrecoverable state before the package command phase.  Keeping
/// this in the package domain prevents callers from inventing a second audit
/// shape or silently dropping a package attempt.
#[must_use]
pub fn abort_package_market_v2(
    intent: &PackageIntentV2,
    reason: PackageRejectReasonV2,
) -> PackageExecutionResultV2 {
    atomic_reject(intent, reason)
}

struct LegAttemptV2 {
    actual: f64,
    demand: f64,
    fee: f64,
}

fn validate_request(request: &PackageMarketExecutionRequestV2<'_>) -> Result<(), String> {
    let width = request.previous_units.len();
    if width == 0
        || request.intent.legs.is_empty()
        || request.close_prices.len() != width
        || request.contract_sizes.len() != width
        || request.leverages.len() != width
        || request.fee_rates.len() != width
        || !request.equity.is_finite()
        || request.equity <= 0.0
        || !request.slippage_rate.is_finite()
        || request.slippage_rate < 0.0
        || request
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
        return Err("package V2 request has invalid shared-account inputs".to_owned());
    }
    Ok(())
}

fn validate_leg_order(legs: &[PackageLegIntentV2], n_symbols: usize) -> bool {
    legs.iter().enumerate().all(|(index, leg)| {
        leg.order_id.0 >= 0
            && (leg.symbol.0 as usize) < n_symbols
            && (index == 0 || legs[index - 1].venue_sequence <= leg.venue_sequence)
    })
}

fn resolve_requested(
    legs: &[PackageLegIntentV2],
    index: usize,
    requested: &[f64],
    filled: &[f64],
) -> Option<f64> {
    let leg = legs.get(index)?;
    let raw = match leg.quantity_source {
        LegQuantitySourceV1::Fixed => leg.signed_qty,
        LegQuantitySourceV1::ProportionOfRequested => {
            let source = usize::try_from(leg.source_leg).ok()?;
            if source >= index {
                return None;
            }
            requested[source] * leg.quantity_ratio
        }
        LegQuantitySourceV1::ProportionOfActualFill
        | LegQuantitySourceV1::ConsumePreviousOutput => {
            let source = usize::try_from(leg.source_leg).ok()?;
            if source >= index {
                return None;
            }
            filled[source] * leg.quantity_ratio
        }
    };
    if !raw.is_finite() {
        return None;
    }
    Some(quantize_signed(raw, leg.qty_step))
}

fn attempt_leg(
    leg: PackageLegIntentV2,
    requested: f64,
    units: &mut [f64],
    equity: &mut f64,
    request: &PackageMarketExecutionRequestV2<'_>,
    ignore_fraction: bool,
) -> Result<LegAttemptV2, PackageRejectReasonV2> {
    let reason = leg_reject_reason(leg, requested, request);
    if reason != PackageRejectReasonV2::Accepted {
        return Err(reason);
    }
    let fraction = if ignore_fraction {
        1.0
    } else {
        leg.fill_fraction
    };
    if !fraction.is_finite() || !(0.0..=1.0).contains(&fraction) {
        return Err(PackageRejectReasonV2::InvalidLeg);
    }
    let actual = quantize_signed(requested * fraction, leg.qty_step);
    if actual.abs() <= EPSILON {
        return Err(PackageRejectReasonV2::NoLiquidity);
    }
    let symbol = leg.symbol.0 as usize;
    let close = request.close_prices[symbol];
    let contract_size = request.contract_sizes[symbol];
    let leverage = request.leverages[symbol];
    let execution_price = if actual > 0.0 {
        close * (1.0 + request.slippage_rate)
    } else {
        close * (1.0 - request.slippage_rate)
    };
    if !execution_price.is_finite() || execution_price <= 0.0 {
        return Err(PackageRejectReasonV2::InvalidLeg);
    }
    let old_initial = units[symbol].abs() * close * contract_size / leverage;
    let mut new_units = units.to_vec();
    new_units[symbol] += actual;
    let new_initial = new_units[symbol].abs() * execution_price * contract_size / leverage;
    let current_initial = total_initial_margin(
        units,
        request.close_prices,
        request.contract_sizes,
        request.leverages,
    );
    let fee = actual.abs() * execution_price * contract_size * request.fee_rates[symbol];
    let demand = fee + (new_initial - old_initial).max(0.0);
    if demand > *equity - current_initial + EPSILON {
        return Err(PackageRejectReasonV2::PostCostMargin);
    }
    *equity += actual * (close - execution_price) * contract_size - fee;
    units[symbol] = new_units[symbol];
    Ok(LegAttemptV2 {
        actual,
        demand,
        fee,
    })
}

fn leg_reject_reason(
    leg: PackageLegIntentV2,
    requested: f64,
    request: &PackageMarketExecutionRequestV2<'_>,
) -> PackageRejectReasonV2 {
    if !leg.signed_qty.is_finite()
        || !leg.quantity_ratio.is_finite()
        || !leg.fill_fraction.is_finite()
        || leg.fill_fraction < 0.0
        || leg.fill_fraction > 1.0
        || !leg.qty_step.is_finite()
        || leg.qty_step < 0.0
        || !leg.min_qty.is_finite()
        || leg.min_qty < 0.0
        || !leg.min_notional.is_finite()
        || leg.min_notional < 0.0
        || requested.abs() <= EPSILON
    {
        return PackageRejectReasonV2::InvalidLeg;
    }
    if request.intent.max_staleness_ns >= 0 && leg.source_age_ns > request.intent.max_staleness_ns {
        return PackageRejectReasonV2::StaleMarket;
    }
    if requested.abs() + EPSILON < leg.min_qty {
        return PackageRejectReasonV2::MinQty;
    }
    let symbol = leg.symbol.0 as usize;
    if requested.abs() * request.close_prices[symbol] * request.contract_sizes[symbol] + EPSILON
        < leg.min_notional
    {
        return PackageRejectReasonV2::MinNotional;
    }
    if leg.fill_fraction <= EPSILON {
        return PackageRejectReasonV2::NoLiquidity;
    }
    PackageRejectReasonV2::Accepted
}

fn rejected_residual(
    index: usize,
    leg: PackageLegIntentV2,
    quantity: f64,
    request: &PackageMarketExecutionRequestV2<'_>,
) -> ResidualExposureV1 {
    let symbol = leg.symbol.0 as usize;
    ResidualExposureV1 {
        leg_index: index,
        symbol: leg.symbol,
        quantity,
        notional: quantity * request.close_prices[symbol] * request.contract_sizes[symbol],
        reason: ResidualReasonCodeV1::Rejected,
    }
}

fn value_or_signed(leg: PackageLegIntentV2) -> f64 {
    quantize_signed(leg.signed_qty, leg.qty_step)
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
        .map(|(index, quantity)| {
            quantity.abs() * close_prices[index] * contract_sizes[index] / leverages[index]
        })
        .sum()
}

fn quantize_signed(value: f64, step: f64) -> f64 {
    if !value.is_finite() || !step.is_finite() || step < 0.0 {
        return 0.0;
    }
    if step == 0.0 {
        return value;
    }
    value.signum() * ((value.abs() / step + EPSILON).floor() * step)
}

fn outstanding_gross_notional(
    legs: &[PackageLegIntentV2],
    filled: &[f64],
    compensation: &[f64],
    request: &PackageMarketExecutionRequestV2<'_>,
) -> f64 {
    legs.iter()
        .enumerate()
        .map(|(index, leg)| {
            (filled[index] + compensation[index]).abs()
                * request.close_prices[leg.symbol.0 as usize]
                * request.contract_sizes[leg.symbol.0 as usize]
        })
        .sum()
}

fn compensation_order_id(
    package_id: PackageId,
    leg_index: usize,
) -> Result<ExternalOrderId, String> {
    let package = i64::try_from(package_id.0).map_err(|_| {
        "package V2 package_id exceeds deterministic compensation ID range".to_owned()
    })?;
    let leg = i64::try_from(leg_index).map_err(|_| {
        "package V2 leg index exceeds deterministic compensation ID range".to_owned()
    })?;
    let offset = package
        .checked_mul(1_000_000)
        .and_then(|value| value.checked_add(leg))
        .ok_or_else(|| "package V2 compensation ID overflow".to_owned())?;
    Ok(ExternalOrderId(i64::MIN + offset))
}

fn atomic_reject(
    intent: &PackageIntentV2,
    reason: PackageRejectReasonV2,
) -> PackageExecutionResultV2 {
    atomic_reject_with_leg(intent, usize::MAX, reason)
}

fn atomic_reject_with_leg(
    intent: &PackageIntentV2,
    failed_index: usize,
    reason: PackageRejectReasonV2,
) -> PackageExecutionResultV2 {
    let legs = intent
        .legs
        .iter()
        .enumerate()
        .map(|(index, leg)| PackageLegExecutionV2 {
            order_id: leg.order_id,
            symbol: leg.symbol,
            requested_signed_qty: 0.0,
            filled_signed_qty: 0.0,
            compensation_signed_qty: 0.0,
            accepted: false,
            rejection_reason: if failed_index == usize::MAX || index == failed_index {
                reason
            } else {
                PackageRejectReasonV2::SiblingPreflightRejected
            },
        })
        .collect();
    PackageExecutionResultV2 {
        package_id: intent.package_id,
        policy: intent.execution_policy,
        final_state: PackageStateV2::Aborted,
        transitions: vec![
            PackageStateV2::Planned,
            PackageStateV2::PreflightRejected,
            PackageStateV2::Aborted,
            PackageStateV2::Closed,
        ],
        legs,
        residuals: Vec::new(),
        commands: Vec::new(),
        reservation_created: 0.0,
        reservation_consumed: 0.0,
        reservation_released: 0.0,
        package_fee: 0.0,
        residual_gross_notional: 0.0,
        outstanding_residual_gross_notional: 0.0,
    }
}

#[allow(clippy::too_many_arguments)]
fn build_result(
    intent: &PackageIntentV2,
    final_state: PackageStateV2,
    transitions: Vec<PackageStateV2>,
    requested: &[f64],
    filled: &[f64],
    compensation: &[f64],
    accepted: &[bool],
    reasons: &[PackageRejectReasonV2],
    residuals: Vec<ResidualExposureV1>,
    commands: Vec<PackageExecutionCommandV2>,
    reservation_created: f64,
    reservation_consumed: f64,
    reservation_released: f64,
    package_fee: f64,
    outstanding_residual_gross_notional: f64,
) -> PackageExecutionResultV2 {
    let legs = intent
        .legs
        .iter()
        .enumerate()
        .map(|(index, leg)| PackageLegExecutionV2 {
            order_id: leg.order_id,
            symbol: leg.symbol,
            requested_signed_qty: requested[index],
            filled_signed_qty: filled[index],
            compensation_signed_qty: compensation[index],
            accepted: accepted[index],
            rejection_reason: reasons[index],
        })
        .collect();
    let residual_gross_notional = residuals
        .iter()
        .filter(|item| item.reason != ResidualReasonCodeV1::Unwound)
        .map(|item| item.notional.abs())
        .sum();
    PackageExecutionResultV2 {
        package_id: intent.package_id,
        policy: intent.execution_policy,
        final_state,
        transitions,
        legs,
        residuals,
        commands,
        reservation_created,
        reservation_consumed,
        reservation_released,
        package_fee,
        residual_gross_notional,
        outstanding_residual_gross_notional,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn request(policy: PackageExecutionPolicyV2) -> (PackageIntentV2, Vec<f64>, Vec<f64>) {
        let intent = PackageIntentV2 {
            package_id: PackageId(7),
            command_bar: 1,
            execution_policy: policy,
            residual_policy: ResidualRiskPolicyV1::Record,
            legs: vec![
                PackageLegIntentV2 {
                    order_id: ExternalOrderId(10),
                    symbol: SymbolId(0),
                    signed_qty: 1.0,
                    quantity_source: LegQuantitySourceV1::Fixed,
                    source_leg: -1,
                    quantity_ratio: 1.0,
                    fill_fraction: 1.0,
                    qty_step: 0.0,
                    min_qty: 0.0,
                    min_notional: 0.0,
                    source_age_ns: 0,
                    venue_code: 1,
                    venue_sequence: 0,
                },
                PackageLegIntentV2 {
                    order_id: ExternalOrderId(11),
                    symbol: SymbolId(1),
                    signed_qty: -1.0,
                    quantity_source: LegQuantitySourceV1::ProportionOfActualFill,
                    source_leg: 0,
                    quantity_ratio: -1.0,
                    fill_fraction: 1.0,
                    qty_step: 0.0,
                    min_qty: 0.0,
                    min_notional: 0.0,
                    source_age_ns: 0,
                    venue_code: 1,
                    venue_sequence: 1,
                },
            ]
            .into_boxed_slice(),
            max_staleness_ns: 0,
        };
        (intent, vec![100.0, 100.0], vec![1.0, 1.0])
    }

    fn run(intent: &PackageIntentV2, closes: &[f64], fraction: &[f64]) -> PackageExecutionResultV2 {
        let mut local = intent.clone();
        for (leg, value) in local.legs.iter_mut().zip(fraction.iter().copied()) {
            leg.fill_fraction = value;
        }
        execute_package_market_v2(PackageMarketExecutionRequestV2 {
            intent: &local,
            previous_units: &[0.0, 0.0],
            close_prices: closes,
            contract_sizes: &[1.0, 1.0],
            leverages: &[2.0, 2.0],
            fee_rates: &[0.001, 0.001],
            slippage_rate: 0.001,
            equity: 1_000.0,
        })
        .unwrap()
    }

    #[test]
    fn hedge_uses_actual_primary_fill_and_records_partial_residual() {
        let (intent, closes, _) = request(PackageExecutionPolicyV2::HedgeAfterPrimary);
        let result = run(&intent, &closes, &[0.5, 1.0]);
        assert_eq!(result.legs[0].filled_signed_qty, 0.5);
        assert_eq!(result.legs[1].requested_signed_qty, -0.5);
        assert_eq!(result.legs[1].filled_signed_qty, -0.5);
        assert_eq!(result.final_state, PackageStateV2::CompletedWithResidual);
        assert!(result.invariants_pass(EPSILON));
    }

    #[test]
    fn atomic_partial_request_rejects_without_commands() {
        let (intent, closes, _) = request(PackageExecutionPolicyV2::AtomicBarSimulation);
        let result = run(&intent, &closes, &[0.5, 1.0]);
        assert_eq!(result.final_state, PackageStateV2::Aborted);
        assert!(result.commands.is_empty());
        assert!(result.invariants_pass(EPSILON));
    }

    #[test]
    fn unwind_eliminates_outstanding_package_position() {
        let (mut intent, closes, _) = request(PackageExecutionPolicyV2::HedgeAfterPrimary);
        intent.residual_policy = ResidualRiskPolicyV1::UnwindPackage;
        let result = run(&intent, &closes, &[1.0, 0.0]);
        assert_eq!(result.final_state, PackageStateV2::CompletedHedged);
        assert_eq!(result.outstanding_residual_gross_notional, 0.0);
        assert!(result.commands.iter().any(|command| command.compensation));
    }
}
