//! Backend-neutral Canonical Trace V2 domain types.
//!
//! This is an additive typed contract.  It does not yet make the current
//! `FullSession` a V2 runtime emitter; Phase 57 only freezes the shared row,
//! serializer, hash, and terminal-fingerprint vocabulary for later adoption.

use crate::ids::{AccountId, BarIndex, ExternalOrderId, PackageId, SymbolId, TimestampNs};

pub const CANONICAL_TRACE_V2_SCHEMA_VERSION: &str = "canonical-trace-v2";
pub const CANONICAL_TRACE_V2_SERIALIZER: &str = "canonical-little-endian-v1";
pub const CANONICAL_TRACE_V2_HASH: &str = "fnv1a-dual-128-v1";

const FNV64_PRIME: u64 = 0x0000_0100_0000_01b3;
const FNV64_OFFSET_A: u64 = 0xcbf2_9ce4_8422_2325;
const FNV64_OFFSET_B: u64 = 0x8422_2325_cbf2_9ce4;

#[repr(u16)]
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
pub enum CanonicalEventKindV2 {
    MarketObserved = 1,
    FundingApplied = 2,
    CommandSubmitted = 3,
    CommandAccepted = 4,
    CommandRejected = 5,
    OrderActivated = 6,
    OrderAmended = 7,
    OrderCanceled = 8,
    OrderExpired = 9,
    OrderTriggered = 10,
    FillCommitted = 11,
    FeeCharged = 12,
    PositionChanged = 13,
    CashChanged = 14,
    MarginChanged = 15,
    LiquidationStarted = 16,
    LiquidationFill = 17,
    LiquidationCompleted = 18,
    PackageStateChanged = 19,
    ReservationCreated = 20,
    ReservationConsumed = 21,
    ReservationReleased = 22,
    SettlementApplied = 23,
    RunCompleted = 24,
    AccountSnapshot = 25,
}

/// Field-specific values used for both trace comparison and canonicalization.
/// There is intentionally no global floating-point epsilon.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct TraceToleranceV2 {
    pub quantity_quantum: f64,
    pub price_quantum: f64,
    pub financial_quantum: f64,
    pub metric_quantum: f64,
}

impl Default for TraceToleranceV2 {
    fn default() -> Self {
        Self {
            quantity_quantum: 1e-12,
            price_quantum: 1e-10,
            financial_quantum: 1e-10,
            metric_quantum: 1e-8,
        }
    }
}

/// One allocation-free typed trace row. `None` IDs serialize as the signed
/// `-1` sentinel so Python and Rust can exchange a single fixed-width schema.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct CanonicalTraceRowV2 {
    pub sequence: u64,
    pub bar_index: BarIndex,
    pub event_timestamp_ns: TimestampNs,
    pub effective_timestamp_ns: TimestampNs,
    pub symbol_id: Option<SymbolId>,
    pub account_id: AccountId,
    pub package_id: Option<PackageId>,
    pub order_id: Option<ExternalOrderId>,
    pub event_kind: CanonicalEventKindV2,
    pub reason_code: i32,
    pub order_status_code: i32,
    pub qty: f64,
    pub price: f64,
    pub fee: f64,
    pub cash_before: f64,
    pub cash_after: f64,
    pub position_before: f64,
    pub position_after: f64,
    pub realized_pnl_before: f64,
    pub realized_pnl_after: f64,
    pub initial_margin_before: f64,
    pub initial_margin_after: f64,
    pub maintenance_margin_before: f64,
    pub maintenance_margin_after: f64,
    pub state_hash_before: Option<u64>,
    pub state_hash_after: Option<u64>,
}

/// Stable dual-FNV fingerprint. It is an evidence hash, not a signature.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
pub struct TraceHashV2 {
    pub first: u64,
    pub second: u64,
}

impl TraceHashV2 {
    #[must_use]
    pub fn hex(self) -> String {
        format!("{:016x}{:016x}", self.first, self.second)
    }
}

/// Terminal financial identity shared by score, compact, and audit profiles.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
pub struct TerminalFingerprintV2 {
    pub final_cash_hash: TraceHashV2,
    pub final_position_hash: TraceHashV2,
    pub final_order_hash: TraceHashV2,
    pub final_margin_hash: TraceHashV2,
    pub final_package_hash: TraceHashV2,
    pub trace_hash: TraceHashV2,
    pub metrics_hash: TraceHashV2,
}

#[must_use]
pub fn canonical_trace_hash_v2(
    rows: &[CanonicalTraceRowV2],
    policy: TraceToleranceV2,
) -> TraceHashV2 {
    let mut hasher = TraceHasherV2::new();
    hasher.update_bytes(b"QBT-CANONICAL-TRACE-V2\0");
    hasher.update_bytes(&(rows.len() as u64).to_le_bytes());
    for row in rows {
        row.write_canonical(&mut hasher, policy);
    }
    hasher.finish()
}

impl CanonicalTraceRowV2 {
    fn write_canonical(self, hasher: &mut TraceHasherV2, policy: TraceToleranceV2) {
        hasher.update_bytes(&self.sequence.to_le_bytes());
        hasher.update_bytes(&(self.bar_index.0 as i64).to_le_bytes());
        hasher.update_bytes(&self.event_timestamp_ns.0.to_le_bytes());
        hasher.update_bytes(&self.effective_timestamp_ns.0.to_le_bytes());
        hasher.update_bytes(&optional_u32(self.symbol_id).to_le_bytes());
        hasher.update_bytes(&(self.account_id.0 as i64).to_le_bytes());
        hasher.update_bytes(&optional_i64(self.package_id).to_le_bytes());
        hasher.update_bytes(&optional_i64(self.order_id).to_le_bytes());
        hasher.update_bytes(&(self.event_kind as u16 as i64).to_le_bytes());
        hasher.update_bytes(&(self.reason_code as i64).to_le_bytes());
        hasher.update_bytes(&(self.order_status_code as i64).to_le_bytes());
        hasher.update_bytes(&optional_u64(self.state_hash_before).to_le_bytes());
        hasher.update_bytes(&optional_u64(self.state_hash_after).to_le_bytes());
        write_float(hasher, canonicalize_f64(self.qty, policy.quantity_quantum));
        write_float(hasher, canonicalize_f64(self.price, policy.price_quantum));
        write_float(hasher, canonicalize_f64(self.fee, policy.financial_quantum));
        write_float(
            hasher,
            canonicalize_f64(self.cash_before, policy.financial_quantum),
        );
        write_float(
            hasher,
            canonicalize_f64(self.cash_after, policy.financial_quantum),
        );
        write_float(
            hasher,
            canonicalize_f64(self.position_before, policy.quantity_quantum),
        );
        write_float(
            hasher,
            canonicalize_f64(self.position_after, policy.quantity_quantum),
        );
        write_float(
            hasher,
            canonicalize_f64(self.realized_pnl_before, policy.financial_quantum),
        );
        write_float(
            hasher,
            canonicalize_f64(self.realized_pnl_after, policy.financial_quantum),
        );
        write_float(
            hasher,
            canonicalize_f64(self.initial_margin_before, policy.financial_quantum),
        );
        write_float(
            hasher,
            canonicalize_f64(self.initial_margin_after, policy.financial_quantum),
        );
        write_float(
            hasher,
            canonicalize_f64(self.maintenance_margin_before, policy.financial_quantum),
        );
        write_float(
            hasher,
            canonicalize_f64(self.maintenance_margin_after, policy.financial_quantum),
        );
    }
}

#[must_use]
pub fn canonicalize_f64(value: f64, quantum: f64) -> f64 {
    if !value.is_finite() || quantum <= 0.0 {
        return value;
    }
    let normalized = (value.abs() / quantum + 0.5).floor() * quantum;
    if normalized == 0.0 {
        0.0
    } else {
        normalized.copysign(value)
    }
}

struct TraceHasherV2 {
    first: u64,
    second: u64,
}

impl TraceHasherV2 {
    const fn new() -> Self {
        Self {
            first: FNV64_OFFSET_A,
            second: FNV64_OFFSET_B,
        }
    }

    fn update_bytes(&mut self, payload: &[u8]) {
        for byte in payload {
            self.first = (self.first ^ u64::from(*byte)).wrapping_mul(FNV64_PRIME);
            self.second = (self.second ^ u64::from(*byte ^ 0xa5)).wrapping_mul(FNV64_PRIME);
        }
    }

    const fn finish(self) -> TraceHashV2 {
        TraceHashV2 {
            first: self.first,
            second: self.second,
        }
    }
}

fn optional_u32(value: Option<SymbolId>) -> i64 {
    value.map_or(-1, |item| i64::from(item.0))
}

fn optional_i64(value: Option<impl Into<i64>>) -> i64 {
    value.map_or(-1, Into::into)
}

fn optional_u64(value: Option<u64>) -> i64 {
    value.map_or(-1, |item| i64::try_from(item).unwrap_or(i64::MAX))
}

fn write_float(hasher: &mut TraceHasherV2, value: f64) {
    if value.is_nan() {
        hasher.update_bytes(&[0]);
    } else {
        hasher.update_bytes(&[1]);
        hasher.update_bytes(&(if value == 0.0 { 0.0 } else { value }).to_le_bytes());
    }
}

impl From<PackageId> for i64 {
    fn from(value: PackageId) -> Self {
        value.0
    }
}

impl From<ExternalOrderId> for i64 {
    fn from(value: ExternalOrderId) -> Self {
        value.0
    }
}

#[cfg(test)]
mod tests {
    use super::{
        CanonicalEventKindV2, CanonicalTraceRowV2, TraceToleranceV2, canonical_trace_hash_v2,
    };
    use crate::ids::{AccountId, BarIndex, SymbolId, TimestampNs};

    fn row(sequence: u64) -> CanonicalTraceRowV2 {
        CanonicalTraceRowV2 {
            sequence,
            bar_index: BarIndex(2),
            event_timestamp_ns: TimestampNs(2_000),
            effective_timestamp_ns: TimestampNs(2_000),
            symbol_id: Some(SymbolId(3)),
            account_id: AccountId(0),
            package_id: None,
            order_id: None,
            event_kind: CanonicalEventKindV2::FillCommitted,
            reason_code: 0,
            order_status_code: 3,
            qty: 1.0,
            price: 100.0,
            fee: 0.05,
            cash_before: 1_000.0,
            cash_after: 999.95,
            position_before: 0.0,
            position_after: 1.0,
            realized_pnl_before: 0.0,
            realized_pnl_after: 0.0,
            initial_margin_before: 0.0,
            initial_margin_after: 20.0,
            maintenance_margin_before: 0.0,
            maintenance_margin_after: 1.0,
            state_hash_before: None,
            state_hash_after: None,
        }
    }

    #[test]
    fn trace_hash_is_repeatable_and_sequence_sensitive() {
        let policy = TraceToleranceV2::default();
        let first = canonical_trace_hash_v2(&[row(0)], policy);
        let repeated = canonical_trace_hash_v2(&[row(0)], policy);
        let changed = canonical_trace_hash_v2(&[row(1)], policy);
        assert_eq!(first, repeated);
        assert_ne!(first, changed);
        assert_eq!(first.hex().len(), 32);
        // Cross-language vector generated by the independent Python V2
        // serializer. This locks byte order, NaN/sentinel layout, and the
        // dual-FNV implementation without binding a Python runtime here.
        assert_eq!(first.hex(), "9bf92586ed52388d26e71e0bd2afe920");
    }

    #[test]
    fn trace_hash_normalizes_declared_financial_quantum_only() {
        let policy = TraceToleranceV2::default();
        let first = canonical_trace_hash_v2(&[row(0)], policy);
        let mut within = row(0);
        within.cash_after += 4e-11;
        assert_eq!(first, canonical_trace_hash_v2(&[within], policy));
        let mut outside = row(0);
        outside.cash_after += 2e-10;
        assert_ne!(first, canonical_trace_hash_v2(&[outside], policy));
    }

    #[test]
    fn bounded_generated_rows_are_deterministic_and_order_sensitive() {
        let policy = TraceToleranceV2::default();
        let mut state = 0x9e37_79b9_u64;
        let mut rows = Vec::with_capacity(128);
        for sequence in 0..128_u64 {
            state = state
                .wrapping_mul(6_364_136_223_846_793_005)
                .wrapping_add(1);
            let mut generated = row(sequence);
            generated.price = 50.0 + (state % 10_000) as f64 / 100.0;
            generated.qty = 1.0 + (state % 1_000) as f64 / 1_000.0;
            generated.cash_after = 1_000.0 - generated.price * generated.qty;
            rows.push(generated);
        }
        let first = canonical_trace_hash_v2(&rows, policy);
        let repeated = canonical_trace_hash_v2(&rows, policy);
        rows.swap(7, 8);
        let reordered = canonical_trace_hash_v2(&rows, policy);
        assert_eq!(first, repeated);
        assert_ne!(first, reordered);
    }
}
