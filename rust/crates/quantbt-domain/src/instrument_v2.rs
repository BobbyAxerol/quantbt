//! Purpose-aware canonical venue rules for the V1.1 market contract.

use crate::enums::Side;
use crate::errors::DomainError;
use crate::ids::{CurrencyId, SymbolId, VenueId};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PricePurposeV2 {
    Limit,
    Stop,
    RiskIncreasing,
    RiskReducing,
    Liquidation,
    Hedge,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum QuantityPurposeV2 {
    RiskIncreasing,
    RiskReducing,
    Liquidation,
    Hedge,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum InstrumentValidationCodeV2 {
    Accepted,
    InvalidValue,
    MinQuantity,
    MaxQuantity,
    MinNotional,
    ReduceOnlyPosition,
}

#[derive(Clone, Debug, PartialEq)]
pub struct InstrumentSpecV2 {
    pub symbol_id: SymbolId,
    pub venue_id: VenueId,
    pub instrument_kind: u8,
    pub price_tick: f64,
    pub quantity_step: f64,
    pub min_quantity: f64,
    pub max_quantity: Option<f64>,
    pub min_notional: f64,
    pub contract_multiplier: f64,
    pub leverage_limit: f64,
    pub settlement_currency: CurrencyId,
    pub fee_schedule_id: u32,
    pub funding_schedule_id: Option<u32>,
    pub one_way_fee_rate: f64,
}

impl InstrumentSpecV2 {
    pub fn validate(&self) -> Result<(), DomainError> {
        let invalid_nonnegative = [
            self.price_tick,
            self.quantity_step,
            self.min_quantity,
            self.min_notional,
            self.one_way_fee_rate,
        ]
        .iter()
        .any(|value| !value.is_finite() || *value < 0.0);
        let invalid_positive = !self.contract_multiplier.is_finite()
            || self.contract_multiplier <= 0.0
            || !self.leverage_limit.is_finite()
            || self.leverage_limit <= 0.0;
        if invalid_nonnegative
            || invalid_positive
            || self.max_quantity.is_some_and(|value| {
                !value.is_finite() || value <= 0.0 || value < self.min_quantity
            })
        {
            return Err(DomainError::InvalidShape("invalid V2 instrument rule"));
        }
        Ok(())
    }

    pub fn quantize_price(
        &self,
        raw: f64,
        side: Side,
        purpose: PricePurposeV2,
    ) -> Result<f64, DomainError> {
        if !raw.is_finite() || raw <= 0.0 {
            return Err(DomainError::InvalidShape(
                "price must be finite and positive",
            ));
        }
        if self.price_tick <= 0.0 {
            return Ok(raw);
        }
        let units = raw / self.price_tick;
        let ticks = match (purpose, side) {
            (PricePurposeV2::Limit, Side::Buy) => (units + 1e-12).floor(),
            (PricePurposeV2::Limit, Side::Sell) => (units - 1e-12).ceil(),
            (_, Side::Buy) => (units - 1e-12).ceil(),
            (_, Side::Sell) => (units + 1e-12).floor(),
        };
        let value = ticks * self.price_tick;
        if value <= 0.0 {
            return Err(DomainError::InvalidShape(
                "price quantization is non-positive",
            ));
        }
        Ok(value)
    }

    pub fn quantize_quantity(
        &self,
        raw: f64,
        purpose: QuantityPurposeV2,
        current_position: Option<f64>,
        allow_close_remainder: bool,
    ) -> Result<f64, DomainError> {
        if !raw.is_finite() {
            return Err(DomainError::InvalidShape("quantity must be finite"));
        }
        let mut value = raw.abs();
        if value == 0.0 {
            return Ok(0.0);
        }
        if purpose == QuantityPurposeV2::RiskReducing {
            let available = current_position
                .ok_or(DomainError::InvalidShape(
                    "reduce-only quantity needs current position",
                ))?
                .abs();
            if !available.is_finite() || available == 0.0 {
                return Ok(0.0);
            }
            value = value.min(available);
            if allow_close_remainder && (value - available).abs() <= 1e-12 {
                return Ok(available);
            }
        }
        if self.quantity_step <= 0.0 {
            return Ok(value);
        }
        Ok((value / self.quantity_step + 1e-12).floor() * self.quantity_step)
    }

    #[must_use]
    pub fn cash_notional(&self, price: f64, quantity: f64) -> f64 {
        (price * quantity * self.contract_multiplier).abs()
    }

    #[must_use]
    pub fn pnl(&self, entry: f64, exit: f64, quantity: f64, side: Side) -> f64 {
        let direction = match side {
            Side::Buy => 1.0,
            Side::Sell => -1.0,
        };
        direction * (exit - entry) * quantity.abs() * self.contract_multiplier
    }

    #[must_use]
    pub fn validate_order(&self, price: f64, quantity: f64) -> InstrumentValidationCodeV2 {
        if !price.is_finite() || !quantity.is_finite() || price <= 0.0 || quantity <= 0.0 {
            return InstrumentValidationCodeV2::InvalidValue;
        }
        if quantity + 1e-12 < self.min_quantity {
            return InstrumentValidationCodeV2::MinQuantity;
        }
        if self
            .max_quantity
            .is_some_and(|limit| quantity - 1e-12 > limit)
        {
            return InstrumentValidationCodeV2::MaxQuantity;
        }
        if self.min_notional > 0.0
            && self.cash_notional(price, quantity) + 1e-12 < self.min_notional
        {
            return InstrumentValidationCodeV2::MinNotional;
        }
        InstrumentValidationCodeV2::Accepted
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct InstrumentRegistryV2 {
    pub rules: Box<[InstrumentSpecV2]>,
}

impl InstrumentRegistryV2 {
    pub fn new(rules: Vec<InstrumentSpecV2>) -> Result<Self, DomainError> {
        if rules.is_empty()
            || rules
                .iter()
                .enumerate()
                .any(|(index, rule)| rule.symbol_id.0 as usize != index || rule.validate().is_err())
        {
            return Err(DomainError::InvalidShape("invalid V2 instrument registry"));
        }
        Ok(Self {
            rules: rules.into_boxed_slice(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::{
        InstrumentRegistryV2, InstrumentSpecV2, InstrumentValidationCodeV2, PricePurposeV2,
        QuantityPurposeV2,
    };
    use crate::enums::Side;
    use crate::ids::{CurrencyId, SymbolId, VenueId};

    fn rule() -> InstrumentSpecV2 {
        InstrumentSpecV2 {
            symbol_id: SymbolId(0),
            venue_id: VenueId(1),
            instrument_kind: 1,
            price_tick: 0.1,
            quantity_step: 0.25,
            min_quantity: 0.25,
            max_quantity: Some(10.0),
            min_notional: 5.0,
            contract_multiplier: 1.0,
            leverage_limit: 5.0,
            settlement_currency: CurrencyId(1),
            fee_schedule_id: 1,
            funding_schedule_id: Some(1),
            one_way_fee_rate: 0.0005,
        }
    }

    #[test]
    fn purpose_rounding_and_reduce_close_match_contract() {
        let item = rule();
        assert_eq!(
            item.quantize_price(10.04, Side::Buy, PricePurposeV2::Limit)
                .unwrap(),
            10.0
        );
        assert_eq!(
            item.quantize_price(10.04, Side::Sell, PricePurposeV2::Stop)
                .unwrap(),
            10.0
        );
        assert_eq!(
            item.quantize_quantity(0.41, QuantityPurposeV2::RiskIncreasing, None, false)
                .unwrap(),
            0.25
        );
        assert_eq!(
            item.quantize_quantity(3.0, QuantityPurposeV2::RiskReducing, Some(-0.31), true)
                .unwrap(),
            0.31
        );
        assert_eq!(
            item.validate_order(10.0, 0.25),
            InstrumentValidationCodeV2::MinNotional
        );
        assert!(InstrumentRegistryV2::new(vec![item]).is_ok());
    }
}
