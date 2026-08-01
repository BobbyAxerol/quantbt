use crate::types::{ActiveOrder, ORDER_LIMIT, ORDER_MARKET, SIDE_BUY};

pub fn execution_price(order: &ActiveOrder, high: f64, low: f64, close: f64, slippage: f64) -> Option<f64> {
    match order.order_type {
        ORDER_MARKET => {
            let multiplier = if order.side == SIDE_BUY { 1.0 + slippage } else { 1.0 - slippage };
            Some(close * multiplier)
        }
        ORDER_LIMIT if order.side == SIDE_BUY && low <= order.price => Some(order.price),
        ORDER_LIMIT if order.side != SIDE_BUY && high >= order.price => Some(order.price),
        _ => None,
    }
}
