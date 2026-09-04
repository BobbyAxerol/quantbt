//! Canonical multi-symbol market calendar vocabulary for V1.1.
//!
//! This crate owns only typed, PyO3-free validation/layout.  Pandas parsing and
//! missing-observation policy projection remain at the Python preparation
//! boundary; an execution workload may only lower an all-observed plan until
//! its ABI models missing bars explicitly.

use crate::errors::DomainError;
use crate::ids::SymbolId;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CalendarPolicyV2 {
    Exact,
    Intersection,
    Union,
    PrimaryClock { primary_symbol: SymbolId },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MissingObservationPolicyV1 {
    NoObservation,
    MarkToLastNoExecution,
    ForwardFillQuoteNoVolume,
    RejectIntent,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SymbolCalendarMapV2 {
    pub canonical_to_local: Box<[Option<u32>]>,
    pub local_to_canonical: Box<[Option<u32>]>,
    pub observed: Box<[bool]>,
    pub stale: Box<[bool]>,
    pub tradable: Box<[bool]>,
}

impl SymbolCalendarMapV2 {
    pub fn new(
        canonical_to_local: Vec<Option<u32>>,
        local_to_canonical: Vec<Option<u32>>,
        observed: Vec<bool>,
        stale: Vec<bool>,
        tradable: Vec<bool>,
    ) -> Result<Self, DomainError> {
        let width = canonical_to_local.len();
        if width == 0
            || observed.len() != width
            || stale.len() != width
            || tradable.len() != width
            || canonical_to_local
                .iter()
                .zip(&observed)
                .any(|(mapping, observed)| mapping.is_some() != *observed)
            || tradable
                .iter()
                .zip(&observed)
                .any(|(tradable, observed)| *tradable && !*observed)
        {
            return Err(DomainError::InvalidShape("invalid V2 symbol calendar map"));
        }
        Ok(Self {
            canonical_to_local: canonical_to_local.into_boxed_slice(),
            local_to_canonical: local_to_canonical.into_boxed_slice(),
            observed: observed.into_boxed_slice(),
            stale: stale.into_boxed_slice(),
            tradable: tradable.into_boxed_slice(),
        })
    }

    #[must_use]
    pub fn is_all_observed(&self) -> bool {
        self.observed.iter().all(|value| *value)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CalendarPlanV2 {
    pub canonical_timestamps_ns: Box<[i64]>,
    pub policy: CalendarPolicyV2,
    pub missing_policy: MissingObservationPolicyV1,
    pub symbol_maps: Box<[SymbolCalendarMapV2]>,
}

impl CalendarPlanV2 {
    pub fn new(
        canonical_timestamps_ns: Vec<i64>,
        policy: CalendarPolicyV2,
        missing_policy: MissingObservationPolicyV1,
        symbol_maps: Vec<SymbolCalendarMapV2>,
    ) -> Result<Self, DomainError> {
        if canonical_timestamps_ns.is_empty()
            || symbol_maps.is_empty()
            || canonical_timestamps_ns
                .windows(2)
                .any(|pair| pair[0] >= pair[1])
            || symbol_maps
                .iter()
                .any(|mapping| mapping.canonical_to_local.len() != canonical_timestamps_ns.len())
        {
            return Err(DomainError::InvalidShape(
                "invalid V2 canonical calendar plan",
            ));
        }
        if let CalendarPolicyV2::PrimaryClock { primary_symbol } = policy
            && primary_symbol.0 as usize >= symbol_maps.len()
        {
            return Err(DomainError::InvalidShape(
                "primary symbol is outside V2 calendar map",
            ));
        }
        Ok(Self {
            canonical_timestamps_ns: canonical_timestamps_ns.into_boxed_slice(),
            policy,
            missing_policy,
            symbol_maps: symbol_maps.into_boxed_slice(),
        })
    }

    #[must_use]
    pub fn bars(&self) -> usize {
        self.canonical_timestamps_ns.len()
    }

    #[must_use]
    pub fn symbols(&self) -> usize {
        self.symbol_maps.len()
    }

    #[must_use]
    pub fn is_all_observed(&self) -> bool {
        self.symbol_maps
            .iter()
            .all(SymbolCalendarMapV2::is_all_observed)
    }
}

#[cfg(test)]
mod tests {
    use super::{
        CalendarPlanV2, CalendarPolicyV2, MissingObservationPolicyV1, SymbolCalendarMapV2,
    };
    use crate::ids::SymbolId;

    #[test]
    fn primary_clock_retains_missing_observation_without_claiming_tradability() {
        let primary = SymbolCalendarMapV2::new(
            vec![Some(0), Some(1), Some(2)],
            vec![Some(0), Some(1), Some(2)],
            vec![true, true, true],
            vec![false, false, false],
            vec![true, true, true],
        )
        .unwrap();
        let secondary = SymbolCalendarMapV2::new(
            vec![Some(0), None, Some(1)],
            vec![Some(0), Some(2)],
            vec![true, false, true],
            vec![false, true, false],
            vec![true, false, true],
        )
        .unwrap();
        let plan = CalendarPlanV2::new(
            vec![10, 20, 30],
            CalendarPolicyV2::PrimaryClock {
                primary_symbol: SymbolId(0),
            },
            MissingObservationPolicyV1::MarkToLastNoExecution,
            vec![primary, secondary],
        )
        .unwrap();
        assert_eq!(plan.bars(), 3);
        assert!(!plan.is_all_observed());
        assert!(!plan.symbol_maps[1].tradable[1]);
    }
}
