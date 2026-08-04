use crate::types::{
    ActiveOrder, ORDER_LIMIT, ORDER_MARKET, ORDER_STOP_LIMIT, ORDER_STOP_MARKET, SIDE_BUY,
};

pub fn execution_price(
    order: &ActiveOrder,
    high: f64,
    low: f64,
    close: f64,
    slippage: f64,
) -> Option<f64> {
    match order.order_type {
        ORDER_MARKET => {
            let multiplier = if order.side == SIDE_BUY {
                1.0 + slippage
            } else {
                1.0 - slippage
            };
            Some(close * multiplier)
        }
        ORDER_LIMIT if order.side == SIDE_BUY && low <= order.price => Some(order.price),
        ORDER_LIMIT if order.side != SIDE_BUY && high >= order.price => Some(order.price),
        ORDER_STOP_MARKET if order.side == SIDE_BUY && high >= order.trigger => {
            Some(order.trigger * (1.0 + slippage))
        }
        ORDER_STOP_MARKET if order.side != SIDE_BUY && low <= order.trigger => {
            Some(order.trigger * (1.0 - slippage))
        }
        ORDER_STOP_LIMIT
            if order.side == SIDE_BUY && high >= order.trigger && low <= order.price =>
        {
            Some(order.price)
        }
        ORDER_STOP_LIMIT
            if order.side != SIDE_BUY && low <= order.trigger && high >= order.price =>
        {
            Some(order.price)
        }
        _ => None,
    }
}
