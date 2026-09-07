//! Canonical V1 linear quote-settled gross-cross account transitions.
//!
//! This module is deliberately part of the existing `quantbt-engine::account`
//! substrate.  It is the accounting authority consumed first by FillReplay V2;
//! later event/target/portfolio/package migrations must call this state rather
//! than reimplementing fill arithmetic beside it.

use std::collections::{BTreeMap, BTreeSet};

use quantbt_domain::enums::Side;
use quantbt_domain::ids::SymbolId;
use quantbt_domain::trace_v2::canonicalize_f64;

use super::PositionBook;

const EPSILON: f64 = 1e-12;
// Trace checkpoint hashes are evidence at a deliberately coarser precision
// than individual trace fields. This avoids turning harmless cross-language
// last-bit arithmetic differences into a false state divergence.
const CANONICAL_FINANCIAL_HASH_QUANTUM: f64 = 1e-6;
const FNV64_PRIME: u64 = 0x0000_0100_0000_01b3;
const FNV64_OFFSET_A: u64 = 0xcbf2_9ce4_8422_2325;
const FNV64_OFFSET_B: u64 = 0x8422_2325_cbf2_9ce4;

/// Immutable one-currency linear account inputs.
#[derive(Clone, Debug, PartialEq)]
pub struct LinearAccountConfigV1 {
    pub initial_cash: f64,
    pub maintenance_ratio: f64,
    pub contract_sizes: Box<[f64]>,
    pub leverages: Box<[f64]>,
    /// Certification builds can scan every transition; score paths retain the
    /// same arithmetic but may explicitly disable this O(symbols) audit.
    pub invariant_checks: bool,
}

impl LinearAccountConfigV1 {
    pub fn new(
        initial_cash: f64,
        maintenance_ratio: f64,
        contract_sizes: Vec<f64>,
        leverages: Vec<f64>,
    ) -> Result<Self, AccountingRejectCodeV1> {
        if !initial_cash.is_finite()
            || initial_cash < 0.0
            || !maintenance_ratio.is_finite()
            || maintenance_ratio < 0.0
            || contract_sizes.is_empty()
            || contract_sizes.len() != leverages.len()
            || contract_sizes
                .iter()
                .any(|value| !value.is_finite() || *value <= 0.0)
            || leverages
                .iter()
                .any(|value| !value.is_finite() || *value <= 0.0)
        {
            return Err(AccountingRejectCodeV1::InvalidAccountConfig);
        }
        Ok(Self {
            initial_cash,
            maintenance_ratio,
            contract_sizes: contract_sizes.into_boxed_slice(),
            leverages: leverages.into_boxed_slice(),
            invariant_checks: cfg!(debug_assertions),
        })
    }

    #[must_use]
    pub const fn with_invariant_checks(mut self, enabled: bool) -> Self {
        self.invariant_checks = enabled;
        self
    }

    #[must_use]
    pub fn n_symbols(&self) -> usize {
        self.contract_sizes.len()
    }
}

/// Deterministic, typed reasons for a rejected transition.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(i32)]
pub enum AccountingRejectCodeV1 {
    Accepted = 0,
    InvalidAccountConfig = 1,
    InvalidSymbol = 2,
    InvalidQuantity = 3,
    InvalidPrice = 4,
    InvalidFee = 5,
    InvalidMark = 6,
    PostCostMargin = 7,
    TerminalLiquidation = 8,
    StalePreview = 9,
    UnknownReservation = 10,
    ReservationMismatch = 11,
    DuplicateFundingEvent = 12,
    InvariantViolation = 13,
}

impl AccountingRejectCodeV1 {
    #[must_use]
    pub const fn name(self) -> &'static str {
        match self {
            Self::Accepted => "ACCEPTED",
            Self::InvalidAccountConfig => "INVALID_ACCOUNT_CONFIG",
            Self::InvalidSymbol => "INVALID_SYMBOL",
            Self::InvalidQuantity => "INVALID_QUANTITY",
            Self::InvalidPrice => "INVALID_PRICE",
            Self::InvalidFee => "INVALID_FEE",
            Self::InvalidMark => "INVALID_MARK",
            Self::PostCostMargin => "POST_COST_MARGIN",
            Self::TerminalLiquidation => "TERMINAL_LIQUIDATION",
            Self::StalePreview => "STALE_PREVIEW",
            Self::UnknownReservation => "UNKNOWN_RESERVATION",
            Self::ReservationMismatch => "RESERVATION_MISMATCH",
            Self::DuplicateFundingEvent => "DUPLICATE_FUNDING_EVENT",
            Self::InvariantViolation => "INVARIANT_VIOLATION",
        }
    }
}

/// Explicit state instead of a terminal-only liquidation boolean.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(i32)]
pub enum LiquidationStateV1 {
    Healthy = 0,
    Breached = 1,
    CancelingOrders = 2,
    ReducingPositions = 3,
    Rechecking = 4,
    Liquidated = 5,
    Bankrupt = 6,
}

impl LiquidationStateV1 {
    #[must_use]
    pub const fn is_terminal(self) -> bool {
        matches!(self, Self::Liquidated | Self::Bankrupt)
    }
}

/// One candidate linear fill. `signed_qty > 0` buys and `< 0` sells.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct CandidateFillV1 {
    pub event_id: u64,
    pub symbol: SymbolId,
    pub signed_qty: f64,
    pub price: f64,
    pub fee: f64,
    pub mark_price: f64,
}

/// Scheduled funding is separate from matching/fill rows and carries an
/// apply-once identifier. Positive rates charge long positions.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ScheduledFundingEventV1 {
    pub event_id: u64,
    pub symbol: SymbolId,
    pub rate: f64,
}

/// A deterministic dual-FNV state identity. It is evidence, not a signature.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
pub struct AccountFingerprintV1 {
    pub first: u64,
    pub second: u64,
}

impl AccountFingerprintV1 {
    #[must_use]
    pub fn hex(self) -> String {
        format!("{:016x}{:016x}", self.first, self.second)
    }
}

/// One immutable projected account state used by previews and audit rows.
#[derive(Clone, Debug, PartialEq)]
pub struct LinearAccountSnapshotV1 {
    pub cash: f64,
    pub realized_pnl: f64,
    pub fees_paid: f64,
    pub funding_paid: f64,
    pub qty: Box<[f64]>,
    pub average_entry: Box<[f64]>,
    pub marks: Box<[f64]>,
    pub initial_margin: f64,
    pub maintenance_margin: f64,
    pub reserved_margin: f64,
    pub equity: f64,
    pub available_equity: f64,
    pub liquidation_state: LiquidationStateV1,
    /// Tolerance-normalized state identity for cross-language canonical trace
    /// rows. This is distinct from the exact internal fingerprint used for
    /// preview staleness and reservation integrity.
    pub canonical_state_hash: u64,
    pub fingerprint: AccountFingerprintV1,
}

/// Aggregate gross-cross margin at one deterministic mark set.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct AccountMarginV1 {
    pub equity: f64,
    pub initial_margin: f64,
    pub maintenance_margin: f64,
    pub reserved_margin: f64,
    pub available_equity: f64,
}

/// A side-effect-free fill projection.
#[derive(Clone, Debug, PartialEq)]
pub struct FillPreviewV1 {
    pub event_id: u64,
    pub base_generation: u64,
    pub base_fingerprint: AccountFingerprintV1,
    pub candidate: CandidateFillV1,
    pub projected: LinearAccountSnapshotV1,
    pub reservation_amount: f64,
}

/// A reservation binds one accepted preview until it is consumed or released.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ReservationTokenV1 {
    pub id: u64,
    pub event_id: u64,
    pub amount: f64,
    generation: u64,
}

/// Internal reservation state. The token binds the exact accepted candidate,
/// not only an event ID, so collateral cannot be consumed by another fill.
#[derive(Clone, Debug, PartialEq)]
struct ReservationRecordV1 {
    token: ReservationTokenV1,
    candidate: CandidateFillV1,
}

/// Canonical before/after accounting delta for a committed fill.
#[derive(Clone, Debug, PartialEq)]
pub struct AccountDeltaV1 {
    pub event_id: u64,
    pub symbol: SymbolId,
    pub signed_qty: f64,
    pub price: f64,
    pub fee: f64,
    pub realized_pnl: f64,
    pub before: LinearAccountSnapshotV1,
    pub after: LinearAccountSnapshotV1,
    pub reservation: Option<ReservationTokenV1>,
}

/// Canonical before/after accounting delta for one funding event.
#[derive(Clone, Debug, PartialEq)]
pub struct FundingDeltaV1 {
    pub event_id: u64,
    pub symbol: SymbolId,
    pub rate: f64,
    pub charge: f64,
    pub before: LinearAccountSnapshotV1,
    pub after: LinearAccountSnapshotV1,
}

/// The explicit fills created by a liquidation state transition.
#[derive(Clone, Debug, PartialEq)]
pub struct LiquidationTransitionV1 {
    pub state_before: LiquidationStateV1,
    pub state_after: LiquidationStateV1,
    pub before: LinearAccountSnapshotV1,
    pub after: LinearAccountSnapshotV1,
    pub fills: Vec<AccountDeltaV1>,
}

/// The stable transaction protocol shared by current and future consumers.
pub trait LinearAccountTransactionV1 {
    fn preview_fill(&self, fill: &CandidateFillV1)
    -> Result<FillPreviewV1, AccountingRejectCodeV1>;
    fn reserve(
        &mut self,
        preview: &FillPreviewV1,
    ) -> Result<ReservationTokenV1, AccountingRejectCodeV1>;
    fn commit_fill(
        &mut self,
        token: Option<&ReservationTokenV1>,
        fill: &CandidateFillV1,
    ) -> Result<AccountDeltaV1, AccountingRejectCodeV1>;
    fn release(&mut self, token: ReservationTokenV1) -> Result<(), AccountingRejectCodeV1>;
}

/// The V1.1 linear quote-settled gross-cross account authority.
#[derive(Clone, Debug)]
pub struct LinearGrossCrossAccountV1 {
    pub config: LinearAccountConfigV1,
    pub cash: f64,
    pub realized_pnl: f64,
    pub fees_paid: f64,
    pub funding_paid: f64,
    pub positions: PositionBook,
    pub initial_margin: f64,
    pub maintenance_margin: f64,
    pub reserved_margin: f64,
    pub equity: f64,
    pub available_equity: f64,
    pub liquidation_state: LiquidationStateV1,
    signed_fill_totals: Vec<f64>,
    funding_event_ids: BTreeSet<u64>,
    reservations: BTreeMap<u64, ReservationRecordV1>,
    reservation_created: f64,
    reservation_consumed: f64,
    reservation_released: f64,
    generation: u64,
    next_reservation_id: u64,
}

impl LinearGrossCrossAccountV1 {
    pub fn new(config: LinearAccountConfigV1) -> Self {
        let n_symbols = config.n_symbols();
        let initial_cash = config.initial_cash;
        Self {
            config,
            cash: initial_cash,
            realized_pnl: 0.0,
            fees_paid: 0.0,
            funding_paid: 0.0,
            positions: PositionBook::new(n_symbols),
            initial_margin: 0.0,
            maintenance_margin: 0.0,
            reserved_margin: 0.0,
            equity: initial_cash,
            available_equity: initial_cash,
            liquidation_state: LiquidationStateV1::Healthy,
            signed_fill_totals: vec![0.0; n_symbols],
            funding_event_ids: BTreeSet::new(),
            reservations: BTreeMap::new(),
            reservation_created: 0.0,
            reservation_consumed: 0.0,
            reservation_released: 0.0,
            generation: 0,
            next_reservation_id: 1,
        }
    }

    #[must_use]
    pub fn n_symbols(&self) -> usize {
        self.config.n_symbols()
    }

    #[must_use]
    pub fn generation(&self) -> u64 {
        self.generation
    }

    #[must_use]
    pub fn margin(&self) -> AccountMarginV1 {
        AccountMarginV1 {
            equity: self.equity,
            initial_margin: self.initial_margin,
            maintenance_margin: self.maintenance_margin,
            reserved_margin: self.reserved_margin,
            available_equity: self.available_equity,
        }
    }

    #[must_use]
    pub fn snapshot(&self) -> LinearAccountSnapshotV1 {
        LinearAccountSnapshotV1 {
            cash: self.cash,
            realized_pnl: self.realized_pnl,
            fees_paid: self.fees_paid,
            funding_paid: self.funding_paid,
            qty: self.positions.qty.clone().into_boxed_slice(),
            average_entry: self.positions.avg_entry.clone().into_boxed_slice(),
            marks: self.positions.mark.clone().into_boxed_slice(),
            initial_margin: self.initial_margin,
            maintenance_margin: self.maintenance_margin,
            reserved_margin: self.reserved_margin,
            equity: self.equity,
            available_equity: self.available_equity,
            liquidation_state: self.liquidation_state,
            canonical_state_hash: self.canonical_trace_state_hash(),
            fingerprint: self.fingerprint(),
        }
    }

    /// Hash the account after contract-level numeric normalization.
    ///
    /// The exact [`Self::fingerprint`] intentionally observes every IEEE-754
    /// bit so it can guard transaction staleness inside one Rust process. A
    /// canonical trace instead needs stable equality across independently
    /// implemented arithmetic with declared field tolerances. This hash uses
    /// the V2 quantity, price and financial quanta before encoding state.
    #[must_use]
    pub fn canonical_trace_state_hash(&self) -> u64 {
        let mut first = FNV64_OFFSET_A;
        let mut second = FNV64_OFFSET_B;
        hash_bytes(
            &mut first,
            &mut second,
            b"QBT-LINEAR-GROSS-CROSS-CANONICAL-STATE-V1\0",
        );
        for value in [
            self.config.initial_cash,
            self.cash,
            self.realized_pnl,
            self.fees_paid,
            self.funding_paid,
            self.initial_margin,
            self.maintenance_margin,
            self.reserved_margin,
            self.equity,
            self.available_equity,
        ] {
            hash_canonical_f64(
                &mut first,
                &mut second,
                value,
                CANONICAL_FINANCIAL_HASH_QUANTUM,
            );
        }
        hash_canonical_f64(
            &mut first,
            &mut second,
            self.config.maintenance_ratio,
            1e-12,
        );
        hash_bytes(
            &mut first,
            &mut second,
            &(self.liquidation_state as i32 as i64).to_le_bytes(),
        );
        for index in 0..self.n_symbols() {
            hash_canonical_f64(
                &mut first,
                &mut second,
                self.config.contract_sizes[index],
                1e-10,
            );
            hash_canonical_f64(&mut first, &mut second, self.config.leverages[index], 1e-10);
            hash_canonical_f64(&mut first, &mut second, self.positions.qty[index], 1e-12);
            hash_canonical_f64(
                &mut first,
                &mut second,
                self.positions.avg_entry[index],
                1e-10,
            );
            hash_canonical_f64(&mut first, &mut second, self.positions.mark[index], 1e-10);
            hash_canonical_f64(
                &mut first,
                &mut second,
                self.signed_fill_totals[index],
                1e-12,
            );
        }
        for event_id in &self.funding_event_ids {
            hash_bytes(&mut first, &mut second, &event_id.to_le_bytes());
        }
        for record in self.reservations.values() {
            let token = record.token;
            hash_bytes(&mut first, &mut second, &token.id.to_le_bytes());
            hash_bytes(&mut first, &mut second, &token.event_id.to_le_bytes());
            hash_canonical_f64(
                &mut first,
                &mut second,
                token.amount,
                CANONICAL_FINANCIAL_HASH_QUANTUM,
            );
            hash_bytes(
                &mut first,
                &mut second,
                &u64::from(record.candidate.symbol.0).to_le_bytes(),
            );
            hash_canonical_f64(&mut first, &mut second, record.candidate.signed_qty, 1e-12);
            hash_canonical_f64(&mut first, &mut second, record.candidate.price, 1e-10);
            hash_canonical_f64(
                &mut first,
                &mut second,
                record.candidate.fee,
                CANONICAL_FINANCIAL_HASH_QUANTUM,
            );
            hash_canonical_f64(&mut first, &mut second, record.candidate.mark_price, 1e-10);
        }
        first
    }

    #[must_use]
    pub fn fingerprint(&self) -> AccountFingerprintV1 {
        let mut first = FNV64_OFFSET_A;
        let mut second = FNV64_OFFSET_B;
        hash_bytes(
            &mut first,
            &mut second,
            b"QBT-LINEAR-GROSS-CROSS-ACCOUNT-V1\0",
        );
        for value in [
            self.config.initial_cash,
            self.config.maintenance_ratio,
            self.cash,
            self.realized_pnl,
            self.fees_paid,
            self.funding_paid,
            self.initial_margin,
            self.maintenance_margin,
            self.reserved_margin,
            self.equity,
            self.available_equity,
        ] {
            hash_bytes(&mut first, &mut second, &value.to_bits().to_le_bytes());
        }
        hash_bytes(
            &mut first,
            &mut second,
            &(self.liquidation_state as i32 as i64).to_le_bytes(),
        );
        for index in 0..self.n_symbols() {
            for value in [
                self.config.contract_sizes[index],
                self.config.leverages[index],
                self.positions.qty[index],
                self.positions.avg_entry[index],
                self.positions.mark[index],
                self.signed_fill_totals[index],
            ] {
                hash_bytes(&mut first, &mut second, &value.to_bits().to_le_bytes());
            }
        }
        for event_id in &self.funding_event_ids {
            hash_bytes(&mut first, &mut second, &event_id.to_le_bytes());
        }
        for record in self.reservations.values() {
            let token = record.token;
            hash_bytes(&mut first, &mut second, &token.id.to_le_bytes());
            hash_bytes(&mut first, &mut second, &token.event_id.to_le_bytes());
            hash_bytes(
                &mut first,
                &mut second,
                &token.amount.to_bits().to_le_bytes(),
            );
            hash_bytes(
                &mut first,
                &mut second,
                &u64::from(record.candidate.symbol.0).to_le_bytes(),
            );
            for value in [
                record.candidate.signed_qty,
                record.candidate.price,
                record.candidate.fee,
                record.candidate.mark_price,
            ] {
                hash_bytes(&mut first, &mut second, &value.to_bits().to_le_bytes());
            }
        }
        AccountFingerprintV1 { first, second }
    }

    /// Observe one complete bar mark set and update cross-margin state.
    pub fn observe_marks(
        &mut self,
        marks: &[f64],
    ) -> Result<AccountMarginV1, AccountingRejectCodeV1> {
        if marks.len() != self.n_symbols() {
            return Err(AccountingRejectCodeV1::InvalidMark);
        }
        // Validate the complete market observation before changing any symbol.
        // A malformed late symbol must leave the pre-bar account untouched.
        for mark in marks {
            if !mark.is_finite() || *mark <= 0.0 {
                return Err(AccountingRejectCodeV1::InvalidMark);
            }
        }
        for (index, mark) in marks.iter().enumerate() {
            self.positions.mark_symbol(
                SymbolId(index as u32),
                *mark,
                self.config.contract_sizes[index],
                self.config.leverages[index],
                self.config.maintenance_ratio,
            );
        }
        self.recompute_margin();
        self.bump_generation()?;
        self.maybe_assert_invariants()?;
        Ok(self.margin())
    }

    /// Apply one scheduled funding event only once. A duplicate ID is rejected
    /// without mutating account state.
    pub fn apply_funding_once(
        &mut self,
        event: ScheduledFundingEventV1,
    ) -> Result<FundingDeltaV1, AccountingRejectCodeV1> {
        let index = self.validate_funding(event)?;
        if self.funding_event_ids.contains(&event.event_id) {
            return Err(AccountingRejectCodeV1::DuplicateFundingEvent);
        }
        let mark = self.positions.mark[index];
        if !mark.is_finite() || mark <= 0.0 {
            return Err(AccountingRejectCodeV1::InvalidMark);
        }
        let before = self.snapshot();
        let charge =
            self.positions.qty[index] * mark * self.config.contract_sizes[index] * event.rate;
        self.cash -= charge;
        self.funding_paid += charge;
        self.funding_event_ids.insert(event.event_id);
        self.recompute_margin();
        self.bump_generation()?;
        self.maybe_assert_invariants()?;
        Ok(FundingDeltaV1 {
            event_id: event.event_id,
            symbol: event.symbol,
            rate: event.rate,
            charge,
            before,
            after: self.snapshot(),
        })
    }

    /// Deterministically close all open symbols at the current marks after a
    /// maintenance breach. The generated fills are ordinary accounting deltas.
    pub fn liquidate_if_breached(
        &mut self,
        liquidation_fee_rate: f64,
    ) -> Result<Option<LiquidationTransitionV1>, AccountingRejectCodeV1> {
        if !liquidation_fee_rate.is_finite() || liquidation_fee_rate < 0.0 {
            return Err(AccountingRejectCodeV1::InvalidFee);
        }
        if self.liquidation_state.is_terminal() || !self.maintenance_breached() {
            return Ok(None);
        }
        // Build the forced-close transaction on a clone. An invalid mark or a
        // failed invariant must never leave a half-liquidated account behind.
        let before = self.snapshot();
        let mut projected = self.clone();
        let state_before = projected.liquidation_state;
        projected.liquidation_state = LiquidationStateV1::Breached;
        projected.liquidation_state = LiquidationStateV1::CancelingOrders;
        projected.liquidation_state = LiquidationStateV1::ReducingPositions;
        let mut active = projected.positions.active_symbols().to_vec();
        active.sort_unstable_by_key(|symbol| symbol.0);
        let mut fills = Vec::with_capacity(active.len());
        for symbol in active {
            let index = symbol.0 as usize;
            let quantity = projected.positions.qty[index];
            if quantity.abs() <= EPSILON {
                continue;
            }
            let price = projected.positions.mark[index];
            if !price.is_finite() || price <= 0.0 {
                return Err(AccountingRejectCodeV1::InvalidMark);
            }
            let signed_qty = -quantity;
            let fee = signed_qty.abs()
                * price
                * projected.config.contract_sizes[index]
                * liquidation_fee_rate;
            fills.push(projected.apply_fill_unchecked(
                CandidateFillV1 {
                    event_id: u64::MAX - u64::from(symbol.0),
                    symbol,
                    signed_qty,
                    price,
                    fee,
                    mark_price: price,
                },
                None,
            )?);
        }
        projected.liquidation_state = LiquidationStateV1::Rechecking;
        if projected.positions.active_symbols().is_empty() {
            projected.liquidation_state = if projected.equity < -EPSILON {
                LiquidationStateV1::Bankrupt
            } else {
                LiquidationStateV1::Liquidated
            };
        }
        projected.bump_generation()?;
        projected.maybe_assert_invariants()?;
        let after = projected.snapshot();
        let state_after = projected.liquidation_state;
        *self = projected;
        Ok(Some(LiquidationTransitionV1 {
            state_before,
            state_after,
            before,
            after,
            fills,
        }))
    }

    #[must_use]
    pub fn maintenance_breached(&self) -> bool {
        self.maintenance_margin > 0.0 && self.equity <= self.maintenance_margin + EPSILON
    }

    #[must_use]
    pub fn reservation_balance(&self) -> f64 {
        self.reservation_created - self.reservation_consumed - self.reservation_released
    }

    /// Certification-only invariant scan. It is intentionally explicit so the
    /// release hot path can avoid repeated full scans once certified.
    pub fn assert_invariants(&self) -> Result<(), AccountingRejectCodeV1> {
        let sum_realized: f64 = self.positions.realized.iter().sum();
        let sum_unrealized: f64 = self.positions.unrealized.iter().sum();
        let sum_initial: f64 = self.positions.initial_margin.iter().sum();
        let sum_maintenance: f64 = self.positions.maintenance_margin.iter().sum();
        let active_reservations: f64 = self
            .reservations
            .values()
            .map(|record| record.token.amount)
            .sum();
        let cash_expected =
            self.config.initial_cash + self.realized_pnl - self.fees_paid - self.funding_paid;
        let checks = [
            approximately_equal(self.realized_pnl, sum_realized),
            approximately_equal(self.cash, cash_expected),
            approximately_equal(self.initial_margin, sum_initial),
            approximately_equal(self.maintenance_margin, sum_maintenance),
            approximately_equal(self.reserved_margin, active_reservations),
            approximately_equal(self.reservation_balance(), self.reserved_margin),
            approximately_equal(self.equity, self.cash + sum_unrealized),
            approximately_equal(
                self.available_equity,
                self.equity - self.initial_margin - self.reserved_margin,
            ),
            self.reserved_margin >= -EPSILON,
        ];
        if checks.iter().any(|value| !*value) {
            return Err(AccountingRejectCodeV1::InvariantViolation);
        }
        for index in 0..self.n_symbols() {
            let qty = self.positions.qty[index];
            let average = self.positions.avg_entry[index];
            if !approximately_equal(qty, self.signed_fill_totals[index])
                || (qty.abs() <= EPSILON && average.abs() > EPSILON)
                || (qty.abs() > EPSILON && (!average.is_finite() || average <= 0.0))
            {
                return Err(AccountingRejectCodeV1::InvariantViolation);
            }
        }
        if self.liquidation_state.is_terminal() && !self.positions.active_symbols().is_empty() {
            return Err(AccountingRejectCodeV1::InvariantViolation);
        }
        Ok(())
    }

    fn validate_fill(&self, fill: CandidateFillV1) -> Result<usize, AccountingRejectCodeV1> {
        let index = fill.symbol.0 as usize;
        if index >= self.n_symbols() {
            return Err(AccountingRejectCodeV1::InvalidSymbol);
        }
        if !fill.signed_qty.is_finite() || fill.signed_qty.abs() <= EPSILON {
            return Err(AccountingRejectCodeV1::InvalidQuantity);
        }
        if !fill.price.is_finite() || fill.price <= 0.0 {
            return Err(AccountingRejectCodeV1::InvalidPrice);
        }
        if !fill.mark_price.is_finite() || fill.mark_price <= 0.0 {
            return Err(AccountingRejectCodeV1::InvalidMark);
        }
        if !fill.fee.is_finite() || fill.fee < 0.0 {
            return Err(AccountingRejectCodeV1::InvalidFee);
        }
        Ok(index)
    }

    fn validate_funding(
        &self,
        event: ScheduledFundingEventV1,
    ) -> Result<usize, AccountingRejectCodeV1> {
        let index = event.symbol.0 as usize;
        if index >= self.n_symbols() {
            return Err(AccountingRejectCodeV1::InvalidSymbol);
        }
        if !event.rate.is_finite() {
            return Err(AccountingRejectCodeV1::InvalidFee);
        }
        Ok(index)
    }

    fn apply_fill_unchecked(
        &mut self,
        fill: CandidateFillV1,
        reservation: Option<ReservationTokenV1>,
    ) -> Result<AccountDeltaV1, AccountingRejectCodeV1> {
        let index = self.validate_fill(fill)?;
        let before = self.snapshot();
        let side = if fill.signed_qty > 0.0 {
            Side::Buy
        } else {
            Side::Sell
        };
        let quantity = fill.signed_qty.abs();
        let delta = self.positions.apply_fill(
            fill.symbol,
            side,
            quantity,
            fill.price,
            self.config.contract_sizes[index],
        );
        self.signed_fill_totals[index] += fill.signed_qty;
        self.cash += delta.realized_pnl - fill.fee;
        self.realized_pnl += delta.realized_pnl;
        self.fees_paid += fill.fee;
        self.positions.mark_symbol(
            fill.symbol,
            fill.mark_price,
            self.config.contract_sizes[index],
            self.config.leverages[index],
            self.config.maintenance_ratio,
        );
        self.recompute_margin();
        self.maybe_assert_invariants()?;
        Ok(AccountDeltaV1 {
            event_id: fill.event_id,
            symbol: fill.symbol,
            signed_qty: fill.signed_qty,
            price: fill.price,
            fee: fill.fee,
            realized_pnl: delta.realized_pnl,
            before,
            after: self.snapshot(),
            reservation,
        })
    }

    fn recompute_margin(&mut self) {
        self.initial_margin = self.positions.initial_margin.iter().sum();
        self.maintenance_margin = self.positions.maintenance_margin.iter().sum();
        let unrealized: f64 = self.positions.unrealized.iter().sum();
        self.equity = self.cash + unrealized;
        self.available_equity = self.equity - self.initial_margin - self.reserved_margin;
    }

    fn maybe_assert_invariants(&self) -> Result<(), AccountingRejectCodeV1> {
        if self.config.invariant_checks {
            self.assert_invariants()?;
        }
        Ok(())
    }

    fn bump_generation(&mut self) -> Result<(), AccountingRejectCodeV1> {
        self.generation = self
            .generation
            .checked_add(1)
            .ok_or(AccountingRejectCodeV1::InvariantViolation)?;
        Ok(())
    }
}

impl LinearAccountTransactionV1 for LinearGrossCrossAccountV1 {
    fn preview_fill(
        &self,
        fill: &CandidateFillV1,
    ) -> Result<FillPreviewV1, AccountingRejectCodeV1> {
        if self.liquidation_state.is_terminal() {
            return Err(AccountingRejectCodeV1::TerminalLiquidation);
        }
        self.validate_fill(*fill)?;
        let mut projected = self.clone();
        let before_available = projected.available_equity;
        projected.apply_fill_unchecked(*fill, None)?;
        if projected.available_equity < -EPSILON
            || projected.equity + EPSILON < projected.maintenance_margin
        {
            return Err(AccountingRejectCodeV1::PostCostMargin);
        }
        Ok(FillPreviewV1 {
            event_id: fill.event_id,
            base_generation: self.generation,
            base_fingerprint: self.fingerprint(),
            candidate: *fill,
            projected: projected.snapshot(),
            reservation_amount: (before_available - projected.available_equity).max(0.0),
        })
    }

    fn reserve(
        &mut self,
        preview: &FillPreviewV1,
    ) -> Result<ReservationTokenV1, AccountingRejectCodeV1> {
        if self.generation != preview.base_generation
            || self.fingerprint() != preview.base_fingerprint
        {
            return Err(AccountingRejectCodeV1::StalePreview);
        }
        let token = ReservationTokenV1 {
            id: self.next_reservation_id,
            event_id: preview.event_id,
            amount: preview.reservation_amount,
            generation: self
                .generation
                .checked_add(1)
                .ok_or(AccountingRejectCodeV1::InvariantViolation)?,
        };
        self.next_reservation_id = self
            .next_reservation_id
            .checked_add(1)
            .ok_or(AccountingRejectCodeV1::InvariantViolation)?;
        self.reserved_margin += token.amount;
        self.reservation_created += token.amount;
        self.reservations.insert(
            token.id,
            ReservationRecordV1 {
                token,
                candidate: preview.candidate,
            },
        );
        self.recompute_margin();
        self.bump_generation()?;
        self.maybe_assert_invariants()?;
        Ok(token)
    }

    fn commit_fill(
        &mut self,
        token: Option<&ReservationTokenV1>,
        fill: &CandidateFillV1,
    ) -> Result<AccountDeltaV1, AccountingRejectCodeV1> {
        if let Some(token) = token {
            let active = self
                .reservations
                .get(&token.id)
                .ok_or(AccountingRejectCodeV1::UnknownReservation)?;
            if active.token != *token
                || active.candidate != *fill
                || token.event_id != fill.event_id
                || token.generation != self.generation
            {
                return Err(AccountingRejectCodeV1::ReservationMismatch);
            }
            // Only publish after the reservation-consumption and fill
            // transition both succeed. This preserves abort immutability.
            let mut projected = self.clone();
            projected.reservations.remove(&token.id);
            projected.reserved_margin -= token.amount;
            projected.reservation_consumed += token.amount;
            projected.recompute_margin();
            let delta = projected.apply_fill_unchecked(*fill, Some(*token))?;
            projected.bump_generation()?;
            projected.maybe_assert_invariants()?;
            *self = projected;
            return Ok(delta);
        }

        self.preview_fill(fill)?;
        let delta = self.apply_fill_unchecked(*fill, None)?;
        self.bump_generation()?;
        self.maybe_assert_invariants()?;
        Ok(delta)
    }

    fn release(&mut self, token: ReservationTokenV1) -> Result<(), AccountingRejectCodeV1> {
        let active = self
            .reservations
            .get(&token.id)
            .ok_or(AccountingRejectCodeV1::UnknownReservation)?;
        if active.token != token || token.generation != self.generation {
            return Err(AccountingRejectCodeV1::ReservationMismatch);
        }
        self.reservations.remove(&token.id);
        self.reserved_margin -= token.amount;
        self.reservation_released += token.amount;
        self.recompute_margin();
        self.bump_generation()?;
        self.maybe_assert_invariants()?;
        Ok(())
    }
}

fn approximately_equal(left: f64, right: f64) -> bool {
    (left - right).abs() <= 1e-9_f64.max(1e-12 * left.abs().max(right.abs()))
}

fn hash_bytes(first: &mut u64, second: &mut u64, bytes: &[u8]) {
    for byte in bytes {
        *first ^= u64::from(*byte);
        *first = first.wrapping_mul(FNV64_PRIME);
        *second ^= u64::from(*byte);
        *second = second.wrapping_mul(FNV64_PRIME);
    }
}

fn hash_canonical_f64(first: &mut u64, second: &mut u64, value: f64, quantum: f64) {
    let normalized = canonicalize_f64(value, quantum);
    hash_bytes(first, second, &normalized.to_bits().to_le_bytes());
}

#[cfg(test)]
mod tests {
    use super::{
        AccountingRejectCodeV1, CandidateFillV1, LinearAccountConfigV1, LinearAccountTransactionV1,
        LinearGrossCrossAccountV1, LiquidationStateV1, ScheduledFundingEventV1,
    };
    use quantbt_domain::ids::SymbolId;

    fn account() -> LinearGrossCrossAccountV1 {
        let config =
            LinearAccountConfigV1::new(1_000.0, 0.005, vec![1.0, 2.0], vec![5.0, 5.0]).unwrap();
        let mut account = LinearGrossCrossAccountV1::new(config);
        account.observe_marks(&[100.0, 50.0]).unwrap();
        account
    }

    #[test]
    fn preview_reject_and_release_are_state_immutable() {
        let mut account = account();
        let before = account.fingerprint();
        let rejected = CandidateFillV1 {
            event_id: 1,
            symbol: SymbolId(0),
            signed_qty: 100.0,
            price: 100.0,
            fee: 1.0,
            mark_price: 100.0,
        };
        assert_eq!(
            account.preview_fill(&rejected),
            Err(AccountingRejectCodeV1::PostCostMargin)
        );
        assert_eq!(account.fingerprint(), before);

        let accepted = CandidateFillV1 {
            signed_qty: 1.0,
            event_id: 2,
            ..rejected
        };
        let preview = account.preview_fill(&accepted).unwrap();
        let token = account.reserve(&preview).unwrap();
        assert!(account.reserved_margin >= 0.0);
        account.release(token).unwrap();
        assert_eq!(account.fingerprint(), before);
        assert!(account.reservation_balance().abs() <= 1e-12);
    }

    #[test]
    fn invalid_zero_quantity_and_partial_market_observation_are_immutable() {
        let mut account = account();
        let before = account.fingerprint();
        let zero_fill = CandidateFillV1 {
            event_id: 91,
            symbol: SymbolId(0),
            signed_qty: 0.0,
            price: 100.0,
            fee: 0.0,
            mark_price: 100.0,
        };
        assert_eq!(
            account.preview_fill(&zero_fill),
            Err(AccountingRejectCodeV1::InvalidQuantity)
        );
        assert_eq!(account.fingerprint(), before);

        assert_eq!(
            account.observe_marks(&[101.0, 0.0]),
            Err(AccountingRejectCodeV1::InvalidMark)
        );
        assert_eq!(account.fingerprint(), before);
    }

    #[test]
    fn scale_reduce_reverse_funding_and_apply_once_are_linear() {
        let mut account = account();
        let open = CandidateFillV1 {
            event_id: 1,
            symbol: SymbolId(0),
            signed_qty: 2.0,
            price: 100.0,
            fee: 0.2,
            mark_price: 100.0,
        };
        account.commit_fill(None, &open).unwrap();
        account.observe_marks(&[110.0, 50.0]).unwrap();
        let funding = ScheduledFundingEventV1 {
            event_id: 7,
            symbol: SymbolId(0),
            rate: 0.001,
        };
        assert!((account.apply_funding_once(funding).unwrap().charge - 0.22).abs() <= 1e-12);
        assert_eq!(
            account.apply_funding_once(funding),
            Err(AccountingRejectCodeV1::DuplicateFundingEvent)
        );
        let reverse = CandidateFillV1 {
            signed_qty: -3.0,
            event_id: 2,
            price: 90.0,
            mark_price: 90.0,
            fee: 0.27,
            ..open
        };
        account.commit_fill(None, &reverse).unwrap();
        assert_eq!(account.positions.qty[0], -1.0);
        assert_eq!(account.positions.avg_entry[0], 90.0);
        account.assert_invariants().unwrap();
    }

    #[test]
    fn liquidation_closes_every_symbol_with_explicit_fills() {
        let mut account = account();
        for (event_id, symbol, quantity, price) in [(1, 0, 5.0, 100.0), (2, 1, -5.0, 50.0)] {
            account
                .commit_fill(
                    None,
                    &CandidateFillV1 {
                        event_id,
                        symbol: SymbolId(symbol),
                        signed_qty: quantity,
                        price,
                        fee: 0.0,
                        mark_price: price,
                    },
                )
                .unwrap();
        }
        account.observe_marks(&[1.0, 500.0]).unwrap();
        let transition = account.liquidate_if_breached(0.001).unwrap().unwrap();
        assert_eq!(transition.fills.len(), 2);
        assert!(matches!(
            account.liquidation_state,
            LiquidationStateV1::Liquidated | LiquidationStateV1::Bankrupt
        ));
        assert!(account.positions.active_symbols().is_empty());
        account.assert_invariants().unwrap();
    }

    #[test]
    fn reservation_candidate_mismatch_cannot_consume_or_mutate_the_account() {
        let mut account = account();
        let fill = CandidateFillV1 {
            event_id: 31,
            symbol: SymbolId(0),
            signed_qty: 1.0,
            price: 100.0,
            fee: 0.1,
            mark_price: 100.0,
        };
        let preview = account.preview_fill(&fill).unwrap();
        let token = account.reserve(&preview).unwrap();
        let before = account.fingerprint();
        let mismatched = CandidateFillV1 { fee: 0.2, ..fill };
        assert_eq!(
            account.commit_fill(Some(&token), &mismatched),
            Err(AccountingRejectCodeV1::ReservationMismatch)
        );
        assert_eq!(account.fingerprint(), before);
        account.release(token).unwrap();
        assert!(account.reservation_balance().abs() <= 1e-12);
        account.assert_invariants().unwrap();
    }

    #[test]
    fn randomized_valid_and_invalid_transitions_preserve_invariants() {
        let config =
            LinearAccountConfigV1::new(10_000.0, 0.005, vec![1.0, 2.0, 0.5], vec![5.0, 4.0, 3.0])
                .unwrap()
                .with_invariant_checks(true);
        let mut account = LinearGrossCrossAccountV1::new(config);
        let mut seed = 0x5eed_59a5_d00d_f00d_u64;
        for step in 0_u64..2_048 {
            let marks = [
                50.0 + (next_random(&mut seed) % 1_000) as f64 / 10.0,
                25.0 + (next_random(&mut seed) % 800) as f64 / 10.0,
                10.0 + (next_random(&mut seed) % 600) as f64 / 10.0,
            ];
            account.observe_marks(&marks).unwrap();
            let symbol = SymbolId((next_random(&mut seed) % 3) as u32);
            let raw_qty = 0.25 + (next_random(&mut seed) % 4) as f64 * 0.25;
            let signed_qty = if step % 29 == 0 {
                0.0
            } else if next_random(&mut seed) & 1 == 0 {
                raw_qty
            } else {
                -raw_qty
            };
            let mark = marks[symbol.0 as usize];
            let price = if step % 31 == 0 { 0.0 } else { mark };
            let fill = CandidateFillV1 {
                event_id: step + 1,
                symbol,
                signed_qty,
                price,
                fee: signed_qty.abs() * mark * 0.0005,
                mark_price: mark,
            };
            let before = account.fingerprint();
            match account.preview_fill(&fill) {
                Ok(_) => {
                    account.commit_fill(None, &fill).unwrap();
                    account.assert_invariants().unwrap();
                }
                Err(_) => assert_eq!(account.fingerprint(), before),
            }
            if step % 17 == 0 {
                let event = ScheduledFundingEventV1 {
                    event_id: 100_000 + step,
                    symbol,
                    rate: 0.0001,
                };
                account.apply_funding_once(event).unwrap();
                let after = account.fingerprint();
                assert_eq!(
                    account.apply_funding_once(event),
                    Err(AccountingRejectCodeV1::DuplicateFundingEvent)
                );
                assert_eq!(account.fingerprint(), after);
                account.assert_invariants().unwrap();
            }
        }
    }

    fn next_random(seed: &mut u64) -> u64 {
        *seed = seed
            .wrapping_mul(6_364_136_223_846_793_005)
            .wrapping_add(1_442_695_040_888_963_407);
        *seed
    }
}
