pub fn initial_margin(position: f64, close: f64, contract_size: f64, leverage: f64) -> f64 {
    position.abs() * close * contract_size / leverage
}

pub fn maintenance_margin(
    position: f64,
    close: f64,
    contract_size: f64,
    maintenance_ratio: f64,
) -> f64 {
    position.abs() * close * contract_size * maintenance_ratio
}

pub fn required_margin(
    position: f64,
    delta: f64,
    close: f64,
    execution_price: f64,
    contract_size: f64,
    leverage: f64,
    fee: f64,
) -> (f64, f64) {
    let current = initial_margin(position, close, contract_size, leverage);
    let next = initial_margin(position + delta, execution_price, contract_size, leverage);
    let required = fee + (next - current).max(0.0);
    (required, current)
}
