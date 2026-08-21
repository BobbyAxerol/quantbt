use crate::errors::DomainError;

#[must_use]
pub fn quantize_to_ticks(price: f64, tick_size: f64) -> Option<i64> {
    if !price.is_finite() || !tick_size.is_finite() || price <= 0.0 || tick_size < 0.0 {
        return None;
    }
    if tick_size == 0.0 {
        return Some(0);
    }
    Some((price / tick_size).round() as i64)
}

pub fn validate_finite_positive(value: f64, name: &'static str) -> Result<(), DomainError> {
    if value.is_finite() && value > 0.0 {
        Ok(())
    } else {
        Err(DomainError::InvalidShape(name))
    }
}
