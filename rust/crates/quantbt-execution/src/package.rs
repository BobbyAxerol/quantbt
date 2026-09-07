//! Prepared bounded package workload definitions.
//!
//! The package crate owns preview/residual math. This module owns immutable
//! tape layout and bounded audit retention only; it never owns an account or
//! replays a fill ledger outside the shared execution session.

use std::sync::Arc;

use quantbt_domain::commands::CommandTapeV5;
use quantbt_engine::AuditRetentionV1;
use quantbt_package::{PackageExecutionResultV2, PackageIntentV2, PackageStateV2};

use super::{
    NativeExecutionRequestV1, NativeExecutionRunnerV1, NativeExecutionTemplateV1,
    NativeOutputProfileV1, NativeWorkloadAuditV1,
};

#[derive(Clone, Debug)]
pub struct PackageMarketWorkloadV2 {
    pub intents: Box<[PackageIntentV2]>,
    package_at_bar: Box<[i64]>,
    empty_tape: CommandTapeV5,
}

impl PackageMarketWorkloadV2 {
    pub fn new(n_bars: usize, intents: Vec<PackageIntentV2>) -> Result<Self, String> {
        if n_bars < 2 || intents.is_empty() {
            return Err(
                "native package V2 workload requires bars >= 2 and at least one package".to_owned(),
            );
        }
        let mut package_at_bar = vec![-1_i64; n_bars];
        let mut ids = std::collections::BTreeSet::new();
        for (index, intent) in intents.iter().enumerate() {
            if intent.command_bar == 0 || intent.command_bar + 1 >= n_bars {
                return Err(
                    "native package V2 command_bar must leave one following bar for reconciliation"
                        .to_owned(),
                );
            }
            if !ids.insert(intent.package_id.0) {
                return Err(
                    "native package V2 package IDs must be unique within one tape".to_owned(),
                );
            }
            let slot = &mut package_at_bar[intent.command_bar];
            if *slot >= 0 {
                return Err(
                    "native package V2 permits one package per bar; same-bar package bundles require a distinct grouped reservation contract"
                        .to_owned(),
                );
            }
            *slot = i64::try_from(index)
                .map_err(|_| "native package V2 package count exceeds ABI range".to_owned())?;
        }
        let empty_tape = CommandTapeV5::new(vec![0; n_bars + 1], Vec::new())
            .map_err(|error| error.to_string())?;
        Ok(Self {
            intents: intents.into_boxed_slice(),
            package_at_bar: package_at_bar.into_boxed_slice(),
            empty_tape,
        })
    }

    #[must_use]
    pub fn command_tape(&self) -> &CommandTapeV5 {
        &self.empty_tape
    }

    #[must_use]
    pub fn intent_at(&self, bar: usize) -> Option<&PackageIntentV2> {
        let index = *self.package_at_bar.get(bar)?;
        usize::try_from(index)
            .ok()
            .and_then(|value| self.intents.get(value))
    }

    #[must_use]
    pub fn package_count(&self) -> usize {
        self.intents.len()
    }
}

/// Flat bounded package provenance. Aggregate values stay exact in score mode;
/// row arrays are populated only under the audit retention budget.
#[derive(Clone, Debug)]
pub struct PackageMarketAuditV2 {
    pub package_count: usize,
    pub accepted_package_count: usize,
    pub residual_package_count: usize,
    pub reservation_created_total: f64,
    pub reservation_consumed_total: f64,
    pub reservation_released_total: f64,
    pub package_fee_total: f64,
    pub residual_gross_notional_total: f64,
    pub outstanding_residual_gross_notional_total: f64,
    pub package_id: Vec<u64>,
    pub command_bar: Vec<i64>,
    pub policy_code: Vec<i64>,
    pub final_state_code: Vec<i64>,
    pub reservation_created: Vec<f64>,
    pub reservation_consumed: Vec<f64>,
    pub reservation_released: Vec<f64>,
    pub package_fee: Vec<f64>,
    pub residual_gross_notional: Vec<f64>,
    pub outstanding_residual_gross_notional: Vec<f64>,
    pub leg_package_id: Vec<u64>,
    pub leg_index: Vec<i64>,
    pub leg_order_id: Vec<i64>,
    pub leg_symbol: Vec<i64>,
    pub leg_requested_qty: Vec<f64>,
    pub leg_filled_qty: Vec<f64>,
    pub leg_compensation_qty: Vec<f64>,
    pub leg_accepted: Vec<bool>,
    pub leg_rejection_code: Vec<i64>,
    pub residual_package_id: Vec<u64>,
    pub residual_leg_index: Vec<i64>,
    pub residual_symbol: Vec<i64>,
    pub residual_qty: Vec<f64>,
    pub residual_notional: Vec<f64>,
    pub residual_reason_code: Vec<i64>,
    pub transition_package_id: Vec<u64>,
    pub transition_code: Vec<i64>,
    pub detail_retention: AuditRetentionV1,
}

impl Default for PackageMarketAuditV2 {
    fn default() -> Self {
        Self::with_detail_limit(0)
    }
}

impl PackageMarketAuditV2 {
    #[must_use]
    pub fn with_detail_limit(detail_row_limit: usize) -> Self {
        Self {
            package_count: 0,
            accepted_package_count: 0,
            residual_package_count: 0,
            reservation_created_total: 0.0,
            reservation_consumed_total: 0.0,
            reservation_released_total: 0.0,
            package_fee_total: 0.0,
            residual_gross_notional_total: 0.0,
            outstanding_residual_gross_notional_total: 0.0,
            package_id: Vec::new(),
            command_bar: Vec::new(),
            policy_code: Vec::new(),
            final_state_code: Vec::new(),
            reservation_created: Vec::new(),
            reservation_consumed: Vec::new(),
            reservation_released: Vec::new(),
            package_fee: Vec::new(),
            residual_gross_notional: Vec::new(),
            outstanding_residual_gross_notional: Vec::new(),
            leg_package_id: Vec::new(),
            leg_index: Vec::new(),
            leg_order_id: Vec::new(),
            leg_symbol: Vec::new(),
            leg_requested_qty: Vec::new(),
            leg_filled_qty: Vec::new(),
            leg_compensation_qty: Vec::new(),
            leg_accepted: Vec::new(),
            leg_rejection_code: Vec::new(),
            residual_package_id: Vec::new(),
            residual_leg_index: Vec::new(),
            residual_symbol: Vec::new(),
            residual_qty: Vec::new(),
            residual_notional: Vec::new(),
            residual_reason_code: Vec::new(),
            transition_package_id: Vec::new(),
            transition_code: Vec::new(),
            detail_retention: AuditRetentionV1::new(detail_row_limit),
        }
    }

    pub fn record(&mut self, intent: &PackageIntentV2, result: &PackageExecutionResultV2) {
        self.package_count = self.package_count.saturating_add(1);
        if result.legs.iter().any(|leg| leg.accepted) {
            self.accepted_package_count = self.accepted_package_count.saturating_add(1);
        }
        if result.residual_gross_notional > 0.0 || result.outstanding_residual_gross_notional > 0.0
        {
            self.residual_package_count = self.residual_package_count.saturating_add(1);
        }
        self.reservation_created_total += result.reservation_created;
        self.reservation_consumed_total += result.reservation_consumed;
        self.reservation_released_total += result.reservation_released;
        self.package_fee_total += result.package_fee;
        self.residual_gross_notional_total += result.residual_gross_notional;
        self.outstanding_residual_gross_notional_total +=
            result.outstanding_residual_gross_notional;
        if self.detail_retention.retain_next() {
            self.package_id.push(intent.package_id.0);
            self.command_bar.push(intent.command_bar as i64);
            self.policy_code.push(intent.execution_policy as i64);
            self.final_state_code.push(result.final_state as i64);
            self.reservation_created.push(result.reservation_created);
            self.reservation_consumed.push(result.reservation_consumed);
            self.reservation_released.push(result.reservation_released);
            self.package_fee.push(result.package_fee);
            self.residual_gross_notional
                .push(result.residual_gross_notional);
            self.outstanding_residual_gross_notional
                .push(result.outstanding_residual_gross_notional);
        }
        for (index, leg) in result.legs.iter().enumerate() {
            if !self.detail_retention.retain_next() {
                break;
            }
            self.leg_package_id.push(intent.package_id.0);
            self.leg_index.push(index as i64);
            self.leg_order_id.push(leg.order_id.0);
            self.leg_symbol.push(i64::from(leg.symbol.0));
            self.leg_requested_qty.push(leg.requested_signed_qty);
            self.leg_filled_qty.push(leg.filled_signed_qty);
            self.leg_compensation_qty.push(leg.compensation_signed_qty);
            self.leg_accepted.push(leg.accepted);
            self.leg_rejection_code.push(leg.rejection_reason as i64);
        }
        for residual in &result.residuals {
            if !self.detail_retention.retain_next() {
                break;
            }
            self.residual_package_id.push(intent.package_id.0);
            self.residual_leg_index.push(residual.leg_index as i64);
            self.residual_symbol.push(i64::from(residual.symbol.0));
            self.residual_qty.push(residual.quantity);
            self.residual_notional.push(residual.notional);
            self.residual_reason_code.push(residual.reason as i64);
        }
        for transition in &result.transitions {
            if !self.detail_retention.retain_next() {
                break;
            }
            self.transition_package_id.push(intent.package_id.0);
            self.transition_code.push(*transition as i64);
        }
    }

    #[must_use]
    pub fn has_residual(&self) -> bool {
        self.residual_package_count > 0
    }

    #[must_use]
    pub fn is_closed_result(result: &PackageExecutionResultV2) -> bool {
        result.transitions.last() == Some(&PackageStateV2::Closed)
    }
}

/// Scalar-only row for one isolated bounded-package scenario.  This is the
/// native scenario/WFO primitive: it deliberately owns no Python object, path,
/// fill row, or audit vector.  A selected scenario must be rerun separately in
/// audit profile when its leg-level provenance is required.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct PackageScenarioScoreRowV2 {
    pub scenario_id: u64,
    pub final_equity: f64,
    pub total_fee: f64,
    pub total_funding: f64,
    pub total_turnover: f64,
    pub fill_count: i64,
    pub rejected_count: i64,
    pub liquidated: bool,
    pub package_count: usize,
    pub accepted_package_count: usize,
    pub residual_package_count: usize,
    pub residual_gross_notional_total: f64,
    pub outstanding_residual_gross_notional_total: f64,
    pub terminal_fingerprint: [u8; 32],
    pub request_fingerprint: [u8; 32],
}

/// One Rust-owned, scalar-only score batch for independent package scenarios.
///
/// Every scenario shares only immutable market/instrument/account preparation.
/// The one reusable `FullSession` resets account, orders, lifecycle indexes,
/// and cursors before every execution.  It is therefore suitable for prepared
/// parameter/fold *execution* once package intents already exist, but does not
/// claim that arbitrary Python package generation is native WFO.
#[derive(Clone)]
pub struct PackageScenarioBatchV2 {
    template: Arc<NativeExecutionTemplateV1>,
    requests: Box<[NativeExecutionRequestV1]>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct PackageScenarioBatchOutputV2 {
    pub rows: Vec<PackageScenarioScoreRowV2>,
    pub worker_count: usize,
    pub native_entry_calls: u64,
    pub market_copy_bytes: usize,
}

impl PackageScenarioBatchV2 {
    pub fn new(
        template: Arc<NativeExecutionTemplateV1>,
        scenarios: Vec<Vec<PackageIntentV2>>,
    ) -> Result<Self, String> {
        if scenarios.is_empty() || scenarios.iter().any(Vec::is_empty) {
            return Err(
                "native package V2 scenario batch requires at least one non-empty scenario"
                    .to_owned(),
            );
        }
        let mut requests = Vec::with_capacity(scenarios.len());
        for intents in scenarios {
            requests.push(NativeExecutionRequestV1::from_template_package_market_v2(
                Arc::clone(&template),
                NativeOutputProfileV1::Score,
                intents,
            )?);
        }
        Ok(Self {
            template,
            requests: requests.into_boxed_slice(),
        })
    }

    #[must_use]
    pub fn scenario_count(&self) -> usize {
        self.requests.len()
    }

    /// Execute all independent scenarios inside one Rust entry.  The mutable
    /// runner is intentionally shared serially, rather than the account state:
    /// `execute_request` resets it before every scenario.
    pub fn score(&self) -> Result<PackageScenarioBatchOutputV2, String> {
        let mut runner = NativeExecutionRunnerV1::new(Arc::clone(&self.template))?;
        let mut rows = Vec::with_capacity(self.requests.len());
        for (index, request) in self.requests.iter().enumerate() {
            let result = runner.execute_request(request)?;
            let score = result.score();
            let audit = match &result.workload_audit {
                NativeWorkloadAuditV1::PackageMarketV2(audit) => audit,
                _ => {
                    return Err(
                        "native package V2 scenario batch received a non-package result".to_owned(),
                    );
                }
            };
            rows.push(PackageScenarioScoreRowV2 {
                scenario_id: index as u64,
                final_equity: score.final_equity,
                total_fee: score.total_fee,
                total_funding: score.total_funding,
                total_turnover: score.total_turnover,
                fill_count: score.fill_count,
                rejected_count: score.rejected_count,
                liquidated: score.liquidated,
                package_count: audit.package_count,
                accepted_package_count: audit.accepted_package_count,
                residual_package_count: audit.residual_package_count,
                residual_gross_notional_total: audit.residual_gross_notional_total,
                outstanding_residual_gross_notional_total: audit
                    .outstanding_residual_gross_notional_total,
                terminal_fingerprint: result.header_v2.terminal_fingerprint,
                request_fingerprint: result.request_fingerprint,
            });
        }
        Ok(PackageScenarioBatchOutputV2 {
            rows,
            worker_count: 1,
            native_entry_calls: 1,
            // All requests retain the same immutable template Arc.  Its market
            // is prepared outside this batch and no scenario duplicates it.
            market_copy_bytes: 0,
        })
    }
}
