pub const COMMAND_CODE_WIDTH: usize = 8;
pub const COMMAND_VALUE_WIDTH: usize = 3;

pub const ACTION_PLACE: i64 = 0;
pub const ACTION_CANCEL: i64 = 1;
// Reactive R2 ABI codes are kept stable for the installed wheel. The static
// tape adapter translates the canonical Python compiler codes explicitly.
pub const ACTION_AMEND: i64 = 2;
pub const ACTION_REPLACE: i64 = 3;
pub const ORDER_MARKET: i64 = 0;
pub const ORDER_LIMIT: i64 = 1;
pub const ORDER_STOP_MARKET: i64 = 2;
pub const ORDER_STOP_LIMIT: i64 = 3;
pub const SIDE_BUY: i64 = 1;
pub const SIDE_SELL: i64 = -1;
pub const FLAG_REDUCE_ONLY: i64 = 1;
pub const MUTATE_QTY: i64 = 1;
pub const MUTATE_PRICE: i64 = 2;
pub const MUTATE_TRIGGER: i64 = 4;

pub const EVENT_PLACE: i64 = 0;
pub const EVENT_CANCEL: i64 = 1;
pub const EVENT_FILL: i64 = 2;
pub const EVENT_REJECT: i64 = 3;
pub const EVENT_AMEND: i64 = 4;
pub const EVENT_REPLACE: i64 = 5;

pub const STATUS_PENDING: i64 = 0;
pub const STATUS_FILLED: i64 = 1;
pub const STATUS_CANCELED: i64 = 2;
pub const STATUS_REJECTED: i64 = 3;

#[derive(Clone, Copy)]
pub struct ActiveOrder {
    pub order_id: i64,
    pub side: i64,
    pub order_type: i64,
    pub qty: f64,
    pub price: f64,
    pub trigger: f64,
    pub reduce_only: bool,
}

pub struct StepResult {
    pub equity: f64,
    pub position: f64,
    pub fee: f64,
    pub turnover: f64,
    pub initial_margin: f64,
    pub maintenance_margin: f64,
    pub fills: Vec<Vec<f64>>,
    pub events: Vec<Vec<i64>>,
    pub active_orders: Vec<Vec<f64>>,
    pub fill_count: i64,
    pub event_count: i64,
    pub rejected_count: i64,
    pub canceled_count: i64,
}
