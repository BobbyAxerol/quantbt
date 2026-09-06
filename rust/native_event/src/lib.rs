use numpy::{
    PyArray1, PyReadonlyArray1, PyReadonlyArray2, PyReadonlyArray3, PyReadonlyArray4,
    PyUntypedArrayMethods,
};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyType};
use std::sync::Arc;

mod prepared_evaluation;
mod reactive_hot_loop;
mod reactive_numeric;
mod reactive_score;
use reactive_numeric::{
    ReactiveCancellationTokenCore, ReactiveCandidateBatchContextV1,
    ReactiveCandidateBatchRunOutputCore, ReactiveCandidateBatchRunnerCore,
    ReactiveCandidateCommandBatchV1, ReactiveCommandBufferV2, ReactiveContextBufferV1,
    ReactiveNumericRunOutputCore, ReactiveNumericRunnerCore,
};

use quantbt_batch as batch;
use quantbt_domain::{generated_contracts, generated_product_contracts};
use quantbt_engine as full;
use quantbt_engine::legacy::types;
use quantbt_engine::{FullMarketData, FullSession};
use quantbt_execution as execution;
use quantbt_package as package;
use quantbt_portfolio as portfolio;
use quantbt_strategy_ir as strategy_ir;

const VERSION: &str = generated_product_contracts::NATIVE_PACKAGE_VERSION;
const API_VERSION: &str = generated_product_contracts::NATIVE_API_VERSION;
const INTERNAL_ABI_VERSION: &str = "0.5";

#[pyfunction]
fn version() -> &'static str {
    VERSION
}

#[pyfunction]
fn api_version() -> &'static str {
    API_VERSION
}

/// Internal Rust contract version. Public PyO3 input remains API 0.4 until a
/// separately versioned Python surface opts into the typed ABI directly.
#[pyfunction]
fn core_abi_version() -> &'static str {
    INTERNAL_ABI_VERSION
}

#[pyfunction]
fn contract_registry_fingerprint() -> &'static str {
    generated_contracts::CONTRACT_REGISTRY_FINGERPRINT
}

#[pyfunction]
fn event_contract_ids() -> Vec<&'static str> {
    generated_product_contracts::RUNTIME_CONTRACT_IDS.to_vec()
}

#[pyfunction]
fn capabilities(py: Python<'_>) -> PyResult<Bound<'_, PyDict>> {
    let values = PyDict::new(py);
    for capability in generated_product_contracts::NATIVE_EXTENSION_CAPABILITIES {
        values.set_item(*capability, true)?;
    }
    Ok(values)
}

#[pyfunction]
fn semantic_descriptor(py: Python<'_>) -> PyResult<Bound<'_, PyDict>> {
    let descriptor = PyDict::new(py);
    descriptor.set_item(
        "descriptor_version",
        generated_product_contracts::SEMANTIC_DESCRIPTOR_VERSION,
    )?;
    descriptor.set_item("native_api", API_VERSION)?;
    descriptor.set_item(
        "core_protocol_min",
        generated_product_contracts::CORE_PROTOCOL_MIN,
    )?;
    descriptor.set_item(
        "core_protocol_max",
        generated_product_contracts::CORE_PROTOCOL_MAX,
    )?;
    descriptor.set_item(
        "contract_registry_fingerprint",
        generated_contracts::CONTRACT_REGISTRY_FINGERPRINT,
    )?;
    descriptor.set_item(
        "trace_schema",
        generated_product_contracts::TRACE_SCHEMA_VERSION,
    )?;
    descriptor.set_item(
        "command_abi",
        generated_product_contracts::COMMAND_ABI_VERSION,
    )?;
    descriptor.set_item(
        "contracts",
        generated_product_contracts::RUNTIME_CONTRACT_IDS.to_vec(),
    )?;

    let orders = PyDict::new(py);
    orders.set_item(
        "types",
        generated_product_contracts::RUNTIME_ORDER_TYPES.to_vec(),
    )?;
    orders.set_item(
        "partial_fill",
        generated_product_contracts::RUNTIME_PARTIAL_FILL,
    )?;
    orders.set_item(
        "volume_model",
        generated_product_contracts::RUNTIME_VOLUME_MODEL,
    )?;
    orders.set_item(
        "gap_policy",
        generated_product_contracts::RUNTIME_GAP_POLICIES.to_vec(),
    )?;
    descriptor.set_item("orders", orders)?;

    let account = PyDict::new(py);
    account.set_item(
        "pnl_models",
        generated_product_contracts::RUNTIME_PNL_MODELS.to_vec(),
    )?;
    account.set_item(
        "margin_models",
        generated_product_contracts::RUNTIME_MARGIN_MODELS.to_vec(),
    )?;
    account.set_item(
        "liquidation_models",
        generated_product_contracts::RUNTIME_LIQUIDATION_MODELS.to_vec(),
    )?;
    descriptor.set_item("account", account)?;

    let portfolio = PyDict::new(py);
    // The semantic descriptor is generated from the versioned product
    // registry. It must preserve scalar types exactly so Python and Rust
    // reject a mismatched core/native pair before any execution state exists.
    for (key, value) in generated_product_contracts::RUNTIME_PORTFOLIO_FIELDS {
        match value {
            generated_product_contracts::RuntimePortfolioScalar::Bool(value) => {
                portfolio.set_item(*key, *value)?;
            }
            generated_product_contracts::RuntimePortfolioScalar::Integer(value) => {
                portfolio.set_item(*key, *value)?;
            }
            generated_product_contracts::RuntimePortfolioScalar::Float(value) => {
                portfolio.set_item(*key, *value)?;
            }
            generated_product_contracts::RuntimePortfolioScalar::Str(value) => {
                portfolio.set_item(*key, *value)?;
            }
            generated_product_contracts::RuntimePortfolioScalar::Null => {
                portfolio.set_item(*key, py.None())?;
            }
        }
    }
    descriptor.set_item("portfolio", portfolio)?;
    Ok(descriptor)
}

/// Product ABI metadata, separate from the frozen API 0.4 semantics.
#[pyfunction]
fn product_descriptor(py: Python<'_>) -> PyResult<Bound<'_, PyDict>> {
    let descriptor = PyDict::new(py);
    descriptor.set_item("descriptor_version", "native-event-product-v1")?;
    descriptor.set_item(
        "product_registry_fingerprint",
        generated_product_contracts::PRODUCT_CONTRACT_REGISTRY_FINGERPRINT,
    )?;
    descriptor.set_item(
        "lifecycle_registry_fingerprint",
        generated_product_contracts::LIFECYCLE_REGISTRY_FINGERPRINT,
    )?;
    descriptor.set_item(
        "core_package_version",
        generated_product_contracts::CORE_PACKAGE_VERSION,
    )?;
    descriptor.set_item("native_package_version", VERSION)?;
    descriptor.set_item(
        "native_protocol_min",
        generated_product_contracts::CORE_PROTOCOL_MIN,
    )?;
    descriptor.set_item(
        "native_protocol_max",
        generated_product_contracts::CORE_PROTOCOL_MAX,
    )?;
    descriptor.set_item(
        "command_abi",
        generated_product_contracts::COMMAND_ABI_VERSION,
    )?;
    descriptor.set_item(
        "result_abi",
        generated_product_contracts::RESULT_ABI_VERSION,
    )?;
    descriptor.set_item(
        "trace_schema",
        generated_product_contracts::TRACE_SCHEMA_VERSION,
    )?;
    descriptor.set_item(
        "strategy_ir",
        generated_product_contracts::STRATEGY_IR_VERSION,
    )?;
    Ok(descriptor)
}

/// Execute a whole explicit-fill tape through the V1.1 linear accounting
/// authority. This route has no matching logic: supplied fills, marks, and
/// scheduled funding events are the complete typed input contract.
#[pyfunction]
#[pyo3(signature = (
    timestamps_ns,
    marks,
    contract_sizes,
    leverages,
    initial_capital,
    maintenance_ratio,
    fill_bar,
    fill_sequence,
    fill_event_id,
    fill_symbol,
    fill_signed_qty,
    fill_price,
    fill_fee,
    funding_bar,
    funding_sequence,
    funding_event_id,
    funding_symbol,
    funding_rate,
    funding_phase=1,
    liquidation_fee_rate=0.0,
    output_profile=2,
    invariant_checks=true
))]
#[allow(clippy::too_many_arguments)]
fn run_fill_replay_v2_native(
    py: Python<'_>,
    timestamps_ns: PyReadonlyArray1<'_, i64>,
    marks: PyReadonlyArray2<'_, f64>,
    contract_sizes: PyReadonlyArray1<'_, f64>,
    leverages: PyReadonlyArray1<'_, f64>,
    initial_capital: f64,
    maintenance_ratio: f64,
    fill_bar: PyReadonlyArray1<'_, i64>,
    fill_sequence: PyReadonlyArray1<'_, i64>,
    fill_event_id: PyReadonlyArray1<'_, u64>,
    fill_symbol: PyReadonlyArray1<'_, i64>,
    fill_signed_qty: PyReadonlyArray1<'_, f64>,
    fill_price: PyReadonlyArray1<'_, f64>,
    fill_fee: PyReadonlyArray1<'_, f64>,
    funding_bar: PyReadonlyArray1<'_, i64>,
    funding_sequence: PyReadonlyArray1<'_, i64>,
    funding_event_id: PyReadonlyArray1<'_, u64>,
    funding_symbol: PyReadonlyArray1<'_, i64>,
    funding_rate: PyReadonlyArray1<'_, f64>,
    funding_phase: u8,
    liquidation_fee_rate: f64,
    output_profile: u8,
    invariant_checks: bool,
) -> PyResult<Py<PyDict>> {
    let marks_shape = marks.shape().to_vec();
    let timestamps = timestamps_ns.as_slice()?.to_vec();
    if marks_shape.len() != 2
        || marks_shape[0] != timestamps.len()
        || marks_shape[1] == 0
        || contract_sizes.len() != marks_shape[1]
        || leverages.len() != marks_shape[1]
    {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "FillReplay V2 requires marks shaped (n_bars, n_symbols) and one contract/leverage per symbol",
        ));
    }
    let marks = marks.as_slice()?.to_vec();
    let contract_sizes = contract_sizes.as_slice()?.to_vec();
    let leverages = leverages.as_slice()?.to_vec();
    let fill_bar = fill_bar.as_slice()?;
    let fill_sequence = fill_sequence.as_slice()?;
    let fill_event_id = fill_event_id.as_slice()?;
    let fill_symbol = fill_symbol.as_slice()?;
    let fill_signed_qty = fill_signed_qty.as_slice()?;
    let fill_price = fill_price.as_slice()?;
    let fill_fee = fill_fee.as_slice()?;
    let fill_count = fill_bar.len();
    if [
        fill_sequence.len(),
        fill_event_id.len(),
        fill_symbol.len(),
        fill_signed_qty.len(),
        fill_price.len(),
        fill_fee.len(),
    ]
    .iter()
    .any(|length| *length != fill_count)
    {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "FillReplay V2 fill arrays must have equal length",
        ));
    }
    let mut fills = Vec::with_capacity(fill_count);
    for index in 0..fill_count {
        let bar_index = usize::try_from(fill_bar[index]).map_err(|_| {
            pyo3::exceptions::PyValueError::new_err("FillReplay V2 fill bar_index must be >= 0")
        })?;
        let sequence = u64::try_from(fill_sequence[index]).map_err(|_| {
            pyo3::exceptions::PyValueError::new_err("FillReplay V2 fill sequence must be >= 0")
        })?;
        let symbol = u32::try_from(fill_symbol[index]).map_err(|_| {
            pyo3::exceptions::PyValueError::new_err("FillReplay V2 fill symbol must be >= 0")
        })?;
        fills.push(full::FillReplayFillV2 {
            bar_index,
            sequence,
            event_id: fill_event_id[index],
            symbol: quantbt_domain::ids::SymbolId(symbol),
            signed_qty: fill_signed_qty[index],
            price: fill_price[index],
            fee: fill_fee[index],
        });
    }
    let funding_bar = funding_bar.as_slice()?;
    let funding_sequence = funding_sequence.as_slice()?;
    let funding_event_id = funding_event_id.as_slice()?;
    let funding_symbol = funding_symbol.as_slice()?;
    let funding_rate = funding_rate.as_slice()?;
    let funding_count = funding_bar.len();
    if [
        funding_sequence.len(),
        funding_event_id.len(),
        funding_symbol.len(),
        funding_rate.len(),
    ]
    .iter()
    .any(|length| *length != funding_count)
    {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "FillReplay V2 funding arrays must have equal length",
        ));
    }
    let mut funding = Vec::with_capacity(funding_count);
    for index in 0..funding_count {
        let bar_index = usize::try_from(funding_bar[index]).map_err(|_| {
            pyo3::exceptions::PyValueError::new_err("FillReplay V2 funding bar_index must be >= 0")
        })?;
        let sequence = u64::try_from(funding_sequence[index]).map_err(|_| {
            pyo3::exceptions::PyValueError::new_err("FillReplay V2 funding sequence must be >= 0")
        })?;
        let symbol = u32::try_from(funding_symbol[index]).map_err(|_| {
            pyo3::exceptions::PyValueError::new_err("FillReplay V2 funding symbol must be >= 0")
        })?;
        funding.push(full::FillReplayFundingV2 {
            bar_index,
            sequence,
            event_id: funding_event_id[index],
            symbol: quantbt_domain::ids::SymbolId(symbol),
            rate: funding_rate[index],
        });
    }
    let funding_phase = full::FundingPhaseV1::try_from(funding_phase)
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
    let output_profile = full::FillReplayOutputProfileV2::try_from(output_profile)
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
    let config = full::FillReplayConfigV2::new(
        initial_capital,
        maintenance_ratio,
        contract_sizes,
        leverages,
        liquidation_fee_rate,
        funding_phase,
    )
    .map_err(|code| pyo3::exceptions::PyValueError::new_err(code.name()))?
    .with_invariant_checks(invariant_checks);
    let result = py
        .detach(move || {
            full::run_fill_replay_v2(
                &timestamps,
                &marks,
                marks_shape[1],
                &fills,
                &funding,
                config,
                output_profile,
            )
        })
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
    fill_replay_v2_output_payload(py, result)
}

fn add_fill_replay_v2_score(
    payload: &Bound<'_, PyDict>,
    score: &full::FillReplayScoreV2,
) -> PyResult<()> {
    payload.set_item("final_cash", score.final_cash)?;
    payload.set_item("final_equity", score.final_equity)?;
    payload.set_item("total_realized_pnl", score.total_realized_pnl)?;
    payload.set_item("total_fees", score.total_fees)?;
    payload.set_item("total_funding", score.total_funding)?;
    payload.set_item("initial_margin", score.initial_margin)?;
    payload.set_item("maintenance_margin", score.maintenance_margin)?;
    payload.set_item("available_equity", score.available_equity)?;
    payload.set_item("liquidated", score.liquidated)?;
    payload.set_item("liquidation_state", score.liquidation_state)?;
    payload.set_item("accepted_fill_count", score.accepted_fill_count)?;
    payload.set_item("rejected_fill_count", score.rejected_fill_count)?;
    payload.set_item("accepted_funding_count", score.accepted_funding_count)?;
    payload.set_item("rejected_funding_count", score.rejected_funding_count)?;
    payload.set_item("account_fingerprint", score.account_fingerprint.hex())?;
    payload.set_item("trace_fingerprint", score.trace_fingerprint.hex())?;
    Ok(())
}

fn add_fill_replay_v2_compact(
    py: Python<'_>,
    payload: &Bound<'_, PyDict>,
    compact: full::FillReplayCompactV2,
) -> PyResult<()> {
    let full::FillReplayCompactV2 {
        score,
        equity,
        cash,
        fees_paid,
        funding_paid,
        initial_margin,
        maintenance_margin,
        available_equity,
        liquidation_state,
        positions,
        average_entries,
        n_bars,
        n_symbols,
    } = compact;
    add_fill_replay_v2_score(payload, &score)?;
    payload.set_item("n_bars", n_bars)?;
    payload.set_item("n_symbols", n_symbols)?;
    payload.set_item("equity", PyArray1::from_vec(py, equity))?;
    payload.set_item("cash", PyArray1::from_vec(py, cash))?;
    payload.set_item("fees_paid", PyArray1::from_vec(py, fees_paid))?;
    payload.set_item("funding_paid", PyArray1::from_vec(py, funding_paid))?;
    payload.set_item(
        "initial_margin_path",
        PyArray1::from_vec(py, initial_margin),
    )?;
    payload.set_item(
        "maintenance_margin_path",
        PyArray1::from_vec(py, maintenance_margin),
    )?;
    payload.set_item(
        "available_equity_path",
        PyArray1::from_vec(py, available_equity),
    )?;
    payload.set_item(
        "liquidation_state_path",
        PyArray1::from_vec(py, liquidation_state),
    )?;
    payload.set_item("positions", PyArray1::from_vec(py, positions))?;
    payload.set_item("average_entries", PyArray1::from_vec(py, average_entries))?;
    Ok(())
}

fn add_fill_replay_v2_trace(
    py: Python<'_>,
    payload: &Bound<'_, PyDict>,
    rows: Vec<quantbt_domain::trace_v2::CanonicalTraceRowV2>,
) -> PyResult<()> {
    let count = rows.len();
    let mut sequence = Vec::with_capacity(count);
    let mut bar_index = Vec::with_capacity(count);
    let mut event_timestamp_ns = Vec::with_capacity(count);
    let mut effective_timestamp_ns = Vec::with_capacity(count);
    let mut event_kind = Vec::with_capacity(count);
    let mut symbol = Vec::with_capacity(count);
    let mut reason_code = Vec::with_capacity(count);
    let mut order_status_code = Vec::with_capacity(count);
    let mut qty = Vec::with_capacity(count);
    let mut price = Vec::with_capacity(count);
    let mut fee = Vec::with_capacity(count);
    let mut cash_before = Vec::with_capacity(count);
    let mut cash_after = Vec::with_capacity(count);
    let mut position_before = Vec::with_capacity(count);
    let mut position_after = Vec::with_capacity(count);
    let mut realized_pnl_before = Vec::with_capacity(count);
    let mut realized_pnl_after = Vec::with_capacity(count);
    let mut initial_margin_before = Vec::with_capacity(count);
    let mut initial_margin_after = Vec::with_capacity(count);
    let mut maintenance_margin_before = Vec::with_capacity(count);
    let mut maintenance_margin_after = Vec::with_capacity(count);
    let mut state_hash_before = Vec::with_capacity(count);
    let mut state_hash_after = Vec::with_capacity(count);
    let mut state_hash_before_present = Vec::with_capacity(count);
    let mut state_hash_after_present = Vec::with_capacity(count);
    for row in rows {
        sequence.push(row.sequence);
        bar_index.push(i64::from(row.bar_index.0));
        event_timestamp_ns.push(row.event_timestamp_ns.0);
        effective_timestamp_ns.push(row.effective_timestamp_ns.0);
        event_kind.push(row.event_kind as u16);
        symbol.push(row.symbol_id.map_or(-1_i64, |value| i64::from(value.0)));
        reason_code.push(row.reason_code);
        order_status_code.push(row.order_status_code);
        qty.push(row.qty);
        price.push(row.price);
        fee.push(row.fee);
        cash_before.push(row.cash_before);
        cash_after.push(row.cash_after);
        position_before.push(row.position_before);
        position_after.push(row.position_after);
        realized_pnl_before.push(row.realized_pnl_before);
        realized_pnl_after.push(row.realized_pnl_after);
        initial_margin_before.push(row.initial_margin_before);
        initial_margin_after.push(row.initial_margin_after);
        maintenance_margin_before.push(row.maintenance_margin_before);
        maintenance_margin_after.push(row.maintenance_margin_after);
        state_hash_before.push(row.state_hash_before.unwrap_or(0));
        state_hash_after.push(row.state_hash_after.unwrap_or(0));
        state_hash_before_present.push(row.state_hash_before.is_some());
        state_hash_after_present.push(row.state_hash_after.is_some());
    }
    payload.set_item("trace_rows", count)?;
    payload.set_item("trace_sequence", PyArray1::from_vec(py, sequence))?;
    payload.set_item("trace_bar_index", PyArray1::from_vec(py, bar_index))?;
    payload.set_item(
        "trace_event_timestamp_ns",
        PyArray1::from_vec(py, event_timestamp_ns),
    )?;
    payload.set_item(
        "trace_effective_timestamp_ns",
        PyArray1::from_vec(py, effective_timestamp_ns),
    )?;
    payload.set_item("trace_event_kind", PyArray1::from_vec(py, event_kind))?;
    payload.set_item("trace_symbol", PyArray1::from_vec(py, symbol))?;
    payload.set_item("trace_reason_code", PyArray1::from_vec(py, reason_code))?;
    payload.set_item(
        "trace_order_status_code",
        PyArray1::from_vec(py, order_status_code),
    )?;
    payload.set_item("trace_qty", PyArray1::from_vec(py, qty))?;
    payload.set_item("trace_price", PyArray1::from_vec(py, price))?;
    payload.set_item("trace_fee", PyArray1::from_vec(py, fee))?;
    payload.set_item("trace_cash_before", PyArray1::from_vec(py, cash_before))?;
    payload.set_item("trace_cash_after", PyArray1::from_vec(py, cash_after))?;
    payload.set_item(
        "trace_position_before",
        PyArray1::from_vec(py, position_before),
    )?;
    payload.set_item(
        "trace_position_after",
        PyArray1::from_vec(py, position_after),
    )?;
    payload.set_item(
        "trace_realized_pnl_before",
        PyArray1::from_vec(py, realized_pnl_before),
    )?;
    payload.set_item(
        "trace_realized_pnl_after",
        PyArray1::from_vec(py, realized_pnl_after),
    )?;
    payload.set_item(
        "trace_initial_margin_before",
        PyArray1::from_vec(py, initial_margin_before),
    )?;
    payload.set_item(
        "trace_initial_margin_after",
        PyArray1::from_vec(py, initial_margin_after),
    )?;
    payload.set_item(
        "trace_maintenance_margin_before",
        PyArray1::from_vec(py, maintenance_margin_before),
    )?;
    payload.set_item(
        "trace_maintenance_margin_after",
        PyArray1::from_vec(py, maintenance_margin_after),
    )?;
    payload.set_item(
        "trace_state_hash_before",
        PyArray1::from_vec(py, state_hash_before),
    )?;
    payload.set_item(
        "trace_state_hash_after",
        PyArray1::from_vec(py, state_hash_after),
    )?;
    payload.set_item(
        "trace_state_hash_before_present",
        PyArray1::from_vec(py, state_hash_before_present),
    )?;
    payload.set_item(
        "trace_state_hash_after_present",
        PyArray1::from_vec(py, state_hash_after_present),
    )?;
    Ok(())
}

fn fill_replay_v2_output_payload(
    py: Python<'_>,
    result: full::FillReplayResultV2,
) -> PyResult<Py<PyDict>> {
    let payload = PyDict::new(py);
    payload.set_item("engine", "fill_replay_v2_rust")?;
    payload.set_item("canonical_trace_schema", "canonical-trace-v2")?;
    match result {
        full::FillReplayResultV2::Score(score) => {
            payload.set_item("output_profile", "score")?;
            add_fill_replay_v2_score(&payload, &score)?;
        }
        full::FillReplayResultV2::Compact(compact) => {
            payload.set_item("output_profile", "compact")?;
            add_fill_replay_v2_compact(py, &payload, compact)?;
        }
        full::FillReplayResultV2::Audit(audit) => {
            payload.set_item("output_profile", "audit")?;
            add_fill_replay_v2_compact(py, &payload, audit.compact)?;
            add_fill_replay_v2_trace(py, &payload, audit.trace)?;
        }
    }
    Ok(payload.unbind())
}

/// Native implementation of the frozen portfolio target preflight contract.
/// It is intentionally a planning call: accepted deltas must still travel
/// through the canonical event engine to receive fills, fees and lifecycle.
#[pyfunction]
#[pyo3(signature = (previous_units, requested_units, prices, equity, contract_sizes, leverages, fee_rates, slippage_rates, tradable, stale, min_qty, min_notional, reserved_margin=0.0, policy=0))]
#[allow(clippy::too_many_arguments)]
fn native_portfolio_target_preflight(
    py: Python<'_>,
    previous_units: PyReadonlyArray1<'_, f64>,
    requested_units: PyReadonlyArray1<'_, f64>,
    prices: PyReadonlyArray1<'_, f64>,
    equity: f64,
    contract_sizes: PyReadonlyArray1<'_, f64>,
    leverages: PyReadonlyArray1<'_, f64>,
    fee_rates: PyReadonlyArray1<'_, f64>,
    slippage_rates: PyReadonlyArray1<'_, f64>,
    tradable: PyReadonlyArray1<'_, bool>,
    stale: PyReadonlyArray1<'_, bool>,
    min_qty: PyReadonlyArray1<'_, f64>,
    min_notional: PyReadonlyArray1<'_, f64>,
    reserved_margin: f64,
    policy: u8,
) -> PyResult<Py<PyDict>> {
    let policy = portfolio::PortfolioMarginAllocationPolicy::try_from(policy)
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
    let result = portfolio::execute_portfolio_target(portfolio::PortfolioTargetRequest {
        previous_units: previous_units.as_slice()?,
        requested_units: requested_units.as_slice()?,
        prices: prices.as_slice()?,
        equity,
        contract_sizes: contract_sizes.as_slice()?,
        leverages: leverages.as_slice()?,
        fee_rates: fee_rates.as_slice()?,
        slippage_rates: slippage_rates.as_slice()?,
        tradable: tradable.as_slice()?,
        stale: stale.as_slice()?,
        min_qty: min_qty.as_slice()?,
        min_notional: min_notional.as_slice()?,
        reserved_margin,
        policy,
    })
    .map_err(pyo3::exceptions::PyValueError::new_err)?;
    let rejection_codes = result.rejection_codes();
    let rejection_names = result
        .rejection_reasons
        .iter()
        .map(|reason| reason.name())
        .collect::<Vec<_>>();
    let invariants_pass = result.invariant_passes(1e-12);
    let available_equity_after = result.available_equity_after;
    let payload = PyDict::new(py);
    payload.set_item(
        "requested_units",
        PyArray1::from_vec(py, result.requested_units),
    )?;
    payload.set_item(
        "accepted_units",
        PyArray1::from_vec(py, result.accepted_units),
    )?;
    payload.set_item("delta_qty", PyArray1::from_vec(py, result.delta_qty))?;
    payload.set_item(
        "traded_notional",
        PyArray1::from_vec(py, result.traded_notional),
    )?;
    payload.set_item("fees", PyArray1::from_vec(py, result.fees))?;
    payload.set_item("slippage", PyArray1::from_vec(py, result.slippage))?;
    payload.set_item(
        "initial_margin",
        PyArray1::from_vec(py, result.initial_margin),
    )?;
    payload.set_item("rejection_code", PyArray1::from_vec(py, rejection_codes))?;
    payload.set_item("rejection_reason", rejection_names)?;
    payload.set_item("available_equity_after", available_equity_after)?;
    payload.set_item("policy", policy as u8)?;
    payload.set_item("invariants_pass", invariants_pass)?;
    payload.set_item("native_contract", "portfolio-target-execution-v1")?;
    Ok(payload.unbind())
}

/// Native implementation of the deterministic package preflight/reservation
/// contract. Atomicity is explicitly a bar-transaction simulation model; this
/// function never claims venue-native all-or-none execution.
#[pyfunction]
#[pyo3(signature = (package_id, order_ids, symbol_ids, signed_qty, prices, initial_margin, fee_rates, source_age_ns, venue_codes, venue_sequence, min_qty, min_notional, contract_sizes, available_equity, policy=2, max_staleness_ns=0))]
#[allow(clippy::too_many_arguments)]
fn native_package_transaction_preflight(
    py: Python<'_>,
    package_id: u64,
    order_ids: PyReadonlyArray1<'_, i64>,
    symbol_ids: PyReadonlyArray1<'_, u32>,
    signed_qty: PyReadonlyArray1<'_, f64>,
    prices: PyReadonlyArray1<'_, f64>,
    initial_margin: PyReadonlyArray1<'_, f64>,
    fee_rates: PyReadonlyArray1<'_, f64>,
    source_age_ns: PyReadonlyArray1<'_, i64>,
    venue_codes: PyReadonlyArray1<'_, u16>,
    venue_sequence: PyReadonlyArray1<'_, u32>,
    min_qty: PyReadonlyArray1<'_, f64>,
    min_notional: PyReadonlyArray1<'_, f64>,
    contract_sizes: PyReadonlyArray1<'_, f64>,
    available_equity: f64,
    policy: u8,
    max_staleness_ns: i64,
) -> PyResult<Py<PyDict>> {
    let order_ids = order_ids.as_slice()?;
    let symbol_ids = symbol_ids.as_slice()?;
    let signed_qty = signed_qty.as_slice()?;
    let prices = prices.as_slice()?;
    let initial_margin = initial_margin.as_slice()?;
    let fee_rates = fee_rates.as_slice()?;
    let source_age_ns = source_age_ns.as_slice()?;
    let venue_codes = venue_codes.as_slice()?;
    let venue_sequence = venue_sequence.as_slice()?;
    let min_qty = min_qty.as_slice()?;
    let min_notional = min_notional.as_slice()?;
    let contract_sizes = contract_sizes.as_slice()?;
    let count = order_ids.len();
    if [
        symbol_ids.len(),
        signed_qty.len(),
        prices.len(),
        initial_margin.len(),
        fee_rates.len(),
        source_age_ns.len(),
        venue_codes.len(),
        venue_sequence.len(),
        min_qty.len(),
        min_notional.len(),
        contract_sizes.len(),
    ]
    .iter()
    .any(|length| *length != count)
    {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "native package preflight arrays must have equal one-dimensional length",
        ));
    }
    let legs = (0..count)
        .map(|index| package::PackageLegRequest {
            order_id: quantbt_domain::ids::ExternalOrderId(order_ids[index]),
            symbol: quantbt_domain::ids::SymbolId(symbol_ids[index]),
            signed_qty: signed_qty[index],
            price: prices[index],
            initial_margin: initial_margin[index],
            fee_rate: fee_rates[index],
            source_age_ns: source_age_ns[index],
            venue_code: venue_codes[index],
            venue_sequence: venue_sequence[index],
            min_qty: min_qty[index],
            min_notional: min_notional[index],
            contract_size: contract_sizes[index],
        })
        .collect::<Vec<_>>();
    let policy = package::PackagePolicy::try_from(policy)
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
    let result = package::execute_package_transaction(
        package::PackageId(package_id),
        &legs,
        available_equity,
        policy,
        max_staleness_ns,
    )
    .map_err(pyo3::exceptions::PyValueError::new_err)?;
    let payload = PyDict::new(py);
    payload.set_item("accepted", PyArray1::from_vec(py, result.accepted.clone()))?;
    payload.set_item(
        "rejection_code",
        PyArray1::from_vec(
            py,
            result
                .rejection_reasons
                .iter()
                .map(|reason| *reason as u8)
                .collect::<Vec<_>>(),
        ),
    )?;
    payload.set_item(
        "rejection_reason",
        result
            .rejection_reasons
            .iter()
            .map(|reason| reason.name())
            .collect::<Vec<_>>(),
    )?;
    payload.set_item("final_state", result.final_state as u8)?;
    payload.set_item(
        "transitions",
        PyArray1::from_vec(
            py,
            result
                .transitions
                .iter()
                .map(|event| *event as u8)
                .collect::<Vec<_>>(),
        ),
    )?;
    payload.set_item("reserved_margin", result.reserved_margin)?;
    payload.set_item("released_margin", result.released_margin)?;
    payload.set_item("package_fee", result.package_fee)?;
    payload.set_item("residual_notional", result.residual_notional)?;
    payload.set_item("invariants_pass", result.invariants_pass(1e-12))?;
    payload.set_item("atomicity_model", "bar_transaction")?;
    payload.set_item("native_contract", "package-transaction-v1")?;
    Ok(payload.unbind())
}

fn integer_units(value: f64, increment: f64, ceil_mode: bool) -> i64 {
    if increment <= 0.0 {
        return 0;
    }
    let scaled = value / increment;
    if ceil_mode {
        (scaled - 1e-12).ceil() as i64
    } else {
        (scaled + 1e-12).floor() as i64
    }
}

#[pyfunction]
fn quantize_price_v1(
    price: f64,
    tick_size: f64,
    side: i64,
    order_type: i64,
) -> PyResult<(f64, i64)> {
    if !price.is_finite() || !tick_size.is_finite() || price <= 0.0 || tick_size < 0.0 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "price/tick_size are invalid",
        ));
    }
    if tick_size == 0.0 {
        return Ok((price, 0));
    }
    let is_limit_price = order_type == types::ORDER_LIMIT || order_type == types::ORDER_STOP_LIMIT;
    let ceil_mode = if is_limit_price { side < 0 } else { side > 0 };
    let ticks = integer_units(price, tick_size, ceil_mode);
    Ok((ticks as f64 * tick_size, ticks))
}

#[pyfunction]
#[pyo3(signature = (qty, price, qty_step, min_qty=0.0, max_qty=0.0, min_notional=0.0, contract_size=1.0))]
fn quantize_quantity_v1(
    qty: f64,
    price: f64,
    qty_step: f64,
    min_qty: f64,
    max_qty: f64,
    min_notional: f64,
    contract_size: f64,
) -> PyResult<(f64, i64, i64)> {
    let values = [
        qty,
        price,
        qty_step,
        min_qty,
        max_qty,
        min_notional,
        contract_size,
    ];
    if values.iter().any(|value| !value.is_finite())
        || qty <= 0.0
        || price <= 0.0
        || qty_step < 0.0
        || contract_size <= 0.0
    {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "quantity constraint values are invalid",
        ));
    }
    Ok(quantize_quantity_values(
        qty,
        price,
        qty_step,
        min_qty,
        max_qty,
        min_notional,
        contract_size,
    ))
}

#[pyfunction]
#[pyo3(signature = (price, qty, tick_size, qty_step, side, order_type, min_qty=0.0, max_qty=0.0, min_notional=0.0, contract_size=1.0))]
#[allow(clippy::too_many_arguments)]
fn quantize_order_value_v1(
    price: f64,
    qty: f64,
    tick_size: f64,
    qty_step: f64,
    side: i64,
    order_type: i64,
    min_qty: f64,
    max_qty: f64,
    min_notional: f64,
    contract_size: f64,
) -> (f64, f64, i64, i64, i64) {
    let values = [
        price,
        qty,
        tick_size,
        qty_step,
        min_qty,
        max_qty,
        min_notional,
        contract_size,
    ];
    if values.iter().any(|value| !value.is_finite())
        || price <= 0.0
        || qty <= 0.0
        || tick_size < 0.0
        || qty_step < 0.0
        || contract_size <= 0.0
    {
        return (0.0, 0.0, 0, 0, 1);
    }
    let is_limit_price = order_type == types::ORDER_LIMIT || order_type == types::ORDER_STOP_LIMIT;
    let ceil_mode = if is_limit_price { side < 0 } else { side > 0 };
    let ticks = integer_units(price, tick_size, ceil_mode);
    let quantized_price = if tick_size > 0.0 {
        ticks as f64 * tick_size
    } else {
        price
    };
    let (quantized_qty, lots, mut reject_code) = quantize_quantity_values(
        qty,
        quantized_price.max(f64::MIN_POSITIVE),
        qty_step,
        min_qty,
        max_qty,
        min_notional,
        contract_size,
    );
    if quantized_price <= 0.0 {
        reject_code = 1;
    }
    (quantized_price, quantized_qty, ticks, lots, reject_code)
}

fn quantize_quantity_values(
    qty: f64,
    price: f64,
    qty_step: f64,
    min_qty: f64,
    max_qty: f64,
    min_notional: f64,
    contract_size: f64,
) -> (f64, i64, i64) {
    let lots = integer_units(qty, qty_step, false);
    let quantized = if qty_step > 0.0 {
        lots as f64 * qty_step
    } else {
        qty
    };
    let reject_code = if quantized <= 0.0 || quantized + 1e-12 < min_qty {
        2
    } else if max_qty > 0.0 && quantized - 1e-12 > max_qty {
        3
    } else if min_notional > 0.0 && quantized * price * contract_size + 1e-12 < min_notional {
        4
    } else {
        0
    };
    (quantized, lots, reject_code)
}

#[pyclass]
struct PreparedMarketCore {
    /// API-0.3/legacy compatibility facade over the one native market owner.
    ///
    /// The historical R1/R2 public constructor accepts one-dimensional
    /// arrays.  It is translated to a one-symbol `FullMarketData` at the
    /// boundary, so retaining this class never creates a second Rust market
    /// representation or lifecycle runtime.
    inner: Arc<FullMarketData>,
}

#[pyclass(frozen)]
struct BatchedScoreResultCore {
    #[pyo3(get)]
    final_equity: f64,
    #[pyo3(get)]
    final_position: f64,
    #[pyo3(get)]
    total_fee: f64,
    #[pyo3(get)]
    total_turnover: f64,
    #[pyo3(get)]
    fill_count: i64,
    #[pyo3(get)]
    event_count: i64,
    #[pyo3(get)]
    rejected_count: i64,
    #[pyo3(get)]
    canceled_count: i64,
    #[pyo3(get)]
    max_initial_margin: f64,
    #[pyo3(get)]
    max_maintenance_margin: f64,
    #[pyo3(get)]
    bars: usize,
}

impl PreparedMarketCore {
    #[allow(clippy::too_many_arguments)]
    fn from_arrays(
        timestamps_ns: PyReadonlyArray1<'_, i64>,
        opens: PyReadonlyArray1<'_, f64>,
        highs: PyReadonlyArray1<'_, f64>,
        lows: PyReadonlyArray1<'_, f64>,
        closes: PyReadonlyArray1<'_, f64>,
        volumes: PyReadonlyArray1<'_, f64>,
        funding: PyReadonlyArray1<'_, f64>,
        funding_mask: PyReadonlyArray1<'_, bool>,
    ) -> PyResult<Self> {
        let market = FullMarketData::new(
            timestamps_ns.as_slice()?.to_vec(),
            opens.as_slice()?.to_vec(),
            highs.as_slice()?.to_vec(),
            lows.as_slice()?.to_vec(),
            closes.as_slice()?.to_vec(),
            volumes.as_slice()?.to_vec(),
            funding.as_slice()?.to_vec(),
            funding_mask.as_slice()?.to_vec(),
            1,
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(Self {
            inner: Arc::new(market),
        })
    }
}

#[pymethods]
impl PreparedMarketCore {
    #[new]
    #[allow(clippy::too_many_arguments)]
    fn new(
        timestamps_ns: PyReadonlyArray1<'_, i64>,
        opens: PyReadonlyArray1<'_, f64>,
        highs: PyReadonlyArray1<'_, f64>,
        lows: PyReadonlyArray1<'_, f64>,
        closes: PyReadonlyArray1<'_, f64>,
        volumes: PyReadonlyArray1<'_, f64>,
        funding: PyReadonlyArray1<'_, f64>,
        funding_mask: PyReadonlyArray1<'_, bool>,
    ) -> PyResult<Self> {
        Self::from_arrays(
            timestamps_ns,
            opens,
            highs,
            lows,
            closes,
            volumes,
            funding,
            funding_mask,
        )
    }
}

/// Compatibility-only owner for the API-0.3/R1/R2 primitive command ABI.
///
/// It deliberately contains no account, order, lifecycle, fill, or market
/// state of its own.  The only mutable execution state is `FullSession`.
/// Legacy eight-column rows are translated at ingress and output is projected
/// back to the frozen legacy row schemas at egress.
struct LegacyFullSessionAdapter {
    inner: FullSession,
}

impl LegacyFullSessionAdapter {
    #[allow(clippy::too_many_arguments)]
    fn new(
        market: Arc<FullMarketData>,
        contract_size: f64,
        leverage: f64,
        fee_rate: f64,
        initial_capital: f64,
        maintenance_ratio: f64,
        slippage_rate: f64,
        use_funding: bool,
    ) -> Result<Self, String> {
        // R1/R2 never certified these fields.  Keeping the historical
        // constructor while failing closed is safer than silently changing a
        // legacy run to FullSession funding/liquidation semantics.
        if use_funding {
            return Err("Rust R1 does not support funding".to_owned());
        }
        if maintenance_ratio != 0.0 {
            return Err(
                "Rust R2 does not support liquidation semantics; set maintenance_ratio=0.0 or use FullReactiveSessionCore"
                    .to_owned(),
            );
        }
        let inner = FullSession::new(
            market,
            vec![contract_size],
            vec![leverage],
            vec![fee_rate],
            initial_capital,
            maintenance_ratio,
            slippage_rate,
            false,
        )?;
        Ok(Self { inner })
    }

    #[inline]
    fn market_len(&self) -> usize {
        self.inner.market.n_bars
    }

    #[inline]
    fn next_bar(&self) -> usize {
        self.inner.next_bar()
    }

    fn reset(&mut self) {
        self.inner.reset();
    }

    fn step_with_output(
        &mut self,
        bar: usize,
        legacy_codes: &[i64],
        legacy_values: &[f64],
        legacy_expiry: &[i64],
        command_count: usize,
        materialize: bool,
    ) -> Result<types::StepResult, String> {
        let translated = translate_legacy_command_batch(
            legacy_codes,
            legacy_values,
            legacy_expiry,
            command_count,
        )?;
        let output_mask = if materialize { full::OUTPUT_ALL } else { 0 };
        let result = self.inner.step_with_mask(
            bar,
            &translated.codes,
            &translated.values,
            &translated.expiry,
            command_count,
            output_mask,
        )?;
        Ok(project_legacy_step_result(&self.inner, result, materialize))
    }

    fn step(
        &mut self,
        bar: usize,
        legacy_codes: &[i64],
        legacy_values: &[f64],
        legacy_expiry: &[i64],
        command_count: usize,
    ) -> Result<types::StepResult, String> {
        self.step_with_output(
            bar,
            legacy_codes,
            legacy_values,
            legacy_expiry,
            command_count,
            true,
        )
    }
}

struct LegacyTranslatedBatch {
    codes: Vec<i64>,
    values: Vec<f64>,
    expiry: Vec<i64>,
}

/// Translate the frozen R1/R2 row ABI into the API-0.4 full command ABI.
///
/// The translation is intentionally mechanical: the legacy ABI has no
/// multi-symbol, contingent, or non-GTC fields, so every such full-contract
/// field is set to an explicit inert value.  Unsupported expiry/funding/
/// liquidation combinations fail before a FullSession transition occurs.
fn translate_legacy_command_batch(
    legacy_codes: &[i64],
    legacy_values: &[f64],
    legacy_expiry: &[i64],
    command_count: usize,
) -> Result<LegacyTranslatedBatch, String> {
    if legacy_codes.len() != command_count * types::COMMAND_CODE_WIDTH
        || legacy_values.len() != command_count * types::COMMAND_VALUE_WIDTH
        || legacy_expiry.len() != command_count
    {
        return Err("legacy command batch buffer shape does not match command count".to_owned());
    }
    if legacy_expiry.iter().any(|value| *value != -1) {
        return Err("Rust batched tape does not support expiry".to_owned());
    }

    let mut codes = Vec::with_capacity(command_count * full::CODE_WIDTH);
    let mut values = Vec::with_capacity(command_count * full::VALUE_WIDTH);
    let mut expiry = Vec::with_capacity(command_count);
    for row in 0..command_count {
        let legacy_code =
            &legacy_codes[row * types::COMMAND_CODE_WIDTH..(row + 1) * types::COMMAND_CODE_WIDTH];
        let legacy_value = &legacy_values
            [row * types::COMMAND_VALUE_WIDTH..(row + 1) * types::COMMAND_VALUE_WIDTH];
        let legacy_action = legacy_code[0];
        let full_action = match legacy_action {
            types::ACTION_PLACE => 0,
            types::ACTION_CANCEL => 1,
            types::ACTION_AMEND => 3,
            types::ACTION_REPLACE => 2,
            _ => legacy_action,
        };
        let mut full_code = [-1_i64; full::CODE_WIDTH];
        full_code[0] = full_action;
        // Legacy R1/R2 was exactly one immediate, GTC symbol.  Values which
        // are irrelevant to cancel/amend remain inert and FullSession only
        // reads their explicit action fields.
        full_code[1] = if matches!(legacy_action, types::ACTION_PLACE | types::ACTION_REPLACE) {
            0
        } else {
            -1
        };
        full_code[2] = legacy_code[1];
        full_code[3] = legacy_code[2];
        full_code[4] = 0; // GTC
        full_code[5] = if legacy_code[3] & types::FLAG_REDUCE_ONLY != 0 {
            1
        } else {
            0
        };
        full_code[6] = legacy_code[4];
        full_code[7] = legacy_code[5];
        full_code[8] = -1; // parent
        full_code[9] = -1; // group
        full_code[10] = -1; // OCO
        full_code[11] = 0; // immediate activation
        full_code[12] = legacy_code[7].max(0); // trace-only compiler order

        let mut full_value = [legacy_value[0], legacy_value[1], legacy_value[2]];
        if legacy_action == types::ACTION_AMEND {
            // The legacy mutability mask is not part of the full ABI.  Zero
            // fields are intentionally inert for full-contract AMEND, so
            // clearing unselected values retains exact R2 amend semantics.
            let mask = legacy_code[6];
            if mask & types::MUTATE_QTY == 0 {
                full_value[0] = 0.0;
            }
            if mask & types::MUTATE_PRICE == 0 {
                full_value[1] = 0.0;
            }
            if mask & types::MUTATE_TRIGGER == 0 {
                full_value[2] = 0.0;
            }
        }
        codes.extend_from_slice(&full_code);
        values.extend_from_slice(&full_value);
        expiry.push(-1);
    }
    Ok(LegacyTranslatedBatch {
        codes,
        values,
        expiry,
    })
}

fn legacy_event_kind(full_kind: i64) -> Option<i64> {
    match full_kind {
        full::EVENT_PLACE => Some(types::EVENT_PLACE),
        full::EVENT_CANCEL => Some(types::EVENT_CANCEL),
        full::EVENT_REPLACE => Some(types::EVENT_REPLACE),
        full::EVENT_AMEND => Some(types::EVENT_AMEND),
        full::EVENT_FILL => Some(types::EVENT_FILL),
        full::EVENT_REJECT => Some(types::EVENT_REJECT),
        // R1/R2 rejects expiry/contingent commands at ingress, therefore
        // their generated lifecycle events must never leak through this
        // compatibility surface.
        _ => None,
    }
}

fn project_legacy_step_result(
    session: &FullSession,
    result: full::FullStepResult,
    materialize: bool,
) -> types::StepResult {
    let fills = if materialize {
        result
            .fills
            .into_iter()
            .filter(|row| row.len() >= 6)
            .map(|row| vec![row[0], row[2], row[3], row[4], row[5]])
            .collect()
    } else {
        Vec::new()
    };
    let events = if materialize {
        result
            .events
            .into_iter()
            .flat_map(|row| {
                if row.len() < 4 {
                    return Vec::new();
                }
                if row[0] == full::EVENT_REPLACE {
                    // R1/R2 exposed replacement as a canceled old state
                    // followed by the newly pending replacement. The full
                    // engine has one canonical REPLACE transition, so this
                    // is egress-only compatibility projection, not a second
                    // lifecycle mutation.
                    return vec![
                        vec![types::EVENT_REPLACE, types::STATUS_CANCELED, row[2], row[3]],
                        vec![types::EVENT_REPLACE, row[1], row[2], row[3]],
                    ];
                }
                legacy_event_kind(row[0])
                    .map(|kind| vec![vec![kind, row[1], row[2], row[3]]])
                    .unwrap_or_default()
            })
            .collect()
    } else {
        Vec::new()
    };
    let active_orders = if materialize {
        result
            .active_orders
            .into_iter()
            .filter(|row| row.len() >= 9)
            .map(|row| vec![row[0], row[2], row[3], row[4], row[5], row[6], row[8]])
            .collect()
    } else {
        Vec::new()
    };
    types::StepResult {
        equity: result.equity,
        position: session.positions.first().copied().unwrap_or(0.0),
        fee: result.fee,
        turnover: result.turnover,
        initial_margin: result.initial_margin,
        maintenance_margin: result.maintenance_margin,
        fills,
        events,
        active_orders,
        fill_count: result.fill_count,
        // A successful historical REPLACE projected to two rows above while
        // FullSession intentionally owns one canonical transition.
        event_count: result.event_count + result.replace_count,
        rejected_count: result.rejected_count,
        canceled_count: result.canceled_count,
    }
}

#[pyclass]
struct ReactiveSessionCore {
    /// Historical API-0.3 binding name. The execution owner is always the
    /// API-0.4 `FullSession` behind `LegacyFullSessionAdapter`.
    inner: LegacyFullSessionAdapter,
}

#[pymethods]
impl ReactiveSessionCore {
    #[new]
    #[allow(clippy::too_many_arguments)]
    fn new(
        timestamps_ns: PyReadonlyArray1<'_, i64>,
        opens: PyReadonlyArray1<'_, f64>,
        highs: PyReadonlyArray1<'_, f64>,
        lows: PyReadonlyArray1<'_, f64>,
        closes: PyReadonlyArray1<'_, f64>,
        volumes: PyReadonlyArray1<'_, f64>,
        funding: PyReadonlyArray1<'_, f64>,
        funding_mask: PyReadonlyArray1<'_, bool>,
        contract_size: f64,
        leverage: f64,
        fee_rate: f64,
        initial_capital: f64,
        maintenance_ratio: f64,
        slippage_rate: f64,
        use_funding: bool,
    ) -> PyResult<Self> {
        let prepared = PreparedMarketCore::from_arrays(
            timestamps_ns,
            opens,
            highs,
            lows,
            closes,
            volumes,
            funding,
            funding_mask,
        )?;
        let inner = LegacyFullSessionAdapter::new(
            prepared.inner,
            contract_size,
            leverage,
            fee_rate,
            initial_capital,
            maintenance_ratio,
            slippage_rate,
            use_funding,
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(Self { inner })
    }

    #[classmethod]
    #[allow(clippy::too_many_arguments)]
    fn from_prepared(
        _cls: &Bound<'_, PyType>,
        py: Python<'_>,
        prepared: Py<PreparedMarketCore>,
        contract_size: f64,
        leverage: f64,
        fee_rate: f64,
        initial_capital: f64,
        maintenance_ratio: f64,
        slippage_rate: f64,
        use_funding: bool,
    ) -> PyResult<Self> {
        let market = prepared.borrow(py).inner.clone();
        let inner = LegacyFullSessionAdapter::new(
            market,
            contract_size,
            leverage,
            fee_rate,
            initial_capital,
            maintenance_ratio,
            slippage_rate,
            use_funding,
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(Self { inner })
    }

    fn step(
        &mut self,
        py: Python<'_>,
        bar_index: usize,
        command_codes: PyReadonlyArray2<'_, i64>,
        command_values: PyReadonlyArray2<'_, f64>,
        command_expiry: PyReadonlyArray1<'_, i64>,
    ) -> PyResult<Py<PyDict>> {
        let codes_shape = command_codes.shape();
        let values_shape = command_values.shape();
        if codes_shape.len() != 2 || codes_shape[1] != types::COMMAND_CODE_WIDTH {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "command_codes must have shape (n, 8)",
            ));
        }
        if values_shape.len() != 2
            || values_shape[0] != codes_shape[0]
            || values_shape[1] != types::COMMAND_VALUE_WIDTH
        {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "command_values must have shape (n, 3)",
            ));
        }
        if command_expiry.len() != codes_shape[0] {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "command_expiry must have length n",
            ));
        }
        let result = self
            .inner
            .step(
                bar_index,
                command_codes.as_slice()?,
                command_values.as_slice()?,
                command_expiry.as_slice()?,
                codes_shape[0],
            )
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let payload = PyDict::new(py);
        payload.set_item("equity", result.equity)?;
        payload.set_item("position", result.position)?;
        payload.set_item("fee", result.fee)?;
        payload.set_item("turnover", result.turnover)?;
        payload.set_item("initial_margin", result.initial_margin)?;
        payload.set_item("maintenance_margin", result.maintenance_margin)?;
        payload.set_item("fills", result.fills)?;
        payload.set_item("events", result.events)?;
        payload.set_item("active_orders", result.active_orders)?;
        Ok(payload.unbind())
    }

    fn reset(&mut self) {
        self.inner.reset();
    }

    fn run_tape_score(
        &mut self,
        py: Python<'_>,
        command_ptr: PyReadonlyArray1<'_, i64>,
        command_codes: PyReadonlyArray2<'_, i64>,
        command_values: PyReadonlyArray2<'_, f64>,
        command_expiry: PyReadonlyArray1<'_, i64>,
    ) -> PyResult<Py<BatchedScoreResultCore>> {
        let ptr = command_ptr.as_slice()?;
        let codes = command_codes.as_slice()?;
        let values = command_values.as_slice()?;
        let expiry = command_expiry.as_slice()?;
        let _count = validate_tape_arrays(
            self.inner.market_len(),
            ptr,
            codes,
            command_codes.shape(),
            values,
            command_values.shape(),
            expiry,
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let output = py
            .detach(|| run_tape(&mut self.inner, ptr, codes, values, expiry, false))
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Py::new(
            py,
            BatchedScoreResultCore {
                final_equity: output.final_equity,
                final_position: output.final_position,
                total_fee: output.total_fee,
                total_turnover: output.total_turnover,
                fill_count: output.fill_count,
                event_count: output.event_count,
                rejected_count: output.rejected_count,
                canceled_count: output.canceled_count,
                max_initial_margin: output.max_initial_margin,
                max_maintenance_margin: output.max_maintenance_margin,
                bars: self.inner.market_len(),
            },
        )
    }

    fn run_tape_audit(
        &mut self,
        py: Python<'_>,
        command_ptr: PyReadonlyArray1<'_, i64>,
        command_codes: PyReadonlyArray2<'_, i64>,
        command_values: PyReadonlyArray2<'_, f64>,
        command_expiry: PyReadonlyArray1<'_, i64>,
    ) -> PyResult<Py<PyDict>> {
        let ptr = command_ptr.as_slice()?;
        let codes = command_codes.as_slice()?;
        let values = command_values.as_slice()?;
        let expiry = command_expiry.as_slice()?;
        let _count = validate_tape_arrays(
            self.inner.market_len(),
            ptr,
            codes,
            command_codes.shape(),
            values,
            command_values.shape(),
            expiry,
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let output = py
            .detach(|| run_tape(&mut self.inner, ptr, codes, values, expiry, true))
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let payload = PyDict::new(py);
        payload.set_item("equity", PyArray1::from_vec(py, output.equity))?;
        payload.set_item("positions", PyArray1::from_vec(py, output.positions))?;
        payload.set_item("fees", PyArray1::from_vec(py, output.fees))?;
        payload.set_item("turnover", PyArray1::from_vec(py, output.turnover))?;
        payload.set_item(
            "initial_margin",
            PyArray1::from_vec(py, output.initial_margin),
        )?;
        payload.set_item(
            "maintenance_margin",
            PyArray1::from_vec(py, output.maintenance_margin),
        )?;
        payload.set_item("fill_bar", PyArray1::from_vec(py, output.fill_bar))?;
        payload.set_item(
            "fill_order_id",
            PyArray1::from_vec(py, output.fill_order_id),
        )?;
        payload.set_item("fill_side", PyArray1::from_vec(py, output.fill_side))?;
        payload.set_item("fill_qty", PyArray1::from_vec(py, output.fill_qty))?;
        payload.set_item("fill_price", PyArray1::from_vec(py, output.fill_price))?;
        payload.set_item("fill_fee", PyArray1::from_vec(py, output.fill_fee))?;
        payload.set_item("event_bar", PyArray1::from_vec(py, output.event_bar))?;
        payload.set_item("event_kind", PyArray1::from_vec(py, output.event_kind))?;
        payload.set_item("event_status", PyArray1::from_vec(py, output.event_status))?;
        payload.set_item(
            "event_order_id",
            PyArray1::from_vec(py, output.event_order_id),
        )?;
        payload.set_item(
            "event_target_id",
            PyArray1::from_vec(py, output.event_target_id),
        )?;
        payload.set_item("total_fee", output.total_fee)?;
        payload.set_item("total_turnover", output.total_turnover)?;
        payload.set_item("fill_count", output.fill_count)?;
        payload.set_item("event_count", output.event_count)?;
        payload.set_item("rejected_count", output.rejected_count)?;
        payload.set_item("canceled_count", output.canceled_count)?;
        payload.set_item("max_initial_margin", output.max_initial_margin)?;
        payload.set_item("max_maintenance_margin", output.max_maintenance_margin)?;
        Ok(payload.unbind())
    }

    #[allow(clippy::too_many_arguments)]
    fn run_until(
        &mut self,
        py: Python<'_>,
        stop_bar: usize,
        command_ptr: PyReadonlyArray1<'_, i64>,
        command_codes: PyReadonlyArray2<'_, i64>,
        command_values: PyReadonlyArray2<'_, f64>,
        command_expiry: PyReadonlyArray1<'_, i64>,
        wake_on_fill: bool,
        wake_on_order_event: bool,
        _wake_on_liquidation: bool,
    ) -> PyResult<Py<PyDict>> {
        let ptr = command_ptr.as_slice()?;
        let codes = command_codes.as_slice()?;
        let values = command_values.as_slice()?;
        let expiry = command_expiry.as_slice()?;
        validate_tape_arrays(
            self.inner.market_len(),
            ptr,
            codes,
            command_codes.shape(),
            values,
            command_values.shape(),
            expiry,
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        if stop_bar >= self.inner.market_len() {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "stop_bar is outside the prepared market tape",
            ));
        }
        let start_bar = self.inner.next_bar();
        if start_bar > stop_bar {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "run_until must advance to a bar after the previous chunk",
            ));
        }
        let output = py
            .detach(|| {
                run_sparse_range(
                    &mut self.inner,
                    start_bar,
                    stop_bar,
                    ptr,
                    codes,
                    values,
                    expiry,
                    wake_on_fill,
                    wake_on_order_event,
                )
            })
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let payload = PyDict::new(py);
        payload.set_item("start_bar", output.start_bar)?;
        payload.set_item("stop_bar", output.stop_bar)?;
        payload.set_item("final_equity", output.final_equity)?;
        payload.set_item("final_position", output.final_position)?;
        payload.set_item("total_fee", output.total_fee)?;
        payload.set_item("total_turnover", output.total_turnover)?;
        payload.set_item("fill_count", output.fill_count)?;
        payload.set_item("event_count", output.event_count)?;
        payload.set_item("rejected_count", output.rejected_count)?;
        payload.set_item("canceled_count", output.canceled_count)?;
        payload.set_item("max_initial_margin", output.max_initial_margin)?;
        payload.set_item("max_maintenance_margin", output.max_maintenance_margin)?;
        payload.set_item("liquidation_seen", output.liquidation_seen)?;
        payload.set_item("wake_bar", PyArray1::from_vec(py, output.wake_bar))?;
        payload.set_item("wake_kind", PyArray1::from_vec(py, output.wake_kind))?;
        payload.set_item("fill_bar", PyArray1::from_vec(py, output.fill_bar))?;
        payload.set_item(
            "fill_order_id",
            PyArray1::from_vec(py, output.fill_order_id),
        )?;
        payload.set_item("fill_side", PyArray1::from_vec(py, output.fill_side))?;
        payload.set_item("fill_qty", PyArray1::from_vec(py, output.fill_qty))?;
        payload.set_item("fill_price", PyArray1::from_vec(py, output.fill_price))?;
        payload.set_item("fill_fee", PyArray1::from_vec(py, output.fill_fee))?;
        payload.set_item("event_bar", PyArray1::from_vec(py, output.event_bar))?;
        payload.set_item("event_kind", PyArray1::from_vec(py, output.event_kind))?;
        payload.set_item("event_status", PyArray1::from_vec(py, output.event_status))?;
        payload.set_item(
            "event_order_id",
            PyArray1::from_vec(py, output.event_order_id),
        )?;
        payload.set_item(
            "event_target_id",
            PyArray1::from_vec(py, output.event_target_id),
        )?;
        Ok(payload.unbind())
    }
}

fn validate_tape_arrays(
    market_len: usize,
    command_ptr: &[i64],
    codes: &[i64],
    codes_shape: &[usize],
    values: &[f64],
    values_shape: &[usize],
    expiry: &[i64],
) -> Result<usize, String> {
    if command_ptr.len() != market_len + 1 {
        return Err("command_ptr must have length n_bars + 1".to_owned());
    }
    if codes_shape.len() != 2 || codes_shape[1] != types::COMMAND_CODE_WIDTH {
        return Err("command_codes must have shape (n, 8)".to_owned());
    }
    if values_shape.len() != 2
        || values_shape[0] != codes_shape[0]
        || values_shape[1] != types::COMMAND_VALUE_WIDTH
    {
        return Err("command_values must have shape (n, 3)".to_owned());
    }
    if expiry.len() != codes_shape[0] {
        return Err("command_expiry must have length n".to_owned());
    }
    if expiry.iter().any(|value| *value != -1) {
        return Err("Rust batched tape does not support expiry".to_owned());
    }
    if command_ptr.first().copied().unwrap_or(-1) != 0 {
        return Err("command_ptr must start at zero".to_owned());
    }
    let command_count = codes_shape[0] as i64;
    let mut previous = 0_i64;
    for &value in command_ptr {
        if value < previous || value > command_count {
            return Err("command_ptr must be monotonic and bounded by command count".to_owned());
        }
        previous = value;
    }
    if command_ptr.last().copied().unwrap_or(-1) != command_count {
        return Err("command_ptr last value must equal command count".to_owned());
    }
    if codes.len() != codes_shape[0] * types::COMMAND_CODE_WIDTH
        || values.len() != values_shape[0] * types::COMMAND_VALUE_WIDTH
    {
        return Err("command buffers are not contiguous with their declared shapes".to_owned());
    }
    Ok(codes_shape[0])
}

fn run_tape(
    session: &mut LegacyFullSessionAdapter,
    command_ptr: &[i64],
    codes: &[i64],
    values: &[f64],
    expiry: &[i64],
    audit: bool,
) -> Result<BatchedTapeOutput, String> {
    let n_bars = session.market_len();
    let mut equity = if audit {
        Vec::with_capacity(n_bars)
    } else {
        Vec::new()
    };
    let mut positions = if audit {
        Vec::with_capacity(n_bars)
    } else {
        Vec::new()
    };
    let mut fees = if audit {
        Vec::with_capacity(n_bars)
    } else {
        Vec::new()
    };
    let mut turnover = if audit {
        Vec::with_capacity(n_bars)
    } else {
        Vec::new()
    };
    let mut initial_margin = if audit {
        Vec::with_capacity(n_bars)
    } else {
        Vec::new()
    };
    let mut maintenance_margin = if audit {
        Vec::with_capacity(n_bars)
    } else {
        Vec::new()
    };
    let mut fill_bar = Vec::new();
    let mut fill_order_id = Vec::new();
    let mut fill_side = Vec::new();
    let mut fill_qty = Vec::new();
    let mut fill_price = Vec::new();
    let mut fill_fee = Vec::new();
    let mut event_bar = Vec::new();
    let mut event_kind = Vec::new();
    let mut event_status = Vec::new();
    let mut event_order_id = Vec::new();
    let mut event_target_id = Vec::new();
    let mut total_fee = 0.0;
    let mut total_turnover = 0.0;
    let mut fill_count = 0_i64;
    let mut event_count = 0_i64;
    let mut rejected_count = 0_i64;
    let mut canceled_count = 0_i64;
    let mut final_equity = 0.0;
    let mut final_position = 0.0;
    let mut max_initial_margin: f64 = 0.0;
    let mut max_maintenance_margin: f64 = 0.0;

    for bar in 0..n_bars {
        let start = command_ptr[bar] as usize;
        let end = command_ptr[bar + 1] as usize;
        let step = session.step_with_output(
            bar,
            &codes[start * types::COMMAND_CODE_WIDTH..end * types::COMMAND_CODE_WIDTH],
            &values[start * types::COMMAND_VALUE_WIDTH..end * types::COMMAND_VALUE_WIDTH],
            &expiry[start..end],
            end - start,
            audit,
        )?;
        if audit {
            equity.push(step.equity);
            positions.push(step.position);
            fees.push(step.fee);
            turnover.push(step.turnover);
            initial_margin.push(step.initial_margin);
            maintenance_margin.push(step.maintenance_margin);
        }
        final_equity = step.equity;
        final_position = step.position;
        max_initial_margin = max_initial_margin.max(step.initial_margin);
        max_maintenance_margin = max_maintenance_margin.max(step.maintenance_margin);
        total_fee += step.fee;
        total_turnover += step.turnover;
        fill_count += step.fill_count;
        event_count += step.event_count;
        rejected_count += step.rejected_count;
        canceled_count += step.canceled_count;
        for fill in step.fills {
            if audit {
                fill_bar.push(bar as i64);
                fill_order_id.push(fill[0] as i64);
                fill_side.push(fill[1] as i64);
                fill_qty.push(fill[2]);
                fill_price.push(fill[3]);
                fill_fee.push(fill[4]);
            }
        }
        for event in step.events {
            if audit {
                event_bar.push(bar as i64);
                event_kind.push(event[0]);
                event_status.push(event[1]);
                event_order_id.push(event[2]);
                event_target_id.push(event[3]);
            }
        }
    }
    Ok(BatchedTapeOutput {
        equity,
        positions,
        fees,
        turnover,
        initial_margin,
        maintenance_margin,
        total_fee,
        total_turnover,
        fill_count,
        event_count,
        rejected_count,
        canceled_count,
        fill_bar,
        fill_order_id,
        fill_side,
        fill_qty,
        fill_price,
        fill_fee,
        event_bar,
        event_kind,
        event_status,
        event_order_id,
        event_target_id,
        final_equity,
        final_position,
        max_initial_margin,
        max_maintenance_margin,
    })
}

#[allow(clippy::too_many_arguments)]
fn run_sparse_range(
    session: &mut LegacyFullSessionAdapter,
    start_bar: usize,
    stop_bar: usize,
    command_ptr: &[i64],
    codes: &[i64],
    values: &[f64],
    expiry: &[i64],
    wake_on_fill: bool,
    wake_on_order_event: bool,
) -> Result<SparseTapeOutput, String> {
    let mut output = SparseTapeOutput {
        start_bar,
        stop_bar,
        final_equity: 0.0,
        final_position: 0.0,
        total_fee: 0.0,
        total_turnover: 0.0,
        fill_count: 0,
        event_count: 0,
        rejected_count: 0,
        canceled_count: 0,
        max_initial_margin: 0.0,
        max_maintenance_margin: 0.0,
        liquidation_seen: false,
        wake_bar: Vec::new(),
        wake_kind: Vec::new(),
        fill_bar: Vec::new(),
        fill_order_id: Vec::new(),
        fill_side: Vec::new(),
        fill_qty: Vec::new(),
        fill_price: Vec::new(),
        fill_fee: Vec::new(),
        event_bar: Vec::new(),
        event_kind: Vec::new(),
        event_status: Vec::new(),
        event_order_id: Vec::new(),
        event_target_id: Vec::new(),
    };

    for bar in start_bar..=stop_bar {
        let start = command_ptr[bar] as usize;
        let end = command_ptr[bar + 1] as usize;
        let materialize = wake_on_fill || wake_on_order_event;
        let step = session.step_with_output(
            bar,
            &codes[start * types::COMMAND_CODE_WIDTH..end * types::COMMAND_CODE_WIDTH],
            &values[start * types::COMMAND_VALUE_WIDTH..end * types::COMMAND_VALUE_WIDTH],
            &expiry[start..end],
            end - start,
            materialize,
        )?;
        output.final_equity = step.equity;
        output.final_position = step.position;
        output.max_initial_margin = output.max_initial_margin.max(step.initial_margin);
        output.max_maintenance_margin = output.max_maintenance_margin.max(step.maintenance_margin);
        output.total_fee += step.fee;
        output.total_turnover += step.turnover;
        output.fill_count += step.fill_count;
        output.event_count += step.event_count;
        output.rejected_count += step.rejected_count;
        output.canceled_count += step.canceled_count;
        for fill in step.fills {
            if wake_on_fill {
                output.wake_bar.push(bar as i64);
                output.wake_kind.push(0);
            }
            output.fill_bar.push(bar as i64);
            output.fill_order_id.push(fill[0] as i64);
            output.fill_side.push(fill[1] as i64);
            output.fill_qty.push(fill[2]);
            output.fill_price.push(fill[3]);
            output.fill_fee.push(fill[4]);
        }
        for event in step.events {
            if wake_on_order_event {
                output.wake_bar.push(bar as i64);
                output.wake_kind.push(1);
            }
            output.event_bar.push(bar as i64);
            output.event_kind.push(event[0]);
            output.event_status.push(event[1]);
            output.event_order_id.push(event[2]);
            output.event_target_id.push(event[3]);
        }
    }
    // Kind 2 means end-of-chunk. It is always emitted so a caller can make
    // progress without reconstructing a dense per-bar result path.
    output.wake_bar.push(stop_bar as i64);
    output.wake_kind.push(2);
    Ok(output)
}

struct BatchedTapeOutput {
    equity: Vec<f64>,
    positions: Vec<f64>,
    fees: Vec<f64>,
    turnover: Vec<f64>,
    initial_margin: Vec<f64>,
    maintenance_margin: Vec<f64>,
    total_fee: f64,
    total_turnover: f64,
    fill_count: i64,
    event_count: i64,
    rejected_count: i64,
    canceled_count: i64,
    fill_bar: Vec<i64>,
    fill_order_id: Vec<i64>,
    fill_side: Vec<i64>,
    fill_qty: Vec<f64>,
    fill_price: Vec<f64>,
    fill_fee: Vec<f64>,
    event_bar: Vec<i64>,
    event_kind: Vec<i64>,
    event_status: Vec<i64>,
    event_order_id: Vec<i64>,
    event_target_id: Vec<i64>,
    final_equity: f64,
    final_position: f64,
    max_initial_margin: f64,
    max_maintenance_margin: f64,
}

struct SparseTapeOutput {
    start_bar: usize,
    stop_bar: usize,
    final_equity: f64,
    final_position: f64,
    total_fee: f64,
    total_turnover: f64,
    fill_count: i64,
    event_count: i64,
    rejected_count: i64,
    canceled_count: i64,
    max_initial_margin: f64,
    max_maintenance_margin: f64,
    liquidation_seen: bool,
    wake_bar: Vec<i64>,
    wake_kind: Vec<i64>,
    fill_bar: Vec<i64>,
    fill_order_id: Vec<i64>,
    fill_side: Vec<i64>,
    fill_qty: Vec<f64>,
    fill_price: Vec<f64>,
    fill_fee: Vec<f64>,
    event_bar: Vec<i64>,
    event_kind: Vec<i64>,
    event_status: Vec<i64>,
    event_order_id: Vec<i64>,
    event_target_id: Vec<i64>,
}

#[pyclass(frozen, skip_from_py_object)]
struct FullStepResultCore {
    #[pyo3(get)]
    equity: f64,
    #[pyo3(get)]
    fee: f64,
    #[pyo3(get)]
    turnover: f64,
    #[pyo3(get)]
    funding: f64,
    #[pyo3(get)]
    initial_margin: f64,
    #[pyo3(get)]
    maintenance_margin: f64,
    #[pyo3(get)]
    total_fee: f64,
    #[pyo3(get)]
    total_turnover: f64,
    #[pyo3(get)]
    total_funding: f64,
    #[pyo3(get)]
    total_rejected: i64,
    #[pyo3(get)]
    total_canceled: i64,
    #[pyo3(get)]
    fill_count: i64,
    #[pyo3(get)]
    event_count: i64,
    #[pyo3(get)]
    rejected_count: i64,
    #[pyo3(get)]
    canceled_count: i64,
    #[pyo3(get)]
    liquidated: bool,
    #[pyo3(get)]
    liquidation_bar: i64,
    #[pyo3(get)]
    liquidation_reason: i64,
    #[pyo3(get)]
    positions: Option<Vec<f64>>,
    #[pyo3(get)]
    fills: Option<Vec<Vec<f64>>>,
    #[pyo3(get)]
    events: Option<Vec<Vec<i64>>>,
    #[pyo3(get)]
    active_orders: Option<Vec<Vec<f64>>>,
    #[pyo3(get)]
    fill_begin: u64,
    #[pyo3(get)]
    fill_end: u64,
    #[pyo3(get)]
    event_begin: u64,
    #[pyo3(get)]
    event_end: u64,
    #[pyo3(get)]
    order_delta_begin: u64,
    #[pyo3(get)]
    order_delta_end: u64,
    #[pyo3(get)]
    position_delta_begin: u64,
    #[pyo3(get)]
    position_delta_end: u64,
}

impl FullStepResultCore {
    #[allow(clippy::too_many_arguments)]
    fn from_result(
        result: full::FullStepResult,
        output_mask: u8,
        total_fee: f64,
        total_turnover: f64,
        total_funding: f64,
        total_rejected: i64,
        total_canceled: i64,
        fill_begin: u64,
        event_begin: u64,
        order_delta_begin: u64,
        position_delta_begin: u64,
        position_delta_count: u64,
    ) -> Self {
        let fill_end = fill_begin + result.fill_count.max(0) as u64;
        let event_end = event_begin + result.event_count.max(0) as u64;
        let order_delta_end = order_delta_begin + result.event_count.max(0) as u64;
        Self {
            equity: result.equity,
            fee: result.fee,
            turnover: result.turnover,
            funding: result.funding,
            initial_margin: result.initial_margin,
            maintenance_margin: result.maintenance_margin,
            total_fee,
            total_turnover,
            total_funding,
            total_rejected,
            total_canceled,
            fill_count: result.fill_count,
            event_count: result.event_count,
            rejected_count: result.rejected_count,
            canceled_count: result.canceled_count,
            liquidated: result.liquidated,
            liquidation_bar: result.liquidation_bar,
            liquidation_reason: result.liquidation_reason,
            positions: (output_mask & full::OUTPUT_POSITIONS != 0).then_some(result.positions),
            fills: (output_mask & full::OUTPUT_FILLS != 0).then_some(result.fills),
            events: (output_mask & full::OUTPUT_EVENTS != 0).then_some(result.events),
            active_orders: (output_mask & full::OUTPUT_ACTIVE_ORDERS != 0)
                .then_some(result.active_orders),
            fill_begin,
            fill_end,
            event_begin,
            event_end,
            order_delta_begin,
            order_delta_end,
            position_delta_begin,
            position_delta_end: position_delta_begin + position_delta_count,
        }
    }
}

#[pyclass]
pub(crate) struct FullPreparedMarketCore {
    pub(crate) inner: Arc<FullMarketData>,
}

#[pymethods]
impl FullPreparedMarketCore {
    #[new]
    #[allow(clippy::too_many_arguments)]
    fn new(
        timestamps_ns: PyReadonlyArray1<'_, i64>,
        opens: PyReadonlyArray2<'_, f64>,
        highs: PyReadonlyArray2<'_, f64>,
        lows: PyReadonlyArray2<'_, f64>,
        closes: PyReadonlyArray2<'_, f64>,
        volumes: PyReadonlyArray2<'_, f64>,
        funding: PyReadonlyArray2<'_, f64>,
        funding_mask: PyReadonlyArray1<'_, bool>,
    ) -> PyResult<Self> {
        let shapes = [
            opens.shape(),
            highs.shape(),
            lows.shape(),
            closes.shape(),
            volumes.shape(),
            funding.shape(),
        ];
        if shapes
            .iter()
            .any(|shape| shape.len() != 2 || *shape != closes.shape())
        {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "full OHLCV/funding arrays must share shape (n_bars, n_symbols)",
            ));
        }
        let market = FullMarketData::new(
            timestamps_ns.as_slice()?.to_vec(),
            opens.as_slice()?.to_vec(),
            highs.as_slice()?.to_vec(),
            lows.as_slice()?.to_vec(),
            closes.as_slice()?.to_vec(),
            volumes.as_slice()?.to_vec(),
            funding.as_slice()?.to_vec(),
            funding_mask.as_slice()?.to_vec(),
            closes.shape()[1],
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(Self {
            inner: Arc::new(market),
        })
    }

    #[getter]
    fn bars(&self) -> usize {
        self.inner.n_bars
    }

    #[getter]
    fn symbols(&self) -> usize {
        self.inner.n_symbols
    }

    /// Native-owned immutable tape bytes. This excludes transient NumPy
    /// ingress buffers and output buffers, which have separate ownership.
    #[getter]
    fn prepared_bytes(&self) -> usize {
        self.inner.timestamps_ns.len() * std::mem::size_of::<i64>()
            + self.inner.opens.len() * std::mem::size_of::<f64>()
            + self.inner.highs.len() * std::mem::size_of::<f64>()
            + self.inner.lows.len() * std::mem::size_of::<f64>()
            + self.inner.closes.len() * std::mem::size_of::<f64>()
            + self.inner.volumes.len() * std::mem::size_of::<f64>()
            + self.inner.funding.len() * std::mem::size_of::<f64>()
            + self.inner.funding_mask.len() * std::mem::size_of::<bool>()
    }

    /// Number of native `Arc` owners for the immutable market tape. It is a
    /// lifetime diagnostic only; callers must not infer cache correctness from
    /// this count.
    #[getter]
    fn reference_count(&self) -> usize {
        Arc::strong_count(&self.inner)
    }
}

/// Typed one-run ingress for the bounded single-symbol intrabar contract.
///
/// The prepared market remains native-owned through an `Arc`; Python passes
/// compact intent/session arrays once, then Rust owns the complete bracket,
/// account, funding, liquidation, and audit state machine for the run.
#[pyclass]
struct NativeIntrabarRequestCore {
    inner: Arc<execution::intrabar::IntrabarRequestV1>,
}

#[pymethods]
impl NativeIntrabarRequestCore {
    #[classmethod]
    #[pyo3(signature = (
        prepared,
        entry_side,
        entry_size,
        stop_value,
        take_profit_value,
        trailing_value,
        exit_long,
        exit_short,
        level_mode,
        initial_capital,
        leverage,
        maintenance_ratio,
        margin_buffer,
        contract_size,
        fee_rate,
        slippage_rate,
        sizing_mode,
        fixed_notional,
        equity_fraction,
        risk_fraction,
        qty_step,
        min_qty,
        min_notional,
        tick_size,
        bar_timestamp_semantics,
        same_bar_policy,
        take_profit_gap_policy,
        close_on_last_bar,
        output_profile=1,
        audit_detail_limit=250000,
        session_id=None,
        entry_allowed_at_open=None,
        force_flat_at_open=None,
        entry_position_policy=1,
        counter_basis=1,
        protective_reentry_policy=1,
        max_long_entries_per_session=-1,
        max_short_entries_per_session=-1,
        cancel_pending_on_session_change=true,
        suppress_entry_on_force_flat_bar=true
    ))]
    #[allow(clippy::too_many_arguments)]
    fn from_prepared(
        _cls: &Bound<'_, PyType>,
        py: Python<'_>,
        prepared: Py<FullPreparedMarketCore>,
        entry_side: PyReadonlyArray1<'_, i8>,
        entry_size: PyReadonlyArray1<'_, f64>,
        stop_value: PyReadonlyArray1<'_, f64>,
        take_profit_value: PyReadonlyArray1<'_, f64>,
        trailing_value: PyReadonlyArray1<'_, f64>,
        exit_long: PyReadonlyArray1<'_, bool>,
        exit_short: PyReadonlyArray1<'_, bool>,
        level_mode: u8,
        initial_capital: f64,
        leverage: f64,
        maintenance_ratio: f64,
        margin_buffer: f64,
        contract_size: f64,
        fee_rate: f64,
        slippage_rate: f64,
        sizing_mode: u8,
        fixed_notional: f64,
        equity_fraction: f64,
        risk_fraction: f64,
        qty_step: f64,
        min_qty: f64,
        min_notional: f64,
        tick_size: f64,
        bar_timestamp_semantics: u8,
        same_bar_policy: u8,
        take_profit_gap_policy: u8,
        close_on_last_bar: bool,
        output_profile: u8,
        audit_detail_limit: usize,
        session_id: Option<PyReadonlyArray1<'_, i64>>,
        entry_allowed_at_open: Option<PyReadonlyArray1<'_, bool>>,
        force_flat_at_open: Option<PyReadonlyArray1<'_, bool>>,
        entry_position_policy: u8,
        counter_basis: u8,
        protective_reentry_policy: u8,
        max_long_entries_per_session: i64,
        max_short_entries_per_session: i64,
        cancel_pending_on_session_change: bool,
        suppress_entry_on_force_flat_bar: bool,
    ) -> PyResult<Self> {
        let market = prepared.borrow(py).inner.clone();
        let intent = execution::intrabar::IntrabarIntentV1::new(
            entry_side.as_slice()?.to_vec(),
            entry_size.as_slice()?.to_vec(),
            stop_value.as_slice()?.to_vec(),
            take_profit_value.as_slice()?.to_vec(),
            trailing_value.as_slice()?.to_vec(),
            exit_long.as_slice()?.to_vec(),
            exit_short.as_slice()?.to_vec(),
            level_mode,
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let account = execution::intrabar::IntrabarAccountConfigV1::new(
            initial_capital,
            leverage,
            maintenance_ratio,
            margin_buffer,
            contract_size,
            fee_rate,
            slippage_rate,
            sizing_mode,
            fixed_notional,
            equity_fraction,
            risk_fraction,
            qty_step,
            min_qty,
            min_notional,
            tick_size,
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let contract = execution::intrabar::IntrabarContractConfigV1::new(
            bar_timestamp_semantics,
            same_bar_policy,
            take_profit_gap_policy,
            close_on_last_bar,
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let session = match (session_id, entry_allowed_at_open, force_flat_at_open) {
            (None, None, None) => None,
            (Some(session_id), Some(entry_allowed), Some(force_flat)) => Some(
                execution::intrabar::IntrabarSessionConfigV1::new(
                    session_id.as_slice()?.to_vec(),
                    entry_allowed.as_slice()?.to_vec(),
                    force_flat.as_slice()?.to_vec(),
                    entry_position_policy,
                    counter_basis,
                    protective_reentry_policy,
                    max_long_entries_per_session,
                    max_short_entries_per_session,
                    cancel_pending_on_session_change,
                    suppress_entry_on_force_flat_bar,
                )
                .map_err(pyo3::exceptions::PyValueError::new_err)?,
            ),
            _ => {
                return Err(pyo3::exceptions::PyValueError::new_err(
                    "session_id, entry_allowed_at_open, and force_flat_at_open must be supplied together",
                ));
            }
        };
        let output = execution::intrabar::IntrabarOutputProfileV1::try_from(output_profile)
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let inner = execution::intrabar::IntrabarRequestV1::new(
            market,
            intent,
            account,
            contract,
            session,
            output,
            audit_detail_limit,
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(Self {
            inner: Arc::new(inner),
        })
    }

    #[getter]
    fn fingerprint(&self) -> String {
        self.inner.fingerprint_hex()
    }

    #[getter]
    fn bars(&self) -> usize {
        self.inner.bar_count()
    }

    #[getter]
    fn source_market_bytes(&self) -> usize {
        self.inner.source_market_bytes()
    }

    #[getter]
    fn output_profile(&self) -> &'static str {
        self.inner.output_profile().name()
    }

    #[getter]
    fn session_enabled(&self) -> bool {
        self.inner.session_enabled()
    }

    fn execute(&self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        let request = self.inner.clone();
        let bars = request.bar_count();
        let result = py.detach(move || request.execute());
        intrabar_result_payload(py, result, bars)
    }
}

fn intrabar_hex(value: [u8; 32]) -> String {
    value.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn intrabar_result_payload(
    py: Python<'_>,
    result: execution::intrabar::IntrabarExecutionResultV1,
    bars: usize,
) -> PyResult<Py<PyDict>> {
    let payload = PyDict::new(py);
    let metric_fields =
        NativeMetricFieldsCore::from_snapshot(result.metric_contract, result.metrics);
    let request_fingerprint = intrabar_hex(result.request_fingerprint);
    let terminal_fingerprint = intrabar_hex(result.terminal_fingerprint);
    payload.set_item("output_profile", result.output_profile.name())?;
    payload.set_item("final_equity", result.final_equity)?;
    payload.set_item("final_position", result.final_position)?;
    payload.set_item("total_fee", result.total_fee)?;
    payload.set_item("total_turnover", result.total_turnover)?;
    payload.set_item("total_funding", result.total_funding)?;
    payload.set_item("fill_count", result.fill_count)?;
    payload.set_item("event_count", metric_fields.event_count)?;
    payload.set_item("ambiguity_count", result.ambiguity_count)?;
    payload.set_item("rejected_count", result.rejected_count)?;
    payload.set_item("canceled_count", metric_fields.canceled_count)?;
    payload.set_item("liquidated", result.liquidated)?;
    payload.set_item("liquidation_bar", result.liquidation_bar)?;
    payload.set_item("execution_model_id", result.execution_model_id)?;
    payload.set_item("request_fingerprint", &request_fingerprint)?;
    payload.set_item("terminal_fingerprint", &terminal_fingerprint)?;
    payload.set_item("native_execution_request_fingerprint", &request_fingerprint)?;
    payload.set_item(
        "native_execution_terminal_fingerprint",
        &terminal_fingerprint,
    )?;
    payload.set_item("native_execution_workload", "intrabar_bracket_v1")?;
    payload.set_item("native_execution_runtime_class", "whole_run_native")?;
    payload.set_item("native_execution_account_authority", "linear_account_v1")?;
    payload.set_item("native_execution_model_id", result.execution_model_id)?;
    payload.set_item(
        "native_execution_metric_contract_version",
        metric_fields.contract_version,
    )?;
    payload.set_item(
        "native_execution_output_profile",
        result.output_profile.name(),
    )?;
    payload.set_item("bars", bars)?;
    payload.set_item("native_execution_passes", 1)?;
    payload.set_item("python_callbacks", 0)?;
    payload.set_item("boundary_calls", 1)?;
    add_metric_fields(&payload, &metric_fields)?;
    payload.set_item("audit_detail_retained_rows", result.audit.retained_rows)?;
    payload.set_item("audit_detail_dropped_rows", result.audit.dropped_rows)?;
    payload.set_item("audit_detail_truncated", result.audit.dropped_rows > 0)?;

    if let Some(paths) = result.paths {
        payload.set_item("equity", PyArray1::from_vec(py, paths.equity))?;
        payload.set_item("position", PyArray1::from_vec(py, paths.position))?;
        payload.set_item("average_entry", PyArray1::from_vec(py, paths.average_entry))?;
        payload.set_item("active_stop", PyArray1::from_vec(py, paths.active_stop))?;
        payload.set_item(
            "active_take_profit",
            PyArray1::from_vec(py, paths.active_take_profit),
        )?;
        payload.set_item("fees", PyArray1::from_vec(py, paths.fees))?;
        payload.set_item("funding", PyArray1::from_vec(py, paths.funding))?;
        payload.set_item("event_flags", PyArray1::from_vec(py, paths.event_flags))?;
        payload.set_item(
            "initial_margin",
            PyArray1::from_vec(py, paths.initial_margin),
        )?;
        payload.set_item(
            "maintenance_margin",
            PyArray1::from_vec(py, paths.maintenance_margin),
        )?;
    }

    let fills = result.audit.fills;
    let fill_bar = fills.iter().map(|fill| fill.bar).collect();
    let fill_sequence = fills.iter().map(|fill| fill.sequence).collect();
    let fill_side = fills.iter().map(|fill| fill.side).collect();
    let fill_qty = fills.iter().map(|fill| fill.qty).collect();
    let fill_price = fills.iter().map(|fill| fill.price).collect();
    let fill_fee = fills.iter().map(|fill| fill.fee).collect();
    let fill_reason = fills.iter().map(|fill| fill.reason).collect();
    let fill_ambiguity = fills.iter().map(|fill| fill.ambiguity).collect();
    let fill_same_bar_policy = fills.iter().map(|fill| fill.same_bar_policy).collect();
    payload.set_item("fill_bar", PyArray1::from_vec(py, fill_bar))?;
    payload.set_item("fill_sequence", PyArray1::from_vec(py, fill_sequence))?;
    payload.set_item("fill_side", PyArray1::from_vec(py, fill_side))?;
    payload.set_item("fill_qty", PyArray1::from_vec(py, fill_qty))?;
    payload.set_item("fill_price", PyArray1::from_vec(py, fill_price))?;
    payload.set_item("fill_fee", PyArray1::from_vec(py, fill_fee))?;
    payload.set_item("fill_reason", PyArray1::from_vec(py, fill_reason))?;
    payload.set_item("fill_ambiguity", PyArray1::from_vec(py, fill_ambiguity))?;
    payload.set_item(
        "fill_same_bar_policy",
        PyArray1::from_vec(py, fill_same_bar_policy),
    )?;
    payload.set_item(
        "ambiguity_bar",
        PyArray1::from_vec(py, result.audit.ambiguity_bar),
    )?;
    payload.set_item(
        "ambiguity_policy",
        PyArray1::from_vec(py, result.audit.ambiguity_policy),
    )?;

    if let Some(session) = result.session {
        payload.set_item("session_execution_enabled", true)?;
        payload.set_item("session_reset_count", session.session_reset_count)?;
        payload.set_item(
            "session_forced_exit_count",
            session.session_forced_exit_count,
        )?;
        payload.set_item(
            "entry_window_blocked_count",
            session.entry_window_blocked_count,
        )?;
        payload.set_item("long_quota_blocked_count", session.long_quota_blocked_count)?;
        payload.set_item(
            "short_quota_blocked_count",
            session.short_quota_blocked_count,
        )?;
        payload.set_item("flat_only_blocked_count", session.flat_only_blocked_count)?;
        payload.set_item(
            "stale_session_signal_count",
            session.stale_session_signal_count,
        )?;
        payload.set_item("reentry_suppressed_count", session.reentry_suppressed_count)?;
    } else {
        payload.set_item("session_execution_enabled", false)?;
    }
    Ok(payload.unbind())
}

/// One native result object's immutable execution provenance. Python owns the
/// NumPy arrays after the Rust vectors have moved across the cold boundary.
/// The metadata is intentionally scalar so score requests never construct a
/// dictionary just to return a score.
struct NativeOutputMetadataCore {
    native_result_version: u16,
    output_version: u16,
    request_version: u16,
    protocol_version: u16,
    request_fingerprint: String,
    template_fingerprint: String,
    contract_bundle_hash: String,
    terminal_fingerprint: String,
    workload_kind: &'static str,
    runtime_class: &'static str,
    account_authority: &'static str,
    execution_model_id: &'static str,
    metric_contract_version: u16,
    output_profile: &'static str,
    command_count: usize,
    bars: usize,
    execution_generation: u64,
    runner_run_count: u64,
    detail_truncated: bool,
    retained_rows: u64,
    dropped_rows: u64,
    output_bytes: usize,
}

impl NativeOutputMetadataCore {
    fn from_result(result: &execution::NativeExecutionResultV1, output_bytes: usize) -> Self {
        let header = &result.header_v2;
        Self {
            native_result_version: header.result_version,
            output_version: result.output.score().output_version,
            request_version: result.request_version,
            protocol_version: result.protocol_version,
            request_fingerprint: result.fingerprint_hex(),
            template_fingerprint: result.template_fingerprint_hex(),
            contract_bundle_hash: header.contract_bundle_hash_hex(),
            terminal_fingerprint: header.terminal_fingerprint_hex(),
            workload_kind: result.workload_kind.name(),
            runtime_class: header.authority.runtime_class,
            account_authority: header.authority.account_authority,
            execution_model_id: header.authority.execution_model_id,
            metric_contract_version: header.authority.metric_contract_version,
            output_profile: result.output_profile.name(),
            command_count: result.command_count,
            bars: result.bar_count,
            execution_generation: result.execution_generation,
            runner_run_count: result.runner_run_count,
            detail_truncated: header.detail_truncated,
            retained_rows: header.retained_rows,
            dropped_rows: header.dropped_rows,
            output_bytes,
        }
    }
}

/// Scalar native metric policy and values returned by the same authoritative
/// execution pass. It owns no Python report object; dictionaries are created
/// only by explicit typed-result cold-path accessors below.
#[derive(Clone, Copy)]
struct NativeMetricFieldsCore {
    contract_version: u16,
    return_frequency: &'static str,
    annualization_factor: f64,
    risk_free_rate: f64,
    variance_ddof: u8,
    zero_variance_policy: &'static str,
    short_run_policy: &'static str,
    trade_count_definition: &'static str,
    total_return: f64,
    cagr: f64,
    mean_return: f64,
    variance: f64,
    sharpe: f64,
    sortino: f64,
    max_drawdown: f64,
    calmar: f64,
    omega: f64,
    profit_factor: f64,
    average_gross_exposure: f64,
    final_equity: f64,
    turnover: f64,
    total_fee: f64,
    total_funding: f64,
    fill_count: u64,
    event_count: u64,
    rejected_count: u64,
    canceled_count: u64,
    sample_count: u64,
    liquidated: bool,
}

impl NativeMetricFieldsCore {
    fn from_native(output: &quantbt_engine::NativeScoreOutputV1) -> Self {
        Self::from_snapshot(output.metric_contract, *output.metrics_v2)
    }

    fn from_snapshot(
        contract: quantbt_engine::MetricContractV2,
        metrics: quantbt_engine::NativeMetricSnapshotV2,
    ) -> Self {
        Self {
            contract_version: metrics.metric_contract_version,
            return_frequency: match contract.return_frequency {
                quantbt_engine::ReturnFrequencyV2::PerBar => "per_bar",
                quantbt_engine::ReturnFrequencyV2::Daily => "daily",
            },
            annualization_factor: contract.annualization_factor,
            risk_free_rate: contract.risk_free_rate,
            variance_ddof: contract.variance_ddof,
            zero_variance_policy: match contract.zero_variance_policy {
                quantbt_engine::ZeroVariancePolicyV2::ReturnZero => "return_zero",
            },
            short_run_policy: match contract.short_run_policy {
                quantbt_engine::ShortRunMetricPolicyV2::ReturnZero => "return_zero",
            },
            trade_count_definition: match contract.trade_count_definition {
                quantbt_engine::TradeCountDefinitionV2::CommittedFills => "committed_fills",
            },
            total_return: metrics.total_return,
            cagr: metrics.cagr,
            mean_return: metrics.mean_return,
            variance: metrics.variance,
            sharpe: metrics.sharpe,
            sortino: metrics.sortino,
            max_drawdown: metrics.max_drawdown,
            calmar: metrics.calmar,
            omega: metrics.omega,
            profit_factor: metrics.profit_factor,
            average_gross_exposure: metrics.average_gross_exposure,
            final_equity: metrics.final_equity,
            turnover: metrics.turnover,
            total_fee: metrics.total_fee,
            total_funding: metrics.total_funding,
            fill_count: metrics.fill_count,
            event_count: metrics.event_count,
            rejected_count: metrics.rejected_count,
            canceled_count: metrics.canceled_count,
            sample_count: metrics.sample_count,
            liquidated: metrics.liquidated,
        }
    }
}

/// Scalar columns shared by score, compact, and audit outputs. The final
/// position array moves directly from Rust-owned `Vec<f64>` into its NumPy
/// owner, preserving the result after the request/session is dropped.
struct NativeScoreFieldsCore {
    final_equity: f64,
    final_positions: Py<PyArray1<f64>>,
    total_fee: f64,
    total_turnover: f64,
    total_funding: f64,
    fill_count: i64,
    event_count: i64,
    rejected_count: i64,
    canceled_count: i64,
    max_initial_margin: f64,
    max_maintenance_margin: f64,
    liquidated: bool,
    liquidation_bar: i64,
    liquidation_reason: i64,
    metrics: NativeMetricFieldsCore,
}

impl NativeScoreFieldsCore {
    fn from_native(py: Python<'_>, output: quantbt_engine::NativeScoreOutputV1) -> Self {
        let metrics = NativeMetricFieldsCore::from_native(&output);
        Self {
            final_equity: output.final_equity,
            final_positions: PyArray1::from_vec(py, output.final_positions).unbind(),
            total_fee: output.total_fee,
            total_turnover: output.total_turnover,
            total_funding: output.total_funding,
            fill_count: output.fill_count,
            event_count: output.event_count,
            rejected_count: output.rejected_count,
            canceled_count: output.canceled_count,
            max_initial_margin: output.max_initial_margin,
            max_maintenance_margin: output.max_maintenance_margin,
            liquidated: output.liquidated,
            liquidation_bar: output.liquidation_bar,
            liquidation_reason: output.liquidation_reason,
            metrics,
        }
    }
}

/// Dense account arrays carried by compact/audit profiles only.
struct NativePathFieldsCore {
    equity: Py<PyArray1<f64>>,
    positions: Py<PyArray1<f64>>,
    fees: Py<PyArray1<f64>>,
    turnover: Py<PyArray1<f64>>,
    funding: Py<PyArray1<f64>>,
    initial_margin: Py<PyArray1<f64>>,
    maintenance_margin: Py<PyArray1<f64>>,
}

impl NativePathFieldsCore {
    fn from_native(py: Python<'_>, output: quantbt_engine::NativePathOutputV1) -> Self {
        Self {
            equity: PyArray1::from_vec(py, output.equity).unbind(),
            positions: PyArray1::from_vec(py, output.positions).unbind(),
            fees: PyArray1::from_vec(py, output.fees).unbind(),
            turnover: PyArray1::from_vec(py, output.turnover).unbind(),
            funding: PyArray1::from_vec(py, output.funding).unbind(),
            initial_margin: PyArray1::from_vec(py, output.initial_margin).unbind(),
            maintenance_margin: PyArray1::from_vec(py, output.maintenance_margin).unbind(),
        }
    }
}

/// Audit-only typed fill/event SoA columns. IDs remain `int64` rather than
/// being silently coerced into floating-point values.
struct NativeAuditFieldsCore {
    fill_bar: Py<PyArray1<i64>>,
    fill_order_id: Py<PyArray1<i64>>,
    fill_symbol: Py<PyArray1<i64>>,
    fill_side: Py<PyArray1<i64>>,
    fill_qty: Py<PyArray1<f64>>,
    fill_price: Py<PyArray1<f64>>,
    fill_fee: Py<PyArray1<f64>>,
    fill_reason: Py<PyArray1<i64>>,
    fill_ambiguity: Py<PyArray1<i64>>,
    event_bar: Py<PyArray1<i64>>,
    event_kind: Py<PyArray1<i64>>,
    event_status: Py<PyArray1<i64>>,
    event_order_id: Py<PyArray1<i64>>,
    event_target_id: Py<PyArray1<i64>>,
    event_symbol: Py<PyArray1<i64>>,
    event_reject_code: Py<PyArray1<i64>>,
}

impl NativeAuditFieldsCore {
    fn from_native(
        py: Python<'_>,
        fills: quantbt_engine::NativeFillOutputV1,
        events: quantbt_engine::NativeEventOutputV1,
    ) -> Self {
        Self {
            fill_bar: PyArray1::from_vec(py, fills.bar).unbind(),
            fill_order_id: PyArray1::from_vec(py, fills.order_id).unbind(),
            fill_symbol: PyArray1::from_vec(py, fills.symbol).unbind(),
            fill_side: PyArray1::from_vec(py, fills.side).unbind(),
            fill_qty: PyArray1::from_vec(py, fills.qty).unbind(),
            fill_price: PyArray1::from_vec(py, fills.price).unbind(),
            fill_fee: PyArray1::from_vec(py, fills.fee).unbind(),
            fill_reason: PyArray1::from_vec(py, fills.reason).unbind(),
            fill_ambiguity: PyArray1::from_vec(py, fills.ambiguity).unbind(),
            event_bar: PyArray1::from_vec(py, events.bar).unbind(),
            event_kind: PyArray1::from_vec(py, events.kind).unbind(),
            event_status: PyArray1::from_vec(py, events.status).unbind(),
            event_order_id: PyArray1::from_vec(py, events.order_id).unbind(),
            event_target_id: PyArray1::from_vec(py, events.target_id).unbind(),
            event_symbol: PyArray1::from_vec(py, events.symbol).unbind(),
            event_reject_code: PyArray1::from_vec(py, events.reject_code).unbind(),
        }
    }
}

/// Audit-only provenance for dynamic portfolio/package admission. It is
/// adjacent to, but deliberately distinct from, the canonical fill/event
/// trace: target/package admission never reconstructs fills or accounting in
/// Python. The bounded vectors move directly into NumPy only for audit output.
enum NativeWorkloadAuditFieldsCore {
    None,
    DirectTarget {
        target_kind: &'static str,
        timing: u8,
        invalid_target_policy: &'static str,
        decision_count: usize,
        rejected_decision_count: usize,
        retention: quantbt_engine::AuditRetentionV1,
        bar: Py<PyArray1<i64>>,
        symbol: Py<PyArray1<i64>>,
        requested_units: Py<PyArray1<f64>>,
        accepted_units: Py<PyArray1<f64>>,
        rejection_code: Py<PyArray1<i64>>,
        rejected_by_bar: Option<Py<PyArray1<i64>>>,
        reject_code_by_bar: Option<Py<PyArray1<i64>>>,
    },
    PortfolioTarget {
        decision_count: usize,
        rejected_decision_count: usize,
        retention: quantbt_engine::AuditRetentionV1,
        bar: Py<PyArray1<i64>>,
        requested_units: Py<PyArray1<f64>>,
        accepted_units: Py<PyArray1<f64>>,
        rejection_code: Py<PyArray1<i64>>,
    },
    PackageAtomic {
        command_bar: i64,
        package_id: u64,
        attempted: bool,
        reserved_margin: f64,
        released_margin: f64,
        package_fee: f64,
        residual_notional: f64,
        retention: quantbt_engine::AuditRetentionV1,
        accepted: Py<PyArray1<bool>>,
        rejection_code: Py<PyArray1<i64>>,
        transition_code: Py<PyArray1<i64>>,
    },
    /// Package V2 detail remains flat Rust-owned audit data until the caller
    /// explicitly asks for the cold compatibility dictionary. Unlike the
    /// legacy atomic route, it can contain multiple packages and bounded leg,
    /// residual, and transition arrays, so keeping it as one typed struct
    /// avoids allocating per-row Python objects at execution completion.
    // Keep the bounded V2 provenance vectors indirect through the cold-path
    // adapter so ordinary output variants do not carry its inline footprint.
    PackageMarketV2(Box<execution::package::PackageMarketAuditV2>),
}

impl NativeWorkloadAuditFieldsCore {
    fn from_direct_target(
        py: Python<'_>,
        target_kind: execution::target::DirectTargetKindV1,
        timing: u8,
        invalid_target_policy: execution::target::InvalidTargetPolicyV1,
        audit: execution::target::DirectTargetAuditV1,
        rejected_by_bar: Option<Vec<i64>>,
        reject_code_by_bar: Option<Vec<i64>>,
    ) -> Self {
        Self::DirectTarget {
            target_kind: target_kind.name(),
            timing,
            invalid_target_policy: invalid_target_policy.name(),
            decision_count: audit.decision_count,
            rejected_decision_count: audit.rejected_decision_count,
            retention: audit.detail_retention,
            bar: PyArray1::from_vec(py, audit.bar).unbind(),
            symbol: PyArray1::from_vec(py, audit.symbol).unbind(),
            requested_units: PyArray1::from_vec(py, audit.requested_units).unbind(),
            accepted_units: PyArray1::from_vec(py, audit.accepted_units).unbind(),
            rejection_code: PyArray1::from_vec(py, audit.rejection_code).unbind(),
            rejected_by_bar: rejected_by_bar.map(|values| PyArray1::from_vec(py, values).unbind()),
            reject_code_by_bar: reject_code_by_bar
                .map(|values| PyArray1::from_vec(py, values).unbind()),
        }
    }

    fn from_native(py: Python<'_>, audit: execution::NativeWorkloadAuditV1) -> Self {
        match audit {
            execution::NativeWorkloadAuditV1::None => Self::None,
            execution::NativeWorkloadAuditV1::PortfolioTarget(audit) => Self::PortfolioTarget {
                decision_count: audit.decision_count,
                rejected_decision_count: audit.rejected_decision_count,
                retention: audit.detail_retention,
                bar: PyArray1::from_vec(py, audit.bar).unbind(),
                requested_units: PyArray1::from_vec(py, audit.requested_units).unbind(),
                accepted_units: PyArray1::from_vec(py, audit.accepted_units).unbind(),
                rejection_code: PyArray1::from_vec(py, audit.rejection_code).unbind(),
            },
            execution::NativeWorkloadAuditV1::PackageAtomic(audit) => Self::PackageAtomic {
                command_bar: audit.command_bar,
                package_id: audit.package_id,
                attempted: audit.attempted,
                reserved_margin: audit.reserved_margin,
                released_margin: audit.released_margin,
                package_fee: audit.package_fee,
                residual_notional: audit.residual_notional,
                retention: audit.detail_retention,
                accepted: PyArray1::from_vec(py, audit.accepted).unbind(),
                rejection_code: PyArray1::from_vec(py, audit.rejection_code).unbind(),
                transition_code: PyArray1::from_vec(py, audit.transition_code).unbind(),
            },
            execution::NativeWorkloadAuditV1::PackageMarketV2(audit) => {
                Self::PackageMarketV2(audit)
            }
        }
    }

    const fn kind(&self) -> &'static str {
        match self {
            Self::None => "none",
            Self::DirectTarget { .. } => "direct_target_v1",
            Self::PortfolioTarget { .. } => "portfolio_target_market_v1",
            Self::PackageAtomic { .. } => "package_atomic_market_v1",
            Self::PackageMarketV2(_) => "package_market_v2",
        }
    }

    const fn retention(&self) -> quantbt_engine::AuditRetentionV1 {
        match self {
            Self::None => quantbt_engine::AuditRetentionV1::new(0),
            Self::DirectTarget { retention, .. }
            | Self::PortfolioTarget { retention, .. }
            | Self::PackageAtomic { retention, .. } => *retention,
            Self::PackageMarketV2(audit) => audit.detail_retention,
        }
    }
}

fn bytes_f64(values: &[f64]) -> usize {
    values.len().saturating_mul(std::mem::size_of::<f64>())
}

fn bytes_i64(values: &[i64]) -> usize {
    values.len().saturating_mul(std::mem::size_of::<i64>())
}

fn bytes_u64(values: &[u64]) -> usize {
    values.len().saturating_mul(std::mem::size_of::<u64>())
}

fn bytes_bool(values: &[bool]) -> usize {
    values.len().saturating_mul(std::mem::size_of::<bool>())
}

fn workload_audit_output_bytes(audit: &execution::NativeWorkloadAuditV1) -> usize {
    match audit {
        execution::NativeWorkloadAuditV1::None => 0,
        execution::NativeWorkloadAuditV1::PortfolioTarget(audit) => bytes_i64(&audit.bar)
            .saturating_add(bytes_f64(&audit.requested_units))
            .saturating_add(bytes_f64(&audit.accepted_units))
            .saturating_add(bytes_i64(&audit.rejection_code)),
        execution::NativeWorkloadAuditV1::PackageAtomic(audit) => bytes_bool(&audit.accepted)
            .saturating_add(bytes_i64(&audit.rejection_code))
            .saturating_add(bytes_i64(&audit.transition_code)),
        execution::NativeWorkloadAuditV1::PackageMarketV2(audit) => bytes_u64(&audit.package_id)
            .saturating_add(bytes_i64(&audit.command_bar))
            .saturating_add(bytes_i64(&audit.policy_code))
            .saturating_add(bytes_i64(&audit.final_state_code))
            .saturating_add(bytes_f64(&audit.reservation_created))
            .saturating_add(bytes_f64(&audit.reservation_consumed))
            .saturating_add(bytes_f64(&audit.reservation_released))
            .saturating_add(bytes_f64(&audit.package_fee))
            .saturating_add(bytes_f64(&audit.residual_gross_notional))
            .saturating_add(bytes_f64(&audit.outstanding_residual_gross_notional))
            .saturating_add(bytes_u64(&audit.leg_package_id))
            .saturating_add(bytes_i64(&audit.leg_index))
            .saturating_add(bytes_i64(&audit.leg_order_id))
            .saturating_add(bytes_i64(&audit.leg_symbol))
            .saturating_add(bytes_f64(&audit.leg_requested_qty))
            .saturating_add(bytes_f64(&audit.leg_filled_qty))
            .saturating_add(bytes_f64(&audit.leg_compensation_qty))
            .saturating_add(bytes_bool(&audit.leg_accepted))
            .saturating_add(bytes_i64(&audit.leg_rejection_code))
            .saturating_add(bytes_u64(&audit.residual_package_id))
            .saturating_add(bytes_i64(&audit.residual_leg_index))
            .saturating_add(bytes_i64(&audit.residual_symbol))
            .saturating_add(bytes_f64(&audit.residual_qty))
            .saturating_add(bytes_f64(&audit.residual_notional))
            .saturating_add(bytes_i64(&audit.residual_reason_code))
            .saturating_add(bytes_u64(&audit.transition_package_id))
            .saturating_add(bytes_i64(&audit.transition_code)),
    }
}

fn score_output_bytes(output: &quantbt_engine::NativeScoreOutputV1) -> usize {
    bytes_f64(&output.final_positions)
}

fn compact_output_bytes(output: &quantbt_engine::NativeCompactOutputV1) -> usize {
    let paths = &output.paths;
    score_output_bytes(&output.score)
        .saturating_add(bytes_f64(&paths.equity))
        .saturating_add(bytes_f64(&paths.positions))
        .saturating_add(bytes_f64(&paths.fees))
        .saturating_add(bytes_f64(&paths.turnover))
        .saturating_add(bytes_f64(&paths.funding))
        .saturating_add(bytes_f64(&paths.initial_margin))
        .saturating_add(bytes_f64(&paths.maintenance_margin))
}

fn audit_output_bytes(output: &quantbt_engine::NativeAuditOutputV1) -> usize {
    let fills = &output.fills;
    let events = &output.events;
    compact_output_bytes(&output.compact)
        .saturating_add(bytes_i64(&fills.bar))
        .saturating_add(bytes_i64(&fills.order_id))
        .saturating_add(bytes_i64(&fills.symbol))
        .saturating_add(bytes_i64(&fills.side))
        .saturating_add(bytes_f64(&fills.qty))
        .saturating_add(bytes_f64(&fills.price))
        .saturating_add(bytes_f64(&fills.fee))
        .saturating_add(bytes_i64(&fills.reason))
        .saturating_add(bytes_i64(&fills.ambiguity))
        .saturating_add(bytes_i64(&events.bar))
        .saturating_add(bytes_i64(&events.kind))
        .saturating_add(bytes_i64(&events.status))
        .saturating_add(bytes_i64(&events.order_id))
        .saturating_add(bytes_i64(&events.target_id))
        .saturating_add(bytes_i64(&events.symbol))
        .saturating_add(bytes_i64(&events.reject_code))
}

fn add_typed_output_metadata(
    payload: &Bound<'_, PyDict>,
    metadata: &NativeOutputMetadataCore,
) -> PyResult<()> {
    payload.set_item("native_result_version", metadata.native_result_version)?;
    payload.set_item("native_execution_output_version", metadata.output_version)?;
    payload.set_item("native_execution_request_version", metadata.request_version)?;
    payload.set_item(
        "native_execution_protocol_version",
        metadata.protocol_version,
    )?;
    payload.set_item(
        "native_execution_request_fingerprint",
        &metadata.request_fingerprint,
    )?;
    payload.set_item(
        "native_execution_template_fingerprint",
        &metadata.template_fingerprint,
    )?;
    payload.set_item(
        "native_execution_contract_bundle_hash",
        &metadata.contract_bundle_hash,
    )?;
    payload.set_item(
        "native_execution_terminal_fingerprint",
        &metadata.terminal_fingerprint,
    )?;
    payload.set_item("native_execution_workload", metadata.workload_kind)?;
    payload.set_item("native_execution_runtime_class", metadata.runtime_class)?;
    payload.set_item(
        "native_execution_account_authority",
        metadata.account_authority,
    )?;
    payload.set_item("native_execution_model_id", metadata.execution_model_id)?;
    payload.set_item(
        "native_metric_contract_version",
        metadata.metric_contract_version,
    )?;
    payload.set_item("native_execution_output_profile", metadata.output_profile)?;
    payload.set_item("native_execution_command_count", metadata.command_count)?;
    payload.set_item("bars", metadata.bars)?;
    payload.set_item("native_execution_generation", metadata.execution_generation)?;
    payload.set_item(
        "native_execution_runner_run_count",
        metadata.runner_run_count,
    )?;
    payload.set_item(
        "native_execution_detail_truncated",
        metadata.detail_truncated,
    )?;
    payload.set_item("native_execution_retained_rows", metadata.retained_rows)?;
    payload.set_item("native_execution_dropped_rows", metadata.dropped_rows)?;
    payload.set_item("native_execution_output_bytes", metadata.output_bytes)?;
    payload.set_item(
        "native_execution_buffer_transfer",
        "rust_vec_to_numpy_zero_copy",
    )?;
    payload.set_item("native_execution_passes", 1)?;
    payload.set_item("python_callbacks", 0)?;
    payload.set_item("boundary_calls", 1)?;
    Ok(())
}

fn add_metric_fields(
    payload: &Bound<'_, PyDict>,
    metrics: &NativeMetricFieldsCore,
) -> PyResult<()> {
    payload.set_item("native_metric_contract_version", metrics.contract_version)?;
    payload.set_item("native_metric_return_frequency", metrics.return_frequency)?;
    payload.set_item(
        "native_metric_annualization_factor",
        metrics.annualization_factor,
    )?;
    payload.set_item("native_metric_risk_free_rate", metrics.risk_free_rate)?;
    payload.set_item("native_metric_variance_ddof", metrics.variance_ddof)?;
    payload.set_item(
        "native_metric_zero_variance_policy",
        metrics.zero_variance_policy,
    )?;
    payload.set_item("native_metric_short_run_policy", metrics.short_run_policy)?;
    payload.set_item(
        "native_metric_trade_count_definition",
        metrics.trade_count_definition,
    )?;
    payload.set_item("native_metric_total_return", metrics.total_return)?;
    payload.set_item("native_metric_cagr", metrics.cagr)?;
    payload.set_item("native_metric_mean_return", metrics.mean_return)?;
    payload.set_item("native_metric_variance", metrics.variance)?;
    payload.set_item("native_metric_sharpe", metrics.sharpe)?;
    payload.set_item("native_metric_sortino", metrics.sortino)?;
    payload.set_item("native_metric_max_drawdown", metrics.max_drawdown)?;
    payload.set_item("native_metric_calmar", metrics.calmar)?;
    payload.set_item("native_metric_omega", metrics.omega)?;
    payload.set_item("native_metric_profit_factor", metrics.profit_factor)?;
    payload.set_item(
        "native_metric_average_gross_exposure",
        metrics.average_gross_exposure,
    )?;
    payload.set_item("native_metric_final_equity", metrics.final_equity)?;
    payload.set_item("native_metric_turnover", metrics.turnover)?;
    payload.set_item("native_metric_total_fee", metrics.total_fee)?;
    payload.set_item("native_metric_total_funding", metrics.total_funding)?;
    payload.set_item("native_metric_fill_count", metrics.fill_count)?;
    payload.set_item("native_metric_event_count", metrics.event_count)?;
    payload.set_item("native_metric_rejected_count", metrics.rejected_count)?;
    payload.set_item("native_metric_canceled_count", metrics.canceled_count)?;
    payload.set_item("native_metric_sample_count", metrics.sample_count)?;
    payload.set_item("native_metric_liquidated", metrics.liquidated)?;
    Ok(())
}

fn native_metric_payload(py: Python<'_>, metrics: &NativeMetricFieldsCore) -> PyResult<Py<PyDict>> {
    let payload = PyDict::new(py);
    add_metric_fields(&payload, metrics)?;
    Ok(payload.unbind())
}

fn add_score_fields(
    py: Python<'_>,
    payload: &Bound<'_, PyDict>,
    score: &NativeScoreFieldsCore,
) -> PyResult<()> {
    payload.set_item("final_equity", score.final_equity)?;
    payload.set_item("final_positions", score.final_positions.clone_ref(py))?;
    payload.set_item("total_fee", score.total_fee)?;
    payload.set_item("total_turnover", score.total_turnover)?;
    payload.set_item("total_funding", score.total_funding)?;
    payload.set_item("fill_count", score.fill_count)?;
    payload.set_item("event_count", score.event_count)?;
    payload.set_item("rejected_count", score.rejected_count)?;
    payload.set_item("canceled_count", score.canceled_count)?;
    payload.set_item("max_initial_margin", score.max_initial_margin)?;
    payload.set_item("max_maintenance_margin", score.max_maintenance_margin)?;
    payload.set_item("liquidated", score.liquidated)?;
    payload.set_item("liquidation_bar", score.liquidation_bar)?;
    payload.set_item("liquidation_reason", score.liquidation_reason)?;
    add_metric_fields(payload, &score.metrics)?;
    Ok(())
}

fn add_path_fields(
    py: Python<'_>,
    payload: &Bound<'_, PyDict>,
    paths: &NativePathFieldsCore,
) -> PyResult<()> {
    payload.set_item("equity", paths.equity.clone_ref(py))?;
    payload.set_item("positions", paths.positions.clone_ref(py))?;
    payload.set_item("fees", paths.fees.clone_ref(py))?;
    payload.set_item("turnover", paths.turnover.clone_ref(py))?;
    payload.set_item("funding", paths.funding.clone_ref(py))?;
    payload.set_item("initial_margin", paths.initial_margin.clone_ref(py))?;
    payload.set_item("maintenance_margin", paths.maintenance_margin.clone_ref(py))?;
    Ok(())
}

fn add_audit_fields(
    py: Python<'_>,
    payload: &Bound<'_, PyDict>,
    audit: &NativeAuditFieldsCore,
) -> PyResult<()> {
    payload.set_item("fill_bar", audit.fill_bar.clone_ref(py))?;
    payload.set_item("fill_order_id", audit.fill_order_id.clone_ref(py))?;
    payload.set_item("fill_symbol", audit.fill_symbol.clone_ref(py))?;
    payload.set_item("fill_side", audit.fill_side.clone_ref(py))?;
    payload.set_item("fill_qty", audit.fill_qty.clone_ref(py))?;
    payload.set_item("fill_price", audit.fill_price.clone_ref(py))?;
    payload.set_item("fill_fee", audit.fill_fee.clone_ref(py))?;
    payload.set_item("fill_reason", audit.fill_reason.clone_ref(py))?;
    payload.set_item("fill_ambiguity", audit.fill_ambiguity.clone_ref(py))?;
    payload.set_item("event_bar", audit.event_bar.clone_ref(py))?;
    payload.set_item("event_kind", audit.event_kind.clone_ref(py))?;
    payload.set_item("event_status", audit.event_status.clone_ref(py))?;
    payload.set_item("event_order_id", audit.event_order_id.clone_ref(py))?;
    payload.set_item("event_target_id", audit.event_target_id.clone_ref(py))?;
    payload.set_item("event_symbol", audit.event_symbol.clone_ref(py))?;
    payload.set_item("event_reject_code", audit.event_reject_code.clone_ref(py))?;
    Ok(())
}

/// Typed score result for ABI-0.5 requests. It contains scalar accounting and
/// final positions only. Use `as_dict()` only when a legacy/cold-path consumer
/// explicitly requires a mapping.
#[pyclass(name = "NativeScoreOutputV1", module = "_quantbt_native")]
struct NativeScoreOutputCore {
    metadata: NativeOutputMetadataCore,
    score: NativeScoreFieldsCore,
}

#[pymethods]
impl NativeScoreOutputCore {
    #[getter]
    fn native_result_version(&self) -> u16 {
        self.metadata.native_result_version
    }

    #[getter]
    fn output_version(&self) -> u16 {
        self.metadata.output_version
    }

    #[getter]
    fn request_version(&self) -> u16 {
        self.metadata.request_version
    }

    #[getter]
    fn protocol_version(&self) -> u16 {
        self.metadata.protocol_version
    }

    #[getter]
    fn fingerprint(&self) -> String {
        self.metadata.request_fingerprint.clone()
    }

    #[getter]
    fn template_fingerprint(&self) -> String {
        self.metadata.template_fingerprint.clone()
    }

    #[getter]
    fn workload_kind(&self) -> &'static str {
        self.metadata.workload_kind
    }

    #[getter]
    fn output_profile(&self) -> &'static str {
        self.metadata.output_profile
    }

    #[getter]
    fn command_count(&self) -> usize {
        self.metadata.command_count
    }

    #[getter]
    fn bars(&self) -> usize {
        self.metadata.bars
    }

    #[getter]
    fn execution_generation(&self) -> u64 {
        self.metadata.execution_generation
    }

    #[getter]
    fn runner_run_count(&self) -> u64 {
        self.metadata.runner_run_count
    }

    #[getter]
    fn output_bytes(&self) -> usize {
        self.metadata.output_bytes
    }

    #[getter]
    fn contract_bundle_hash(&self) -> String {
        self.metadata.contract_bundle_hash.clone()
    }

    #[getter]
    fn terminal_fingerprint(&self) -> String {
        self.metadata.terminal_fingerprint.clone()
    }

    #[getter]
    fn execution_model_id(&self) -> &'static str {
        self.metadata.execution_model_id
    }

    #[getter]
    fn runtime_class(&self) -> &'static str {
        self.metadata.runtime_class
    }

    #[getter]
    fn account_authority(&self) -> &'static str {
        self.metadata.account_authority
    }

    #[getter]
    fn metric_contract_version(&self) -> u16 {
        self.metadata.metric_contract_version
    }

    #[getter]
    fn detail_truncated(&self) -> bool {
        self.metadata.detail_truncated
    }

    #[getter]
    fn retained_rows(&self) -> u64 {
        self.metadata.retained_rows
    }

    #[getter]
    fn dropped_rows(&self) -> u64 {
        self.metadata.dropped_rows
    }

    #[getter]
    fn final_equity(&self) -> f64 {
        self.score.final_equity
    }

    #[getter]
    fn final_positions(&self, py: Python<'_>) -> Py<PyArray1<f64>> {
        self.score.final_positions.clone_ref(py)
    }

    #[getter]
    fn total_fee(&self) -> f64 {
        self.score.total_fee
    }

    #[getter]
    fn total_turnover(&self) -> f64 {
        self.score.total_turnover
    }

    #[getter]
    fn total_funding(&self) -> f64 {
        self.score.total_funding
    }

    #[getter]
    fn fill_count(&self) -> i64 {
        self.score.fill_count
    }

    #[getter]
    fn event_count(&self) -> i64 {
        self.score.event_count
    }

    #[getter]
    fn rejected_count(&self) -> i64 {
        self.score.rejected_count
    }

    #[getter]
    fn canceled_count(&self) -> i64 {
        self.score.canceled_count
    }

    #[getter]
    fn max_initial_margin(&self) -> f64 {
        self.score.max_initial_margin
    }

    #[getter]
    fn max_maintenance_margin(&self) -> f64 {
        self.score.max_maintenance_margin
    }

    #[getter]
    fn liquidated(&self) -> bool {
        self.score.liquidated
    }

    #[getter]
    fn liquidation_bar(&self) -> i64 {
        self.score.liquidation_bar
    }

    #[getter]
    fn liquidation_reason(&self) -> i64 {
        self.score.liquidation_reason
    }

    #[getter]
    fn metrics(&self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        native_metric_payload(py, &self.score.metrics)
    }

    /// Explicit cold-path compatibility conversion. It creates one mapping
    /// after execution; the score run itself never allocated a `PyDict`.
    fn as_dict(&self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        let payload = PyDict::new(py);
        add_typed_output_metadata(&payload, &self.metadata)?;
        add_score_fields(py, &payload, &self.score)?;
        Ok(payload.unbind())
    }
}

/// Typed compact result with scalar accounting and contiguous dense account
/// paths. It intentionally has no fill/event attributes.
struct DirectTargetCompactFieldsCore {
    rejected_by_bar: Py<PyArray1<i64>>,
    reject_code_by_bar: Py<PyArray1<i64>>,
}

impl DirectTargetCompactFieldsCore {
    fn from_required(
        py: Python<'_>,
        rejected_by_bar: Option<Vec<i64>>,
        reject_code_by_bar: Option<Vec<i64>>,
    ) -> Self {
        Self {
            rejected_by_bar: PyArray1::from_vec(
                py,
                rejected_by_bar.expect("compact direct target output requires rejected_by_bar"),
            )
            .unbind(),
            reject_code_by_bar: PyArray1::from_vec(
                py,
                reject_code_by_bar
                    .expect("compact direct target output requires reject_code_by_bar"),
            )
            .unbind(),
        }
    }
}

#[pyclass(name = "NativeCompactOutputV1", module = "_quantbt_native")]
struct NativeCompactOutputCore {
    metadata: NativeOutputMetadataCore,
    score: NativeScoreFieldsCore,
    paths: NativePathFieldsCore,
    direct_target: Option<DirectTargetCompactFieldsCore>,
}

#[pymethods]
impl NativeCompactOutputCore {
    #[getter]
    fn native_result_version(&self) -> u16 {
        self.metadata.native_result_version
    }

    #[getter]
    fn output_version(&self) -> u16 {
        self.metadata.output_version
    }

    #[getter]
    fn request_version(&self) -> u16 {
        self.metadata.request_version
    }

    #[getter]
    fn protocol_version(&self) -> u16 {
        self.metadata.protocol_version
    }

    #[getter]
    fn fingerprint(&self) -> String {
        self.metadata.request_fingerprint.clone()
    }

    #[getter]
    fn template_fingerprint(&self) -> String {
        self.metadata.template_fingerprint.clone()
    }

    #[getter]
    fn workload_kind(&self) -> &'static str {
        self.metadata.workload_kind
    }

    #[getter]
    fn output_profile(&self) -> &'static str {
        self.metadata.output_profile
    }

    #[getter]
    fn command_count(&self) -> usize {
        self.metadata.command_count
    }

    #[getter]
    fn bars(&self) -> usize {
        self.metadata.bars
    }

    #[getter]
    fn execution_generation(&self) -> u64 {
        self.metadata.execution_generation
    }

    #[getter]
    fn runner_run_count(&self) -> u64 {
        self.metadata.runner_run_count
    }

    #[getter]
    fn output_bytes(&self) -> usize {
        self.metadata.output_bytes
    }

    #[getter]
    fn contract_bundle_hash(&self) -> String {
        self.metadata.contract_bundle_hash.clone()
    }

    #[getter]
    fn terminal_fingerprint(&self) -> String {
        self.metadata.terminal_fingerprint.clone()
    }

    #[getter]
    fn execution_model_id(&self) -> &'static str {
        self.metadata.execution_model_id
    }

    #[getter]
    fn runtime_class(&self) -> &'static str {
        self.metadata.runtime_class
    }

    #[getter]
    fn account_authority(&self) -> &'static str {
        self.metadata.account_authority
    }

    #[getter]
    fn metric_contract_version(&self) -> u16 {
        self.metadata.metric_contract_version
    }

    #[getter]
    fn detail_truncated(&self) -> bool {
        self.metadata.detail_truncated
    }

    #[getter]
    fn retained_rows(&self) -> u64 {
        self.metadata.retained_rows
    }

    #[getter]
    fn dropped_rows(&self) -> u64 {
        self.metadata.dropped_rows
    }

    #[getter]
    fn final_equity(&self) -> f64 {
        self.score.final_equity
    }

    #[getter]
    fn final_positions(&self, py: Python<'_>) -> Py<PyArray1<f64>> {
        self.score.final_positions.clone_ref(py)
    }

    #[getter]
    fn total_fee(&self) -> f64 {
        self.score.total_fee
    }

    #[getter]
    fn total_turnover(&self) -> f64 {
        self.score.total_turnover
    }

    #[getter]
    fn total_funding(&self) -> f64 {
        self.score.total_funding
    }

    #[getter]
    fn fill_count(&self) -> i64 {
        self.score.fill_count
    }

    #[getter]
    fn event_count(&self) -> i64 {
        self.score.event_count
    }

    #[getter]
    fn rejected_count(&self) -> i64 {
        self.score.rejected_count
    }

    #[getter]
    fn canceled_count(&self) -> i64 {
        self.score.canceled_count
    }

    #[getter]
    fn max_initial_margin(&self) -> f64 {
        self.score.max_initial_margin
    }

    #[getter]
    fn max_maintenance_margin(&self) -> f64 {
        self.score.max_maintenance_margin
    }

    #[getter]
    fn liquidated(&self) -> bool {
        self.score.liquidated
    }

    #[getter]
    fn liquidation_bar(&self) -> i64 {
        self.score.liquidation_bar
    }

    #[getter]
    fn liquidation_reason(&self) -> i64 {
        self.score.liquidation_reason
    }

    #[getter]
    fn metrics(&self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        native_metric_payload(py, &self.score.metrics)
    }

    #[getter]
    fn equity(&self, py: Python<'_>) -> Py<PyArray1<f64>> {
        self.paths.equity.clone_ref(py)
    }

    #[getter]
    fn positions(&self, py: Python<'_>) -> Py<PyArray1<f64>> {
        self.paths.positions.clone_ref(py)
    }

    #[getter]
    fn fees(&self, py: Python<'_>) -> Py<PyArray1<f64>> {
        self.paths.fees.clone_ref(py)
    }

    #[getter]
    fn turnover(&self, py: Python<'_>) -> Py<PyArray1<f64>> {
        self.paths.turnover.clone_ref(py)
    }

    #[getter]
    fn funding(&self, py: Python<'_>) -> Py<PyArray1<f64>> {
        self.paths.funding.clone_ref(py)
    }

    #[getter]
    fn initial_margin(&self, py: Python<'_>) -> Py<PyArray1<f64>> {
        self.paths.initial_margin.clone_ref(py)
    }

    #[getter]
    fn maintenance_margin(&self, py: Python<'_>) -> Py<PyArray1<f64>> {
        self.paths.maintenance_margin.clone_ref(py)
    }

    #[getter]
    fn direct_target_rejected_by_bar(&self, py: Python<'_>) -> Option<Py<PyArray1<i64>>> {
        self.direct_target
            .as_ref()
            .map(|fields| fields.rejected_by_bar.clone_ref(py))
    }

    #[getter]
    fn direct_target_reject_code_by_bar(&self, py: Python<'_>) -> Option<Py<PyArray1<i64>>> {
        self.direct_target
            .as_ref()
            .map(|fields| fields.reject_code_by_bar.clone_ref(py))
    }

    /// Explicit cold-path compatibility conversion after a compact run.
    fn as_dict(&self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        let payload = PyDict::new(py);
        add_typed_output_metadata(&payload, &self.metadata)?;
        add_score_fields(py, &payload, &self.score)?;
        add_path_fields(py, &payload, &self.paths)?;
        if let Some(fields) = self.direct_target.as_ref() {
            payload.set_item(
                "direct_target_rejected_by_bar",
                fields.rejected_by_bar.clone_ref(py),
            )?;
            payload.set_item(
                "direct_target_reject_code_by_bar",
                fields.reject_code_by_bar.clone_ref(py),
            )?;
        }
        Ok(payload.unbind())
    }
}

/// Typed audit result with compact accounting paths and typed fill/event
/// columns. It is the only native route that retains detail by default.
#[pyclass(name = "NativeAuditOutputV1", module = "_quantbt_native")]
struct NativeAuditOutputCore {
    metadata: NativeOutputMetadataCore,
    score: NativeScoreFieldsCore,
    paths: NativePathFieldsCore,
    audit: NativeAuditFieldsCore,
    workload_audit: NativeWorkloadAuditFieldsCore,
}

#[pymethods]
impl NativeAuditOutputCore {
    #[getter]
    fn native_result_version(&self) -> u16 {
        self.metadata.native_result_version
    }

    #[getter]
    fn output_version(&self) -> u16 {
        self.metadata.output_version
    }

    #[getter]
    fn request_version(&self) -> u16 {
        self.metadata.request_version
    }

    #[getter]
    fn protocol_version(&self) -> u16 {
        self.metadata.protocol_version
    }

    #[getter]
    fn fingerprint(&self) -> String {
        self.metadata.request_fingerprint.clone()
    }

    #[getter]
    fn template_fingerprint(&self) -> String {
        self.metadata.template_fingerprint.clone()
    }

    #[getter]
    fn workload_kind(&self) -> &'static str {
        self.metadata.workload_kind
    }

    #[getter]
    fn output_profile(&self) -> &'static str {
        self.metadata.output_profile
    }

    #[getter]
    fn command_count(&self) -> usize {
        self.metadata.command_count
    }

    #[getter]
    fn bars(&self) -> usize {
        self.metadata.bars
    }

    #[getter]
    fn execution_generation(&self) -> u64 {
        self.metadata.execution_generation
    }

    #[getter]
    fn runner_run_count(&self) -> u64 {
        self.metadata.runner_run_count
    }

    #[getter]
    fn output_bytes(&self) -> usize {
        self.metadata.output_bytes
    }

    #[getter]
    fn contract_bundle_hash(&self) -> String {
        self.metadata.contract_bundle_hash.clone()
    }

    #[getter]
    fn terminal_fingerprint(&self) -> String {
        self.metadata.terminal_fingerprint.clone()
    }

    #[getter]
    fn execution_model_id(&self) -> &'static str {
        self.metadata.execution_model_id
    }

    #[getter]
    fn runtime_class(&self) -> &'static str {
        self.metadata.runtime_class
    }

    #[getter]
    fn account_authority(&self) -> &'static str {
        self.metadata.account_authority
    }

    #[getter]
    fn metric_contract_version(&self) -> u16 {
        self.metadata.metric_contract_version
    }

    #[getter]
    fn detail_truncated(&self) -> bool {
        self.metadata.detail_truncated
    }

    #[getter]
    fn retained_rows(&self) -> u64 {
        self.metadata.retained_rows
    }

    #[getter]
    fn dropped_rows(&self) -> u64 {
        self.metadata.dropped_rows
    }

    #[getter]
    fn workload_audit_kind(&self) -> &'static str {
        self.workload_audit.kind()
    }

    #[getter]
    fn workload_audit_detail_truncated(&self) -> bool {
        self.workload_audit.retention().truncated()
    }

    #[getter]
    fn workload_audit_retained_rows(&self) -> usize {
        self.workload_audit.retention().retained_rows
    }

    #[getter]
    fn workload_audit_dropped_rows(&self) -> usize {
        self.workload_audit.retention().dropped_rows
    }

    #[getter]
    fn final_equity(&self) -> f64 {
        self.score.final_equity
    }

    #[getter]
    fn final_positions(&self, py: Python<'_>) -> Py<PyArray1<f64>> {
        self.score.final_positions.clone_ref(py)
    }

    #[getter]
    fn total_fee(&self) -> f64 {
        self.score.total_fee
    }

    #[getter]
    fn total_turnover(&self) -> f64 {
        self.score.total_turnover
    }

    #[getter]
    fn total_funding(&self) -> f64 {
        self.score.total_funding
    }

    #[getter]
    fn fill_count(&self) -> i64 {
        self.score.fill_count
    }

    #[getter]
    fn event_count(&self) -> i64 {
        self.score.event_count
    }

    #[getter]
    fn rejected_count(&self) -> i64 {
        self.score.rejected_count
    }

    #[getter]
    fn canceled_count(&self) -> i64 {
        self.score.canceled_count
    }

    #[getter]
    fn max_initial_margin(&self) -> f64 {
        self.score.max_initial_margin
    }

    #[getter]
    fn max_maintenance_margin(&self) -> f64 {
        self.score.max_maintenance_margin
    }

    #[getter]
    fn liquidated(&self) -> bool {
        self.score.liquidated
    }

    #[getter]
    fn liquidation_bar(&self) -> i64 {
        self.score.liquidation_bar
    }

    #[getter]
    fn liquidation_reason(&self) -> i64 {
        self.score.liquidation_reason
    }

    #[getter]
    fn metrics(&self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        native_metric_payload(py, &self.score.metrics)
    }

    #[getter]
    fn equity(&self, py: Python<'_>) -> Py<PyArray1<f64>> {
        self.paths.equity.clone_ref(py)
    }

    #[getter]
    fn positions(&self, py: Python<'_>) -> Py<PyArray1<f64>> {
        self.paths.positions.clone_ref(py)
    }

    #[getter]
    fn fees(&self, py: Python<'_>) -> Py<PyArray1<f64>> {
        self.paths.fees.clone_ref(py)
    }

    #[getter]
    fn turnover(&self, py: Python<'_>) -> Py<PyArray1<f64>> {
        self.paths.turnover.clone_ref(py)
    }

    #[getter]
    fn funding(&self, py: Python<'_>) -> Py<PyArray1<f64>> {
        self.paths.funding.clone_ref(py)
    }

    #[getter]
    fn initial_margin(&self, py: Python<'_>) -> Py<PyArray1<f64>> {
        self.paths.initial_margin.clone_ref(py)
    }

    #[getter]
    fn maintenance_margin(&self, py: Python<'_>) -> Py<PyArray1<f64>> {
        self.paths.maintenance_margin.clone_ref(py)
    }

    #[getter]
    fn fill_bar(&self, py: Python<'_>) -> Py<PyArray1<i64>> {
        self.audit.fill_bar.clone_ref(py)
    }

    #[getter]
    fn fill_order_id(&self, py: Python<'_>) -> Py<PyArray1<i64>> {
        self.audit.fill_order_id.clone_ref(py)
    }

    #[getter]
    fn fill_symbol(&self, py: Python<'_>) -> Py<PyArray1<i64>> {
        self.audit.fill_symbol.clone_ref(py)
    }

    #[getter]
    fn fill_side(&self, py: Python<'_>) -> Py<PyArray1<i64>> {
        self.audit.fill_side.clone_ref(py)
    }

    #[getter]
    fn fill_qty(&self, py: Python<'_>) -> Py<PyArray1<f64>> {
        self.audit.fill_qty.clone_ref(py)
    }

    #[getter]
    fn fill_price(&self, py: Python<'_>) -> Py<PyArray1<f64>> {
        self.audit.fill_price.clone_ref(py)
    }

    #[getter]
    fn fill_fee(&self, py: Python<'_>) -> Py<PyArray1<f64>> {
        self.audit.fill_fee.clone_ref(py)
    }

    #[getter]
    fn fill_reason(&self, py: Python<'_>) -> Py<PyArray1<i64>> {
        self.audit.fill_reason.clone_ref(py)
    }

    #[getter]
    fn fill_ambiguity(&self, py: Python<'_>) -> Py<PyArray1<i64>> {
        self.audit.fill_ambiguity.clone_ref(py)
    }

    #[getter]
    fn event_bar(&self, py: Python<'_>) -> Py<PyArray1<i64>> {
        self.audit.event_bar.clone_ref(py)
    }

    #[getter]
    fn event_kind(&self, py: Python<'_>) -> Py<PyArray1<i64>> {
        self.audit.event_kind.clone_ref(py)
    }

    #[getter]
    fn event_status(&self, py: Python<'_>) -> Py<PyArray1<i64>> {
        self.audit.event_status.clone_ref(py)
    }

    #[getter]
    fn event_order_id(&self, py: Python<'_>) -> Py<PyArray1<i64>> {
        self.audit.event_order_id.clone_ref(py)
    }

    #[getter]
    fn event_target_id(&self, py: Python<'_>) -> Py<PyArray1<i64>> {
        self.audit.event_target_id.clone_ref(py)
    }

    #[getter]
    fn event_symbol(&self, py: Python<'_>) -> Py<PyArray1<i64>> {
        self.audit.event_symbol.clone_ref(py)
    }

    #[getter]
    fn event_reject_code(&self, py: Python<'_>) -> Py<PyArray1<i64>> {
        self.audit.event_reject_code.clone_ref(py)
    }

    /// Explicit cold-path compatibility conversion after an audit run.
    fn as_dict(&self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        let payload = PyDict::new(py);
        add_typed_output_metadata(&payload, &self.metadata)?;
        add_score_fields(py, &payload, &self.score)?;
        add_path_fields(py, &payload, &self.paths)?;
        add_audit_fields(py, &payload, &self.audit)?;
        add_native_workload_audit_core_fields(py, &payload, &self.workload_audit)?;
        Ok(payload.unbind())
    }
}

/// Immutable native template for a prepared market plus instrument/account
/// model. The template is output-independent and shares the market through an
/// `Arc`, so static, IR, fold-window, portfolio, and package requests can use
/// one validated native tape without Python dataframe normalization per run.
#[pyclass]
struct NativeExecutionTemplateCore {
    inner: Arc<execution::NativeExecutionTemplateV1>,
}

#[pymethods]
impl NativeExecutionTemplateCore {
    #[classmethod]
    #[pyo3(signature = (
        prepared,
        contract_sizes,
        leverages,
        fee_rates,
        initial_capital,
        maintenance_ratio,
        slippage_rate,
        use_funding,
        event_contract_code=generated_contracts::CONTRACT_EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE,
    ))]
    #[allow(clippy::too_many_arguments)]
    fn from_prepared(
        _cls: &Bound<'_, PyType>,
        py: Python<'_>,
        prepared: Py<FullPreparedMarketCore>,
        contract_sizes: PyReadonlyArray1<'_, f64>,
        leverages: PyReadonlyArray1<'_, f64>,
        fee_rates: PyReadonlyArray1<'_, f64>,
        initial_capital: f64,
        maintenance_ratio: f64,
        slippage_rate: f64,
        use_funding: bool,
        event_contract_code: i64,
    ) -> PyResult<Self> {
        let market = prepared.borrow(py).inner.clone();
        let inner = build_execution_template(
            market,
            contract_sizes.as_slice()?.to_vec(),
            leverages.as_slice()?.to_vec(),
            fee_rates.as_slice()?.to_vec(),
            initial_capital,
            maintenance_ratio,
            slippage_rate,
            use_funding,
            event_contract_code,
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(Self { inner })
    }

    /// Return a zero-copy market window with a fresh local bar clock. The new
    /// template has no mutable account/order state and cannot carry a prior
    /// fold's positions or orders into the next fold.
    fn window(&self, start: usize, end: usize) -> PyResult<Self> {
        self.inner
            .window(start, end)
            .map(|inner| Self {
                inner: Arc::new(inner),
            })
            .map_err(pyo3::exceptions::PyValueError::new_err)
    }

    #[getter]
    fn fingerprint(&self) -> String {
        self.inner.fingerprint_hex()
    }

    #[getter]
    fn bars(&self) -> usize {
        self.inner.bar_count()
    }

    #[getter]
    fn symbols(&self) -> usize {
        self.inner.n_symbols()
    }

    #[getter]
    fn source_market_bytes(&self) -> usize {
        self.inner.source_market_bytes()
    }

    #[getter]
    fn view_bytes(&self) -> usize {
        self.inner.view_bytes()
    }

    #[getter]
    fn market_reference_count(&self) -> usize {
        Arc::strong_count(self.inner.market())
    }

    #[getter]
    fn template_reference_count(&self) -> usize {
        Arc::strong_count(&self.inner)
    }
}

/// Immutable internal ABI-0.5 request. It is intentionally additive to the
/// frozen API-0.4 session classes: old callers keep their array/session
/// signatures, while typed static and IR workloads can reuse one prepared
/// native template and choose either fresh or reusable runner ownership.
#[pyclass]
struct NativeExecutionRequestCore {
    inner: Arc<execution::NativeExecutionRequestV1>,
}

/// Decode one contiguous package-tape slice at the Python/Rust boundary.
///
/// This is intentionally shared by the one-request and scenario-batch
/// constructors so the exact shape, ID, dependency, and enum validation cannot
/// drift between public ABI entries. It creates immutable typed package intent
/// values only; execution/account state is still created by `FullSession`.
#[allow(clippy::too_many_arguments)]
fn decode_package_market_v2_intents(
    command_bars: &[u64],
    package_ids: &[u64],
    package_leg_offsets: &[u64],
    execution_policies: &[u8],
    residual_policies: &[u8],
    max_staleness_ns: &[i64],
    order_ids: &[i64],
    symbol_ids: &[u32],
    signed_qty: &[f64],
    quantity_sources: &[u8],
    source_legs: &[i64],
    quantity_ratios: &[f64],
    fill_fractions: &[f64],
    qty_step: &[f64],
    min_qty: &[f64],
    min_notional: &[f64],
    source_age_ns: &[i64],
    venue_codes: &[u16],
    venue_sequence: &[u32],
) -> Result<Vec<package::PackageIntentV2>, String> {
    let package_count = package_ids.len();
    if package_count == 0
        || command_bars.len() != package_count
        || execution_policies.len() != package_count
        || residual_policies.len() != package_count
        || max_staleness_ns.len() != package_count
        || package_leg_offsets.len() != package_count + 1
        || package_leg_offsets.first() != Some(&0)
    {
        return Err("native package V2 package arrays have an invalid shape".to_owned());
    }
    let leg_count = order_ids.len();
    if package_leg_offsets.last().copied() != Some(leg_count as u64)
        || [
            symbol_ids.len(),
            signed_qty.len(),
            quantity_sources.len(),
            source_legs.len(),
            quantity_ratios.len(),
            fill_fractions.len(),
            qty_step.len(),
            min_qty.len(),
            min_notional.len(),
            source_age_ns.len(),
            venue_codes.len(),
            venue_sequence.len(),
        ]
        .iter()
        .any(|length| *length != leg_count)
    {
        return Err(
            "native package V2 leg arrays must share the declared offset length".to_owned(),
        );
    }
    let mut package_set = std::collections::BTreeSet::new();
    let mut order_set = std::collections::BTreeSet::new();
    let mut intents = Vec::with_capacity(package_count);
    for package_index in 0..package_count {
        let package_id = package_ids[package_index];
        let command_bar = usize::try_from(command_bars[package_index])
            .map_err(|_| "native package V2 command_bar exceeds platform range".to_owned())?;
        if package_id > i64::MAX as u64 || !package_set.insert(package_id) {
            return Err(
                "native package V2 package IDs must be unique and fit canonical group IDs"
                    .to_owned(),
            );
        }
        let start = usize::try_from(package_leg_offsets[package_index])
            .map_err(|_| "native package V2 offset exceeds platform range".to_owned())?;
        let end = usize::try_from(package_leg_offsets[package_index + 1])
            .map_err(|_| "native package V2 offset exceeds platform range".to_owned())?;
        if start >= end || end > leg_count {
            return Err(
                "native package V2 offsets must be increasing non-empty leg ranges".to_owned(),
            );
        }
        let execution_policy =
            package::PackageExecutionPolicyV2::try_from(execution_policies[package_index])?;
        let residual_policy =
            package::ResidualRiskPolicyV1::try_from(residual_policies[package_index])?;
        let mut legs = Vec::with_capacity(end - start);
        for index in start..end {
            if order_ids[index] < 0 || !order_set.insert(order_ids[index]) {
                return Err(
                    "native package V2 order IDs must be unique non-negative values".to_owned(),
                );
            }
            legs.push(package::PackageLegIntentV2 {
                order_id: quantbt_domain::ids::ExternalOrderId(order_ids[index]),
                symbol: quantbt_domain::ids::SymbolId(symbol_ids[index]),
                signed_qty: signed_qty[index],
                quantity_source: package::LegQuantitySourceV1::try_from(quantity_sources[index])?,
                source_leg: source_legs[index],
                quantity_ratio: quantity_ratios[index],
                fill_fraction: fill_fractions[index],
                qty_step: qty_step[index],
                min_qty: min_qty[index],
                min_notional: min_notional[index],
                source_age_ns: source_age_ns[index],
                venue_code: venue_codes[index],
                venue_sequence: venue_sequence[index],
            });
        }
        intents.push(package::PackageIntentV2 {
            package_id: package::PackageId(package_id),
            command_bar,
            execution_policy,
            residual_policy,
            legs: legs.into_boxed_slice(),
            max_staleness_ns: max_staleness_ns[package_index],
        });
    }
    Ok(intents)
}

#[pymethods]
impl NativeExecutionRequestCore {
    /// Construct a typed request from the legacy flat ABI at the compatibility
    /// ingress.  The arrays are translated once to `CommandTapeV5`; the
    /// mutable lifecycle/account state is not created until `execute()`.
    #[classmethod]
    #[pyo3(signature = (
        prepared,
        command_ptr,
        command_codes,
        command_values,
        command_expiry,
        contract_sizes,
        leverages,
        fee_rates,
        initial_capital,
        maintenance_ratio,
        slippage_rate,
        use_funding,
        event_contract_code=generated_contracts::CONTRACT_EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE,
        output_profile=0,
    ))]
    #[allow(clippy::too_many_arguments)]
    fn from_command_tape(
        _cls: &Bound<'_, PyType>,
        py: Python<'_>,
        prepared: Py<FullPreparedMarketCore>,
        command_ptr: PyReadonlyArray1<'_, i64>,
        command_codes: PyReadonlyArray2<'_, i64>,
        command_values: PyReadonlyArray2<'_, f64>,
        command_expiry: PyReadonlyArray1<'_, i64>,
        contract_sizes: PyReadonlyArray1<'_, f64>,
        leverages: PyReadonlyArray1<'_, f64>,
        fee_rates: PyReadonlyArray1<'_, f64>,
        initial_capital: f64,
        maintenance_ratio: f64,
        slippage_rate: f64,
        use_funding: bool,
        event_contract_code: i64,
        output_profile: u8,
    ) -> PyResult<Self> {
        let market = prepared.borrow(py).inner.clone();
        let inner = build_command_request(
            market,
            command_ptr.as_slice()?,
            command_codes.as_slice()?,
            command_codes.shape(),
            command_values.as_slice()?,
            command_values.shape(),
            command_expiry.as_slice()?,
            contract_sizes.as_slice()?.to_vec(),
            leverages.as_slice()?.to_vec(),
            fee_rates.as_slice()?.to_vec(),
            initial_capital,
            maintenance_ratio,
            slippage_rate,
            use_funding,
            event_contract_code,
            output_profile,
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(Self {
            inner: Arc::new(inner),
        })
    }

    /// Build an immutable command request from an already validated native
    /// template. This is the prepared ingress for repeated static runs: market
    /// and account/instrument tables are not rebuilt, while the command tape
    /// remains part of the request fingerprint.
    #[classmethod]
    #[pyo3(signature = (
        template,
        command_ptr,
        command_codes,
        command_values,
        command_expiry,
        output_profile=0,
    ))]
    #[allow(clippy::too_many_arguments)]
    fn from_template_command_tape(
        _cls: &Bound<'_, PyType>,
        py: Python<'_>,
        template: Py<NativeExecutionTemplateCore>,
        command_ptr: PyReadonlyArray1<'_, i64>,
        command_codes: PyReadonlyArray2<'_, i64>,
        command_values: PyReadonlyArray2<'_, f64>,
        command_expiry: PyReadonlyArray1<'_, i64>,
        output_profile: u8,
    ) -> PyResult<Self> {
        let template = template.borrow(py).inner.clone();
        let inner = build_command_request_from_template(
            template,
            command_ptr.as_slice()?,
            command_codes.as_slice()?,
            command_codes.shape(),
            command_values.as_slice()?,
            command_values.shape(),
            command_expiry.as_slice()?,
            output_profile,
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(Self {
            inner: Arc::new(inner),
        })
    }

    /// Build a one-call native strategy-IR request.  The signal/parameter
    /// buffers are copied into immutable Rust ownership during construction;
    /// `execute()` has no Python callback or per-bar boundary.
    #[classmethod]
    #[pyo3(signature = (
        prepared,
        program,
        signal,
        contract_sizes,
        leverages,
        fee_rates,
        initial_capital,
        maintenance_ratio,
        slippage_rate,
        use_funding,
        parameters=None,
        event_contract_code=generated_contracts::CONTRACT_EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE,
        output_profile=0,
    ))]
    #[allow(clippy::too_many_arguments)]
    fn from_strategy_ir(
        _cls: &Bound<'_, PyType>,
        py: Python<'_>,
        prepared: Py<FullPreparedMarketCore>,
        program: PyRef<'_, NativeStrategyProgramCore>,
        signal: PyReadonlyArray1<'_, f64>,
        contract_sizes: PyReadonlyArray1<'_, f64>,
        leverages: PyReadonlyArray1<'_, f64>,
        fee_rates: PyReadonlyArray1<'_, f64>,
        initial_capital: f64,
        maintenance_ratio: f64,
        slippage_rate: f64,
        use_funding: bool,
        parameters: Option<PyReadonlyArray1<'_, f64>>,
        event_contract_code: i64,
        output_profile: u8,
    ) -> PyResult<Self> {
        let market = prepared.borrow(py).inner.clone();
        let instruments = execution::InstrumentTableV1::sequential(
            contract_sizes.as_slice()?.to_vec(),
            leverages.as_slice()?.to_vec(),
            fee_rates.as_slice()?.to_vec(),
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let account = execution::AccountModelV1::new(
            initial_capital,
            maintenance_ratio,
            slippage_rate,
            use_funding,
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let contract = execution::ExecutionContractV1::new(event_contract_code)
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let output = execution::NativeOutputProfileV1::try_from(output_profile)
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let inner = execution::NativeExecutionRequestV1::from_strategy_ir(
            market,
            instruments,
            account,
            contract,
            output,
            program.inner.clone(),
            signal.as_slice()?.to_vec(),
            parameters
                .map(|values| values.as_slice().map(|slice| slice.to_vec()))
                .transpose()?,
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(Self {
            inner: Arc::new(inner),
        })
    }

    /// Build a one-call strategy-IR request from an existing native template.
    /// Signal and optional parameter vectors are copied once into immutable
    /// Rust-owned request storage; market/account/instrument ownership is
    /// reused from the template.
    #[classmethod]
    #[pyo3(signature = (
        template,
        program,
        signal,
        parameters=None,
        output_profile=0,
    ))]
    fn from_template_strategy_ir(
        _cls: &Bound<'_, PyType>,
        py: Python<'_>,
        template: Py<NativeExecutionTemplateCore>,
        program: PyRef<'_, NativeStrategyProgramCore>,
        signal: PyReadonlyArray1<'_, f64>,
        parameters: Option<PyReadonlyArray1<'_, f64>>,
        output_profile: u8,
    ) -> PyResult<Self> {
        let template = template.borrow(py).inner.clone();
        let output = execution::NativeOutputProfileV1::try_from(output_profile)
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let inner = execution::NativeExecutionRequestV1::from_strategy_ir_template(
            template,
            output,
            program.inner.clone(),
            signal.as_slice()?.to_vec(),
            parameters
                .map(|values| values.as_slice().map(|slice| slice.to_vec()))
                .transpose()?,
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(Self {
            inner: Arc::new(inner),
        })
    }

    /// Build a bounded multi-symbol target-units request that resolves target
    /// acceptance and canonical market commands inside Rust for every bar.
    ///
    /// The route is intentionally narrow: V2 next-bar-close, linear quote
    /// settled gross-cross account semantics, target units, and all-or-none
    /// rebalance acceptance. Research allocation remains outside the engine.
    #[classmethod]
    #[pyo3(signature = (
        template,
        target_units,
        tradable,
        stale,
        min_qty,
        min_notional,
        external_id_start=1,
        output_profile=2,
    ))]
    #[allow(clippy::too_many_arguments)]
    fn from_template_portfolio_target_market(
        _cls: &Bound<'_, PyType>,
        py: Python<'_>,
        template: Py<NativeExecutionTemplateCore>,
        target_units: PyReadonlyArray2<'_, f64>,
        tradable: PyReadonlyArray2<'_, bool>,
        stale: PyReadonlyArray2<'_, bool>,
        min_qty: PyReadonlyArray1<'_, f64>,
        min_notional: PyReadonlyArray1<'_, f64>,
        external_id_start: i64,
        output_profile: u8,
    ) -> PyResult<Self> {
        let template = template.borrow(py).inner.clone();
        let target_shape = target_units.shape();
        let flag_shape = tradable.shape();
        let stale_shape = stale.shape();
        if target_shape != [template.bar_count(), template.n_symbols()]
            || flag_shape != target_shape
            || stale_shape != target_shape
            || min_qty.len() != template.n_symbols()
            || min_notional.len() != template.n_symbols()
        {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "portfolio target market arrays must match template (bars, symbols)",
            ));
        }
        let output = execution::NativeOutputProfileV1::try_from(output_profile)
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let inner = execution::NativeExecutionRequestV1::from_template_portfolio_target_market(
            template,
            output,
            target_units.as_slice()?.to_vec(),
            tradable.as_slice()?.to_vec(),
            stale.as_slice()?.to_vec(),
            min_qty.as_slice()?.to_vec(),
            min_notional.as_slice()?.to_vec(),
            external_id_start,
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(Self {
            inner: Arc::new(inner),
        })
    }

    /// Build one Rust-owned same-bar atomic package request.  The output
    /// records a bar-transaction audit; it never claims exchange-native OCO,
    /// partial-fill, queue, or cross-venue settlement semantics.
    #[classmethod]
    #[pyo3(signature = (
        template,
        command_bar,
        package_id,
        order_ids,
        symbol_ids,
        signed_qty,
        source_age_ns,
        venue_codes,
        venue_sequence,
        min_qty,
        min_notional,
        max_staleness_ns=0,
        output_profile=2,
    ))]
    #[allow(clippy::too_many_arguments)]
    fn from_template_package_atomic_market(
        _cls: &Bound<'_, PyType>,
        py: Python<'_>,
        template: Py<NativeExecutionTemplateCore>,
        command_bar: usize,
        package_id: u64,
        order_ids: PyReadonlyArray1<'_, i64>,
        symbol_ids: PyReadonlyArray1<'_, u32>,
        signed_qty: PyReadonlyArray1<'_, f64>,
        source_age_ns: PyReadonlyArray1<'_, i64>,
        venue_codes: PyReadonlyArray1<'_, u16>,
        venue_sequence: PyReadonlyArray1<'_, u32>,
        min_qty: PyReadonlyArray1<'_, f64>,
        min_notional: PyReadonlyArray1<'_, f64>,
        max_staleness_ns: i64,
        output_profile: u8,
    ) -> PyResult<Self> {
        let template = template.borrow(py).inner.clone();
        let order_ids = order_ids.as_slice()?;
        let symbol_ids = symbol_ids.as_slice()?;
        let signed_qty = signed_qty.as_slice()?;
        let source_age_ns = source_age_ns.as_slice()?;
        let venue_codes = venue_codes.as_slice()?;
        let venue_sequence = venue_sequence.as_slice()?;
        let min_qty = min_qty.as_slice()?;
        let min_notional = min_notional.as_slice()?;
        let count = order_ids.len();
        if count == 0
            || [
                symbol_ids.len(),
                signed_qty.len(),
                source_age_ns.len(),
                venue_codes.len(),
                venue_sequence.len(),
                min_qty.len(),
                min_notional.len(),
            ]
            .iter()
            .any(|length| *length != count)
        {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "native atomic package arrays must be non-empty and equal length",
            ));
        }
        let legs = (0..count)
            .map(|index| package::PackageLegRequest {
                order_id: quantbt_domain::ids::ExternalOrderId(order_ids[index]),
                symbol: quantbt_domain::ids::SymbolId(symbol_ids[index]),
                signed_qty: signed_qty[index],
                // Dynamic execution replaces these planner placeholders with
                // the prepared market/account values at command_bar.
                price: 1.0,
                initial_margin: 0.0,
                fee_rate: 0.0,
                source_age_ns: source_age_ns[index],
                venue_code: venue_codes[index],
                venue_sequence: venue_sequence[index],
                min_qty: min_qty[index],
                min_notional: min_notional[index],
                contract_size: 1.0,
            })
            .collect::<Vec<_>>();
        let plan = package::PackagePlan {
            id: package::PackageId(package_id),
            policy: package::PackagePolicy::AtomicBarSimulation,
            legs: order_ids
                .iter()
                .copied()
                .map(|order_id| package::PackageLegRef {
                    order_id: quantbt_domain::ids::ExternalOrderId(order_id),
                })
                .collect::<Vec<_>>()
                .into_boxed_slice(),
        };
        let output = execution::NativeOutputProfileV1::try_from(output_profile)
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let inner = execution::NativeExecutionRequestV1::from_template_package_atomic_market(
            template,
            output,
            plan,
            legs,
            command_bar,
            max_staleness_ns,
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(Self {
            inner: Arc::new(inner),
        })
    }

    /// Build an immutable bounded same-account package V2 request.  One
    /// package is declared per command bar and every leg is represented in
    /// typed, contiguous arrays. `fill_fractions` are explicit deterministic
    /// scenario inputs, not an order-book/liquidity claim; actual command
    /// quantities are calculated by Rust and committed by the shared session.
    #[classmethod]
    #[pyo3(signature = (
        template,
        command_bars,
        package_ids,
        package_leg_offsets,
        execution_policies,
        residual_policies,
        max_staleness_ns,
        order_ids,
        symbol_ids,
        signed_qty,
        quantity_sources,
        source_legs,
        quantity_ratios,
        fill_fractions,
        qty_step,
        min_qty,
        min_notional,
        source_age_ns,
        venue_codes,
        venue_sequence,
        output_profile=2,
    ))]
    #[allow(clippy::too_many_arguments)]
    fn from_template_package_market_v2(
        _cls: &Bound<'_, PyType>,
        py: Python<'_>,
        template: Py<NativeExecutionTemplateCore>,
        command_bars: PyReadonlyArray1<'_, u64>,
        package_ids: PyReadonlyArray1<'_, u64>,
        package_leg_offsets: PyReadonlyArray1<'_, u64>,
        execution_policies: PyReadonlyArray1<'_, u8>,
        residual_policies: PyReadonlyArray1<'_, u8>,
        max_staleness_ns: PyReadonlyArray1<'_, i64>,
        order_ids: PyReadonlyArray1<'_, i64>,
        symbol_ids: PyReadonlyArray1<'_, u32>,
        signed_qty: PyReadonlyArray1<'_, f64>,
        quantity_sources: PyReadonlyArray1<'_, u8>,
        source_legs: PyReadonlyArray1<'_, i64>,
        quantity_ratios: PyReadonlyArray1<'_, f64>,
        fill_fractions: PyReadonlyArray1<'_, f64>,
        qty_step: PyReadonlyArray1<'_, f64>,
        min_qty: PyReadonlyArray1<'_, f64>,
        min_notional: PyReadonlyArray1<'_, f64>,
        source_age_ns: PyReadonlyArray1<'_, i64>,
        venue_codes: PyReadonlyArray1<'_, u16>,
        venue_sequence: PyReadonlyArray1<'_, u32>,
        output_profile: u8,
    ) -> PyResult<Self> {
        let template = template.borrow(py).inner.clone();
        let command_bars = command_bars.as_slice()?;
        let package_ids = package_ids.as_slice()?;
        let package_leg_offsets = package_leg_offsets.as_slice()?;
        let execution_policies = execution_policies.as_slice()?;
        let residual_policies = residual_policies.as_slice()?;
        let max_staleness_ns = max_staleness_ns.as_slice()?;
        let order_ids = order_ids.as_slice()?;
        let symbol_ids = symbol_ids.as_slice()?;
        let signed_qty = signed_qty.as_slice()?;
        let quantity_sources = quantity_sources.as_slice()?;
        let source_legs = source_legs.as_slice()?;
        let quantity_ratios = quantity_ratios.as_slice()?;
        let fill_fractions = fill_fractions.as_slice()?;
        let qty_step = qty_step.as_slice()?;
        let min_qty = min_qty.as_slice()?;
        let min_notional = min_notional.as_slice()?;
        let source_age_ns = source_age_ns.as_slice()?;
        let venue_codes = venue_codes.as_slice()?;
        let venue_sequence = venue_sequence.as_slice()?;
        let intents = decode_package_market_v2_intents(
            command_bars,
            package_ids,
            package_leg_offsets,
            execution_policies,
            residual_policies,
            max_staleness_ns,
            order_ids,
            symbol_ids,
            signed_qty,
            quantity_sources,
            source_legs,
            quantity_ratios,
            fill_fractions,
            qty_step,
            min_qty,
            min_notional,
            source_age_ns,
            venue_codes,
            venue_sequence,
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let output = execution::NativeOutputProfileV1::try_from(output_profile)
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let inner = execution::NativeExecutionRequestV1::from_template_package_market_v2(
            template, output, intents,
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(Self {
            inner: Arc::new(inner),
        })
    }

    #[getter]
    fn request_version(&self) -> u16 {
        self.inner.request_version()
    }

    #[getter]
    fn protocol_version(&self) -> u16 {
        self.inner.protocol_version()
    }

    #[getter]
    fn fingerprint(&self) -> String {
        self.inner.fingerprint_hex()
    }

    #[getter]
    fn template_fingerprint(&self) -> String {
        self.inner.template().fingerprint_hex()
    }

    #[getter]
    fn workload_kind(&self) -> &'static str {
        self.inner.workload_kind().name()
    }

    #[getter]
    fn output_profile(&self) -> &'static str {
        self.inner.output_profile().name()
    }

    /// Return a new immutable audit request with a bounded combined fill/event
    /// retention budget. This affects only audit artifact retention and is
    /// fingerprinted; score/compact requests reject it explicitly.
    fn with_audit_detail_limit(&self, detail_row_limit: usize) -> PyResult<Self> {
        let inner = self
            .inner
            .as_ref()
            .clone()
            .with_audit_detail_limit(detail_row_limit)
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(Self {
            inner: Arc::new(inner),
        })
    }

    #[getter]
    fn audit_detail_row_limit(&self) -> Option<usize> {
        self.inner.audit_detail_row_limit()
    }

    #[getter]
    fn command_count(&self) -> usize {
        self.inner.command_count()
    }

    #[getter]
    fn bars(&self) -> usize {
        self.inner.template().bar_count()
    }

    #[getter]
    fn prepared_market_bytes(&self) -> usize {
        self.inner.template().source_market_bytes()
    }

    #[getter]
    fn prepared_view_bytes(&self) -> usize {
        self.inner.template().view_bytes()
    }

    /// Execute the immutable request through the typed output route. One
    /// Rust-only pass produces a score, compact, or audit object according to
    /// the request profile; no Python dictionary, DataFrame, or replay is
    /// required for the execution itself.
    fn execute_typed(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let request = self.inner.clone();
        let result = py
            .detach(move || request.execute())
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        native_request_typed_output(py, result)
    }

    /// API-0.5 compatibility adapter. The authoritative Rust result is first
    /// produced once, then moved into the historical dictionary shape for
    /// callers that have not migrated to `execute_typed()`.
    fn execute(&self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        let request = self.inner.clone();
        let result = py
            .detach(move || request.execute())
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        native_request_output_payload(py, result)
    }

    /// Open a reusable Rust-owned runner for repeated independent scenarios.
    /// The runner resets account/orders before every execution and does not
    /// share mutable state with this immutable request or other runners.
    fn new_runner(&self) -> PyResult<NativeExecutionRunnerCore> {
        let runner = self
            .inner
            .new_runner()
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(NativeExecutionRunnerCore {
            request: self.inner.as_ref().clone(),
            runner: Some(runner),
            boundary_calls: 0,
            full_rebuilds: 0,
            closed: false,
        })
    }
}

/// Prepared scalar-only package scenario batch.  It accepts fully typed V2
/// package tapes and performs all independent runs under one Python-to-Rust
/// boundary. It intentionally exposes score rows only; a chosen scenario is
/// rerun through `NativeExecutionRequestCore` in audit profile for leg detail.
#[pyclass]
struct NativePackageScenarioBatchCore {
    inner: execution::package::PackageScenarioBatchV2,
}

#[pymethods]
impl NativePackageScenarioBatchCore {
    #[classmethod]
    #[pyo3(signature = (
        template,
        scenario_package_offsets,
        command_bars,
        package_ids,
        package_leg_offsets,
        execution_policies,
        residual_policies,
        max_staleness_ns,
        order_ids,
        symbol_ids,
        signed_qty,
        quantity_sources,
        source_legs,
        quantity_ratios,
        fill_fractions,
        qty_step,
        min_qty,
        min_notional,
        source_age_ns,
        venue_codes,
        venue_sequence,
    ))]
    #[allow(clippy::too_many_arguments)]
    fn from_template_v2(
        _cls: &Bound<'_, PyType>,
        py: Python<'_>,
        template: Py<NativeExecutionTemplateCore>,
        scenario_package_offsets: PyReadonlyArray1<'_, u64>,
        command_bars: PyReadonlyArray1<'_, u64>,
        package_ids: PyReadonlyArray1<'_, u64>,
        package_leg_offsets: PyReadonlyArray1<'_, u64>,
        execution_policies: PyReadonlyArray1<'_, u8>,
        residual_policies: PyReadonlyArray1<'_, u8>,
        max_staleness_ns: PyReadonlyArray1<'_, i64>,
        order_ids: PyReadonlyArray1<'_, i64>,
        symbol_ids: PyReadonlyArray1<'_, u32>,
        signed_qty: PyReadonlyArray1<'_, f64>,
        quantity_sources: PyReadonlyArray1<'_, u8>,
        source_legs: PyReadonlyArray1<'_, i64>,
        quantity_ratios: PyReadonlyArray1<'_, f64>,
        fill_fractions: PyReadonlyArray1<'_, f64>,
        qty_step: PyReadonlyArray1<'_, f64>,
        min_qty: PyReadonlyArray1<'_, f64>,
        min_notional: PyReadonlyArray1<'_, f64>,
        source_age_ns: PyReadonlyArray1<'_, i64>,
        venue_codes: PyReadonlyArray1<'_, u16>,
        venue_sequence: PyReadonlyArray1<'_, u32>,
    ) -> PyResult<Self> {
        let template = template.borrow(py).inner.clone();
        let scenario_package_offsets = scenario_package_offsets.as_slice()?;
        let command_bars = command_bars.as_slice()?;
        let package_ids = package_ids.as_slice()?;
        let package_leg_offsets = package_leg_offsets.as_slice()?;
        let execution_policies = execution_policies.as_slice()?;
        let residual_policies = residual_policies.as_slice()?;
        let max_staleness_ns = max_staleness_ns.as_slice()?;
        let order_ids = order_ids.as_slice()?;
        let symbol_ids = symbol_ids.as_slice()?;
        let signed_qty = signed_qty.as_slice()?;
        let quantity_sources = quantity_sources.as_slice()?;
        let source_legs = source_legs.as_slice()?;
        let quantity_ratios = quantity_ratios.as_slice()?;
        let fill_fractions = fill_fractions.as_slice()?;
        let qty_step = qty_step.as_slice()?;
        let min_qty = min_qty.as_slice()?;
        let min_notional = min_notional.as_slice()?;
        let source_age_ns = source_age_ns.as_slice()?;
        let venue_codes = venue_codes.as_slice()?;
        let venue_sequence = venue_sequence.as_slice()?;
        let package_count = package_ids.len();
        let leg_count = order_ids.len();
        if scenario_package_offsets.len() < 2
            || scenario_package_offsets.first() != Some(&0)
            || scenario_package_offsets.last().copied() != Some(package_count as u64)
            || package_leg_offsets.len() != package_count + 1
            || package_leg_offsets.first() != Some(&0)
            || package_leg_offsets.last().copied() != Some(leg_count as u64)
            || [
                command_bars.len(),
                execution_policies.len(),
                residual_policies.len(),
                max_staleness_ns.len(),
            ]
            .iter()
            .any(|length| *length != package_count)
            || [
                symbol_ids.len(),
                signed_qty.len(),
                quantity_sources.len(),
                source_legs.len(),
                quantity_ratios.len(),
                fill_fractions.len(),
                qty_step.len(),
                min_qty.len(),
                min_notional.len(),
                source_age_ns.len(),
                venue_codes.len(),
                venue_sequence.len(),
            ]
            .iter()
            .any(|length| *length != leg_count)
        {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "native package V2 scenario batch arrays have an invalid shape",
            ));
        }
        let mut scenarios = Vec::with_capacity(scenario_package_offsets.len() - 1);
        for scenario_index in 0..scenario_package_offsets.len() - 1 {
            let package_start =
                usize::try_from(scenario_package_offsets[scenario_index]).map_err(|_| {
                    pyo3::exceptions::PyValueError::new_err(
                        "native package V2 scenario package offset exceeds platform range",
                    )
                })?;
            let package_end = usize::try_from(scenario_package_offsets[scenario_index + 1])
                .map_err(|_| {
                    pyo3::exceptions::PyValueError::new_err(
                        "native package V2 scenario package offset exceeds platform range",
                    )
                })?;
            if package_start >= package_end || package_end > package_count {
                return Err(pyo3::exceptions::PyValueError::new_err(
                    "native package V2 scenario offsets must select non-empty package ranges",
                ));
            }
            let leg_start = usize::try_from(package_leg_offsets[package_start]).map_err(|_| {
                pyo3::exceptions::PyValueError::new_err(
                    "native package V2 scenario leg offset exceeds platform range",
                )
            })?;
            let leg_end = usize::try_from(package_leg_offsets[package_end]).map_err(|_| {
                pyo3::exceptions::PyValueError::new_err(
                    "native package V2 scenario leg offset exceeds platform range",
                )
            })?;
            if leg_start >= leg_end || leg_end > leg_count {
                return Err(pyo3::exceptions::PyValueError::new_err(
                    "native package V2 scenario offsets select an invalid leg range",
                ));
            }
            let local_offsets = package_leg_offsets[package_start..=package_end]
                .iter()
                .map(|offset| {
                    offset.checked_sub(leg_start as u64).ok_or_else(|| {
                        pyo3::exceptions::PyValueError::new_err(
                            "native package V2 scenario leg offsets are not monotonic",
                        )
                    })
                })
                .collect::<PyResult<Vec<_>>>()?;
            let intents = decode_package_market_v2_intents(
                &command_bars[package_start..package_end],
                &package_ids[package_start..package_end],
                &local_offsets,
                &execution_policies[package_start..package_end],
                &residual_policies[package_start..package_end],
                &max_staleness_ns[package_start..package_end],
                &order_ids[leg_start..leg_end],
                &symbol_ids[leg_start..leg_end],
                &signed_qty[leg_start..leg_end],
                &quantity_sources[leg_start..leg_end],
                &source_legs[leg_start..leg_end],
                &quantity_ratios[leg_start..leg_end],
                &fill_fractions[leg_start..leg_end],
                &qty_step[leg_start..leg_end],
                &min_qty[leg_start..leg_end],
                &min_notional[leg_start..leg_end],
                &source_age_ns[leg_start..leg_end],
                &venue_codes[leg_start..leg_end],
                &venue_sequence[leg_start..leg_end],
            )
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
            scenarios.push(intents);
        }
        let inner = execution::package::PackageScenarioBatchV2::new(template, scenarios)
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(Self { inner })
    }

    #[getter]
    fn scenario_count(&self) -> usize {
        self.inner.scenario_count()
    }

    /// Execute independent score-only scenarios under one PyO3 entry. The
    /// returned columns are flat numeric arrays; detailed package provenance
    /// remains an explicit selected-scenario audit rerun.
    fn execute(&self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        let batch = self.inner.clone();
        let output = py
            .detach(move || batch.score())
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let payload = PyDict::new(py);
        let rows = output.rows;
        payload.set_item(
            "scenario_id",
            PyArray1::from_vec(py, rows.iter().map(|row| row.scenario_id).collect()),
        )?;
        payload.set_item(
            "final_equity",
            PyArray1::from_vec(py, rows.iter().map(|row| row.final_equity).collect()),
        )?;
        payload.set_item(
            "total_fee",
            PyArray1::from_vec(py, rows.iter().map(|row| row.total_fee).collect()),
        )?;
        payload.set_item(
            "total_funding",
            PyArray1::from_vec(py, rows.iter().map(|row| row.total_funding).collect()),
        )?;
        payload.set_item(
            "total_turnover",
            PyArray1::from_vec(py, rows.iter().map(|row| row.total_turnover).collect()),
        )?;
        payload.set_item(
            "fill_count",
            PyArray1::from_vec(py, rows.iter().map(|row| row.fill_count).collect()),
        )?;
        payload.set_item(
            "rejected_count",
            PyArray1::from_vec(py, rows.iter().map(|row| row.rejected_count).collect()),
        )?;
        payload.set_item(
            "liquidated",
            PyArray1::from_vec(py, rows.iter().map(|row| row.liquidated).collect()),
        )?;
        payload.set_item(
            "package_count",
            PyArray1::from_vec(
                py,
                rows.iter().map(|row| row.package_count as u64).collect(),
            ),
        )?;
        payload.set_item(
            "accepted_package_count",
            PyArray1::from_vec(
                py,
                rows.iter()
                    .map(|row| row.accepted_package_count as u64)
                    .collect(),
            ),
        )?;
        payload.set_item(
            "residual_package_count",
            PyArray1::from_vec(
                py,
                rows.iter()
                    .map(|row| row.residual_package_count as u64)
                    .collect(),
            ),
        )?;
        payload.set_item(
            "residual_gross_notional_total",
            PyArray1::from_vec(
                py,
                rows.iter()
                    .map(|row| row.residual_gross_notional_total)
                    .collect(),
            ),
        )?;
        payload.set_item(
            "outstanding_residual_gross_notional_total",
            PyArray1::from_vec(
                py,
                rows.iter()
                    .map(|row| row.outstanding_residual_gross_notional_total)
                    .collect(),
            ),
        )?;
        let mut terminal_fingerprint = Vec::with_capacity(rows.len() * 32);
        let mut request_fingerprint = Vec::with_capacity(rows.len() * 32);
        for row in &rows {
            terminal_fingerprint.extend_from_slice(&row.terminal_fingerprint);
            request_fingerprint.extend_from_slice(&row.request_fingerprint);
        }
        payload.set_item(
            "terminal_fingerprint_bytes",
            PyArray1::from_vec(py, terminal_fingerprint),
        )?;
        payload.set_item(
            "request_fingerprint_bytes",
            PyArray1::from_vec(py, request_fingerprint),
        )?;
        payload.set_item("fingerprint_width", 32_usize)?;
        payload.set_item("worker_count", output.worker_count)?;
        payload.set_item("native_entry_calls", output.native_entry_calls)?;
        payload.set_item("market_copy_bytes", output.market_copy_bytes)?;
        Ok(payload.unbind())
    }
}

/// Immutable direct close-target request for the Rust vectorized authority.
///
/// Unlike ``NativeExecutionRequestCore``, this route never creates a
/// ``CommandTapeV5`` or an order arena.  It owns a bar-major target matrix and
/// resolves ``target -> quantized units -> delta -> account`` in one Rust pass
/// under the independently frozen ``close_target_v2_same_close`` contract.
#[pyclass]
struct NativeTargetExecutionRequestCore {
    inner: Arc<execution::target::DirectTargetRequestV1>,
}

#[pymethods]
impl NativeTargetExecutionRequestCore {
    #[classmethod]
    #[pyo3(signature = (
        template,
        targets,
        target_kind=0,
        timing=execution::target::TARGET_TIMING_CLOSE_TARGET_V2_SAME_CLOSE,
        invalid_target_policy=0,
        tradable=None,
        stale=None,
        qty_step=None,
        min_qty=None,
        min_notional=None,
        equity_fraction=None,
        output_profile=0,
    ))]
    #[allow(clippy::too_many_arguments)]
    fn from_template(
        _cls: &Bound<'_, PyType>,
        py: Python<'_>,
        template: Py<NativeExecutionTemplateCore>,
        targets: PyReadonlyArray2<'_, f64>,
        target_kind: u8,
        timing: u8,
        invalid_target_policy: u8,
        tradable: Option<PyReadonlyArray2<'_, bool>>,
        stale: Option<PyReadonlyArray2<'_, bool>>,
        qty_step: Option<PyReadonlyArray1<'_, f64>>,
        min_qty: Option<PyReadonlyArray1<'_, f64>>,
        min_notional: Option<PyReadonlyArray1<'_, f64>>,
        equity_fraction: Option<PyReadonlyArray1<'_, f64>>,
        output_profile: u8,
    ) -> PyResult<Self> {
        let template = template.borrow(py).inner.clone();
        let expected_shape = [template.bar_count(), template.n_symbols()];
        if targets.shape() != expected_shape {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "native direct target values must match template (bars, symbols)",
            ));
        }
        let width = expected_shape[0]
            .checked_mul(expected_shape[1])
            .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("target dimensions overflow"))?;
        let target_values = targets.as_slice()?.to_vec();
        let tradable_values = if let Some(values) = tradable {
            if values.shape() != expected_shape {
                return Err(pyo3::exceptions::PyValueError::new_err(
                    "native direct target tradable mask must match target shape",
                ));
            }
            values.as_slice()?.to_vec()
        } else {
            vec![true; width]
        };
        let stale_values = if let Some(values) = stale {
            if values.shape() != expected_shape {
                return Err(pyo3::exceptions::PyValueError::new_err(
                    "native direct target stale mask must match target shape",
                ));
            }
            values.as_slice()?.to_vec()
        } else {
            vec![false; width]
        };
        let vector_or_default = |values: Option<PyReadonlyArray1<'_, f64>>,
                                 default: f64,
                                 name: &str|
         -> PyResult<Vec<f64>> {
            match values {
                Some(values) => {
                    if values.len() != expected_shape[1] {
                        return Err(pyo3::exceptions::PyValueError::new_err(format!(
                            "native direct target {name} length must match template symbols"
                        )));
                    }
                    Ok(values.as_slice()?.to_vec())
                }
                None => Ok(vec![default; expected_shape[1]]),
            }
        };
        let qty_step_values = vector_or_default(qty_step, 0.0, "qty_step")?;
        let min_qty_values = vector_or_default(min_qty, 0.0, "min_qty")?;
        let min_notional_values = vector_or_default(min_notional, 0.0, "min_notional")?;
        let equity_fraction_values = vector_or_default(equity_fraction, 1.0, "equity_fraction")?;
        let kind = execution::target::DirectTargetKindV1::try_from(target_kind)
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let policy = execution::target::InvalidTargetPolicyV1::try_from(invalid_target_policy)
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let output = execution::NativeOutputProfileV1::try_from(output_profile)
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let inner = execution::target::DirectTargetRequestV1::from_template(
            template,
            target_values,
            kind,
            timing,
            policy,
            tradable_values,
            stale_values,
            qty_step_values,
            min_qty_values,
            min_notional_values,
            equity_fraction_values,
            output,
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(Self {
            inner: Arc::new(inner),
        })
    }

    #[getter]
    fn request_version(&self) -> u16 {
        execution::target::DIRECT_TARGET_REQUEST_VERSION_V1
    }

    #[getter]
    fn fingerprint(&self) -> String {
        self.inner.fingerprint_hex()
    }

    #[getter]
    fn template_fingerprint(&self) -> String {
        self.inner.template().fingerprint_hex()
    }

    #[getter]
    fn target_kind(&self) -> &'static str {
        self.inner.kind().name()
    }

    #[getter]
    fn timing(&self) -> u8 {
        self.inner.timing()
    }

    #[getter]
    fn invalid_target_policy(&self) -> &'static str {
        self.inner.invalid_target_policy().name()
    }

    #[getter]
    fn output_profile(&self) -> &'static str {
        self.inner.output_profile().name()
    }

    #[getter]
    fn bars(&self) -> usize {
        self.inner.template().bar_count()
    }

    #[getter]
    fn symbols(&self) -> usize {
        self.inner.template().n_symbols()
    }

    #[getter]
    fn request_bytes(&self) -> usize {
        self.inner.request_bytes()
    }

    #[getter]
    fn native_target_no_order_arena(&self) -> bool {
        true
    }

    fn with_audit_detail_limit(&self, detail_row_limit: usize) -> PyResult<Self> {
        let inner = self
            .inner
            .as_ref()
            .clone()
            .with_audit_detail_limit(detail_row_limit)
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(Self {
            inner: Arc::new(inner),
        })
    }

    /// One detached Rust pass with no generic command tape, per-bar Python
    /// callback, or Python-side accounting replay.
    fn execute_typed(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let request = self.inner.clone();
        let result = py
            .detach(move || request.execute())
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        direct_target_typed_output(py, result)
    }

    /// Explicit cold-path dictionary adaptation after the authoritative direct
    /// target pass. The adapter never reconstructs fills or reruns execution.
    fn execute(&self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        let request = self.inner.clone();
        let result = py
            .detach(move || request.execute())
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        direct_target_output_payload(py, result)
    }
}

/// Immutable direct target request for a linear multi-symbol portfolio that
/// shares one Rust-owned account.  This is intentionally distinct from the
/// legacy ``NativeExecutionRequestCore`` portfolio preflight route: target
/// planning stays in Python, while admission, fills, costs, funding, margin,
/// liquidation, and attribution execute together in one native pass.
#[pyclass]
struct NativeSharedPortfolioTargetRequestCore {
    inner: Arc<execution::target::SharedPortfolioTargetRequestV1>,
}

#[pymethods]
impl NativeSharedPortfolioTargetRequestCore {
    #[classmethod]
    #[pyo3(signature = (
        template,
        targets,
        target_kind=0,
        admission_policy=0,
        timing=execution::target::TARGET_TIMING_CLOSE_TARGET_V2_SAME_CLOSE,
        invalid_target_policy=0,
        tradable=None,
        stale=None,
        qty_step=None,
        min_qty=None,
        min_notional=None,
        equity_fraction=None,
        output_profile=0,
    ))]
    #[allow(clippy::too_many_arguments)]
    fn from_template(
        _cls: &Bound<'_, PyType>,
        py: Python<'_>,
        template: Py<NativeExecutionTemplateCore>,
        targets: PyReadonlyArray2<'_, f64>,
        target_kind: u8,
        admission_policy: u8,
        timing: u8,
        invalid_target_policy: u8,
        tradable: Option<PyReadonlyArray2<'_, bool>>,
        stale: Option<PyReadonlyArray2<'_, bool>>,
        qty_step: Option<PyReadonlyArray1<'_, f64>>,
        min_qty: Option<PyReadonlyArray1<'_, f64>>,
        min_notional: Option<PyReadonlyArray1<'_, f64>>,
        equity_fraction: Option<PyReadonlyArray1<'_, f64>>,
        output_profile: u8,
    ) -> PyResult<Self> {
        let template = template.borrow(py).inner.clone();
        let expected_shape = [template.bar_count(), template.n_symbols()];
        if targets.shape() != expected_shape {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "native shared portfolio targets must match template (bars, symbols)",
            ));
        }
        let width = expected_shape[0]
            .checked_mul(expected_shape[1])
            .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("target dimensions overflow"))?;
        let target_values = targets.as_slice()?.to_vec();
        let matrix_or_default = |values: Option<PyReadonlyArray2<'_, bool>>,
                                 default: bool,
                                 name: &str|
         -> PyResult<Vec<bool>> {
            match values {
                Some(values) => {
                    if values.shape() != expected_shape {
                        return Err(pyo3::exceptions::PyValueError::new_err(format!(
                            "native shared portfolio {name} mask must match target shape"
                        )));
                    }
                    Ok(values.as_slice()?.to_vec())
                }
                None => Ok(vec![default; width]),
            }
        };
        let vector_or_default = |values: Option<PyReadonlyArray1<'_, f64>>,
                                 default: f64,
                                 name: &str|
         -> PyResult<Vec<f64>> {
            match values {
                Some(values) => {
                    if values.len() != expected_shape[1] {
                        return Err(pyo3::exceptions::PyValueError::new_err(format!(
                            "native shared portfolio {name} length must match template symbols"
                        )));
                    }
                    Ok(values.as_slice()?.to_vec())
                }
                None => Ok(vec![default; expected_shape[1]]),
            }
        };
        let kind = execution::target::DirectTargetKindV1::try_from(target_kind)
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let invalid_policy =
            execution::target::InvalidTargetPolicyV1::try_from(invalid_target_policy)
                .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let policy = execution::target::PortfolioAdmissionPolicyV1::try_from(admission_policy)
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let output = execution::NativeOutputProfileV1::try_from(output_profile)
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let inner = execution::target::SharedPortfolioTargetRequestV1::from_template(
            template,
            target_values,
            kind,
            timing,
            invalid_policy,
            matrix_or_default(tradable, true, "tradable")?,
            matrix_or_default(stale, false, "stale")?,
            vector_or_default(qty_step, 0.0, "qty_step")?,
            vector_or_default(min_qty, 0.0, "min_qty")?,
            vector_or_default(min_notional, 0.0, "min_notional")?,
            vector_or_default(equity_fraction, 1.0, "equity_fraction")?,
            policy,
            output,
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(Self {
            inner: Arc::new(inner),
        })
    }

    #[getter]
    fn request_version(&self) -> u16 {
        1
    }

    #[getter]
    fn fingerprint(&self) -> String {
        self.inner.fingerprint_hex()
    }

    #[getter]
    fn template_fingerprint(&self) -> String {
        self.inner.inner().template().fingerprint_hex()
    }

    #[getter]
    fn target_kind(&self) -> &'static str {
        self.inner.inner().kind().name()
    }

    #[getter]
    fn admission_policy(&self) -> &'static str {
        self.inner.admission_policy().name()
    }

    #[getter]
    fn output_profile(&self) -> &'static str {
        self.inner.inner().output_profile().name()
    }

    #[getter]
    fn bars(&self) -> usize {
        self.inner.inner().template().bar_count()
    }

    #[getter]
    fn symbols(&self) -> usize {
        self.inner.inner().template().n_symbols()
    }

    #[getter]
    fn request_bytes(&self) -> usize {
        self.inner.request_bytes()
    }

    #[getter]
    fn native_target_no_order_arena(&self) -> bool {
        true
    }

    fn with_audit_detail_limit(&self, detail_row_limit: usize) -> PyResult<Self> {
        let inner = self
            .inner
            .as_ref()
            .clone()
            .with_audit_detail_limit(detail_row_limit)
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(Self {
            inner: Arc::new(inner),
        })
    }

    /// One detached Rust pass over a shared account.  The dictionary is a
    /// cold-path SoA adapter; it never replays target execution in Python.
    fn execute(&self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        let request = self.inner.clone();
        let result = py
            .detach(move || request.execute())
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        shared_portfolio_target_output_payload(py, result)
    }
}

/// Mutable, non-thread-shareable native scenario runner. It owns one
/// `FullSession` and one immutable request template; every execution begins
/// from a deterministic account/order reset, so folds and optimizer scenarios
/// cannot leak lifecycle state into one another.
#[pyclass(unsendable)]
struct NativeExecutionRunnerCore {
    request: execution::NativeExecutionRequestV1,
    runner: Option<execution::NativeExecutionRunnerV1>,
    boundary_calls: u64,
    full_rebuilds: u64,
    closed: bool,
}

impl NativeExecutionRunnerCore {
    fn take_runner(&mut self) -> PyResult<execution::NativeExecutionRunnerV1> {
        if self.closed {
            return Err(pyo3::exceptions::PyRuntimeError::new_err(
                "native execution runner is closed",
            ));
        }
        self.runner.take().ok_or_else(|| {
            pyo3::exceptions::PyRuntimeError::new_err("native execution runner is unavailable")
        })
    }

    fn restore_runner(&mut self, runner: execution::NativeExecutionRunnerV1) {
        self.runner = Some(runner);
    }

    fn execute_result(&mut self, py: Python<'_>) -> PyResult<execution::NativeExecutionResultV1> {
        let mut runner = self.take_runner()?;
        let request = self.request.clone();
        let (runner, result) = py.detach(move || {
            let result = runner.execute_request(&request);
            (runner, result)
        });
        self.restore_runner(runner);
        self.boundary_calls = self
            .boundary_calls
            .checked_add(1)
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("boundary call overflow"))?;
        result.map_err(pyo3::exceptions::PyValueError::new_err)
    }
}

#[pymethods]
impl NativeExecutionRunnerCore {
    /// Execute once and return profile-specific typed SoA output. The Python
    /// boundary is one detached call; no callback or result replay occurs.
    fn execute_typed(&mut self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let result = self.execute_result(py)?;
        native_request_typed_output(py, result)
    }

    /// Explicit legacy cold-path adaptation for clients still expecting the
    /// historical dictionary surface.
    fn execute(&mut self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        let result = self.execute_result(py)?;
        native_request_output_payload(py, result)
    }

    /// Reset scope is explicit. `account_only` is intentionally unsupported:
    /// retaining order/lifecycle state while resetting account would create an
    /// ambiguous scenario. Result buffers are already detached into output
    /// owners, so releasing scratch capacity cannot invalidate past results.
    #[pyo3(signature = (scope="account_and_orders", max_capacity=0))]
    fn reset(&mut self, scope: &str, max_capacity: usize) -> PyResult<()> {
        if self.closed {
            return Err(pyo3::exceptions::PyRuntimeError::new_err(
                "native execution runner is closed",
            ));
        }
        match scope {
            "account_and_orders" | "scenario_state" => {
                let runner = self.runner.as_mut().ok_or_else(|| {
                    pyo3::exceptions::PyRuntimeError::new_err(
                        "native execution runner is unavailable",
                    )
                })?;
                runner
                    .reset_account_and_orders()
                    .map_err(pyo3::exceptions::PyValueError::new_err)?;
            }
            "result_buffers" => {
                let runner = self.runner.as_mut().ok_or_else(|| {
                    pyo3::exceptions::PyRuntimeError::new_err(
                        "native execution runner is unavailable",
                    )
                })?;
                runner.release_transient_buffers(max_capacity);
            }
            "full_rebuild" => {
                let next_generation = self
                    .runner
                    .as_ref()
                    .ok_or_else(|| {
                        pyo3::exceptions::PyRuntimeError::new_err(
                            "native execution runner is unavailable",
                        )
                    })?
                    .generation()
                    .checked_add(1)
                    .ok_or_else(|| {
                        pyo3::exceptions::PyRuntimeError::new_err(
                            "native execution runner generation overflow",
                        )
                    })?;
                self.runner = Some(
                    execution::NativeExecutionRunnerV1::new_with_generation(
                        self.request.template().clone(),
                        next_generation,
                    )
                    .map_err(pyo3::exceptions::PyValueError::new_err)?,
                );
                self.full_rebuilds = self.full_rebuilds.checked_add(1).ok_or_else(|| {
                    pyo3::exceptions::PyRuntimeError::new_err("full rebuild count overflow")
                })?;
            }
            "account_only" => {
                return Err(pyo3::exceptions::PyNotImplementedError::new_err(
                    "account_only reset is unsupported for full native execution; use account_and_orders",
                ));
            }
            _ => {
                return Err(pyo3::exceptions::PyValueError::new_err(
                    "reset scope must be account_and_orders, scenario_state, result_buffers, or full_rebuild",
                ));
            }
        }
        Ok(())
    }

    /// Drop native runner state while retaining no hidden Python callback or
    /// result reference. A closed runner cannot be reused.
    fn close(&mut self) {
        self.runner = None;
        self.closed = true;
    }

    #[getter]
    fn closed(&self) -> bool {
        self.closed
    }

    /// Cold-path lifecycle and boundary observability. This dictionary is
    /// never materialized by `execute_typed()` in the execution hot path.
    fn diagnostics(&self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        let payload = PyDict::new(py);
        payload.set_item("request_fingerprint", self.request.fingerprint_hex())?;
        payload.set_item(
            "template_fingerprint",
            self.request.template().fingerprint_hex(),
        )?;
        payload.set_item("boundary_calls", self.boundary_calls)?;
        payload.set_item("python_callbacks", 0)?;
        payload.set_item("full_rebuilds", self.full_rebuilds)?;
        payload.set_item("closed", self.closed)?;
        payload.set_item(
            "market_bytes",
            self.request.template().source_market_bytes(),
        )?;
        payload.set_item("view_bytes", self.request.template().view_bytes())?;
        if let Some(runner) = self.runner.as_ref() {
            let (fills, events, active) = runner.step_buffer_capacities();
            let (slots, capacity, compactions, removed) = runner.order_arena_counters();
            let (expiry_scans, matching_scans, relationship_scans) = runner.engine_scan_counters();
            payload.set_item("generation", runner.generation())?;
            payload.set_item("run_count", runner.run_count())?;
            payload.set_item("explicit_reset_count", runner.explicit_reset_count())?;
            payload.set_item("session_reset_count", runner.session_reset_count())?;
            payload.set_item("step_fill_buffer_capacity", fills)?;
            payload.set_item("step_event_buffer_capacity", events)?;
            payload.set_item("step_active_order_buffer_capacity", active)?;
            payload.set_item("order_arena_slots", slots)?;
            payload.set_item("order_arena_capacity", capacity)?;
            payload.set_item("order_compactions", compactions)?;
            payload.set_item("terminal_orders_removed", removed)?;
            payload.set_item("margin_recompute_count", runner.margin_recompute_count())?;
            payload.set_item(
                "derived_account_cache_hits",
                runner.derived_account_cache_hits(),
            )?;
            payload.set_item(
                "derived_account_recomputes",
                runner.derived_account_recomputes(),
            )?;
            payload.set_item(
                "matching_candidate_capacity",
                runner.matching_candidate_capacity(),
            )?;
            payload.set_item(
                "order_arena_retired_slots",
                runner.order_arena_retired_slots(),
            )?;
            // Reset ownership is intentionally observable only on this
            // cold-path diagnostics surface. Typed execution retains no
            // account/order result buffers inside the reusable runner.
            payload.set_item("reset_manifest", "quantbt-native-reset-manifest-v1")?;
            payload.set_item("retained_output_policy", "owned_transfer_no_lease_v1")?;
            payload.set_item("carried_account_reset_allowed", false)?;
            payload.set_item("expiry_scan_count", expiry_scans)?;
            payload.set_item("matching_scan_count", matching_scans)?;
            payload.set_item("relationship_scan_count", relationship_scans)?;
        }
        Ok(payload.unbind())
    }
}

/// Typed, scalar-only result for one prepared native WFO score or selected
/// audit rerun.  The execution loop does not construct this Python object;
/// it is a cold-path view over Rust-owned SoA-compatible metric rows.
#[pyclass(name = "NativeWfoMetricMatrixV2", module = "_quantbt_native")]
struct NativeWfoMetricMatrixCore {
    inner: batch::NativeWfoMetricMatrixV2,
}

/// Immutable Rust-owned WFO signal buffer.  Creating this object is the one
/// explicit Python-to-Rust intent-ingestion boundary; score/audit calls borrow
/// its `Arc` without another candidate-by-bar copy.
#[pyclass(name = "NativeWfoPreparedSignalBatchV2", module = "_quantbt_native")]
struct NativeWfoPreparedSignalBatchCore {
    inner: Arc<batch::PreparedWfoSignalBatchV2>,
}

#[pymethods]
impl NativeWfoPreparedSignalBatchCore {
    #[getter]
    fn rows(&self) -> usize {
        self.inner.rows()
    }

    #[getter]
    fn bars(&self) -> usize {
        self.inner.bars()
    }

    #[getter]
    fn per_fold(&self) -> bool {
        self.inner.is_per_fold()
    }

    #[getter]
    fn intent_fingerprint(&self) -> String {
        self.inner.fingerprint_hex()
    }

    #[getter]
    fn intent_ingest_bytes(&self) -> usize {
        self.inner.ingest_bytes()
    }
}

impl NativeWfoMetricMatrixCore {
    fn candidate_ids(&self, py: Python<'_>) -> Py<PyArray1<u64>> {
        PyArray1::from_vec(
            py,
            self.inner.rows.iter().map(|row| row.candidate_id).collect(),
        )
        .unbind()
    }

    fn fold_ids(&self, py: Python<'_>) -> Py<PyArray1<u32>> {
        PyArray1::from_vec(py, self.inner.rows.iter().map(|row| row.fold_id).collect()).unbind()
    }

    fn scenario_ids(&self, py: Python<'_>) -> Py<PyArray1<u32>> {
        PyArray1::from_vec(
            py,
            self.inner.rows.iter().map(|row| row.scenario_id).collect(),
        )
        .unbind()
    }

    fn statuses(&self, py: Python<'_>) -> Py<PyArray1<u16>> {
        PyArray1::from_vec(
            py,
            self.inner
                .rows
                .iter()
                .map(|row| row.status.code())
                .collect(),
        )
        .unbind()
    }

    fn f64_column(
        &self,
        py: Python<'_>,
        extract: impl Fn(&batch::WfoCandidateMetricRowV2) -> f64,
    ) -> Py<PyArray1<f64>> {
        PyArray1::from_vec(py, self.inner.rows.iter().map(extract).collect()).unbind()
    }

    fn u64_column(
        &self,
        py: Python<'_>,
        extract: impl Fn(&batch::WfoCandidateMetricRowV2) -> u64,
    ) -> Py<PyArray1<u64>> {
        PyArray1::from_vec(py, self.inner.rows.iter().map(extract).collect()).unbind()
    }

    fn bool_column(
        &self,
        py: Python<'_>,
        extract: impl Fn(&batch::WfoCandidateMetricRowV2) -> bool,
    ) -> Py<PyArray1<bool>> {
        PyArray1::from_vec(py, self.inner.rows.iter().map(extract).collect()).unbind()
    }

    fn fingerprint_column(
        &self,
        py: Python<'_>,
        extract: impl Fn(&batch::WfoCandidateMetricRowV2) -> [u8; 32],
    ) -> Vec<String> {
        let _ = py;
        self.inner
            .rows
            .iter()
            .map(|row| hex_fingerprint(&extract(row)))
            .collect()
    }
}

#[pymethods]
impl NativeWfoMetricMatrixCore {
    #[getter]
    fn candidate_id(&self, py: Python<'_>) -> Py<PyArray1<u64>> {
        self.candidate_ids(py)
    }

    #[getter]
    fn fold_id(&self, py: Python<'_>) -> Py<PyArray1<u32>> {
        self.fold_ids(py)
    }

    #[getter]
    fn scenario_id(&self, py: Python<'_>) -> Py<PyArray1<u32>> {
        self.scenario_ids(py)
    }

    #[getter]
    fn status(&self, py: Python<'_>) -> Py<PyArray1<u16>> {
        self.statuses(py)
    }

    #[getter]
    fn final_equity(&self, py: Python<'_>) -> Py<PyArray1<f64>> {
        self.f64_column(py, |row| row.final_equity)
    }

    #[getter]
    fn fold_return(&self, py: Python<'_>) -> Py<PyArray1<f64>> {
        self.f64_column(py, |row| row.fold_return)
    }

    #[getter]
    fn fold_sharpe(&self, py: Python<'_>) -> Py<PyArray1<f64>> {
        self.f64_column(py, |row| row.fold_sharpe)
    }

    #[getter]
    fn fold_sortino(&self, py: Python<'_>) -> Py<PyArray1<f64>> {
        self.f64_column(py, |row| row.fold_sortino)
    }

    #[getter]
    fn max_drawdown(&self, py: Python<'_>) -> Py<PyArray1<f64>> {
        self.f64_column(py, |row| row.max_drawdown)
    }

    #[getter]
    fn turnover(&self, py: Python<'_>) -> Py<PyArray1<f64>> {
        self.f64_column(py, |row| row.turnover)
    }

    #[getter]
    fn total_fee(&self, py: Python<'_>) -> Py<PyArray1<f64>> {
        self.f64_column(py, |row| row.total_fee)
    }

    #[getter]
    fn total_funding(&self, py: Python<'_>) -> Py<PyArray1<f64>> {
        self.f64_column(py, |row| row.total_funding)
    }

    #[getter]
    fn fill_rate(&self, py: Python<'_>) -> Py<PyArray1<f64>> {
        self.f64_column(py, |row| row.fill_rate)
    }

    #[getter]
    fn fill_count(&self, py: Python<'_>) -> Py<PyArray1<u64>> {
        self.u64_column(py, |row| row.fill_count)
    }

    #[getter]
    fn rejected_count(&self, py: Python<'_>) -> Py<PyArray1<u64>> {
        self.u64_column(py, |row| row.rejected_count)
    }

    #[getter]
    fn liquidated(&self, py: Python<'_>) -> Py<PyArray1<bool>> {
        self.bool_column(py, |row| row.liquidated)
    }

    #[getter]
    fn request_fingerprint(&self, py: Python<'_>) -> Vec<String> {
        self.fingerprint_column(py, |row| row.request_fingerprint)
    }

    #[getter]
    fn terminal_fingerprint(&self, py: Python<'_>) -> Vec<String> {
        self.fingerprint_column(py, |row| row.terminal_fingerprint)
    }

    #[getter]
    fn error_slot(&self, py: Python<'_>) -> Py<PyArray1<u32>> {
        PyArray1::from_vec(
            py,
            self.inner.rows.iter().map(|row| row.error_slot).collect(),
        )
        .unbind()
    }

    #[getter]
    fn errors(&self) -> Vec<String> {
        self.inner.errors.clone()
    }

    #[getter]
    fn errors_dropped(&self) -> usize {
        self.inner.errors_dropped
    }

    #[getter]
    fn plan_fingerprint(&self) -> String {
        self.inner.plan_fingerprint_hex()
    }

    #[getter]
    fn intent_fingerprint(&self) -> String {
        self.inner.intent_fingerprint_hex()
    }

    #[getter]
    fn audit(&self) -> bool {
        self.inner.audit
    }

    #[getter]
    fn worker_count(&self) -> usize {
        self.inner.worker_count
    }

    #[getter]
    fn active_worker_count(&self) -> usize {
        self.inner.active_worker_count
    }

    #[getter]
    fn market_copy_bytes(&self) -> usize {
        self.inner.market_copy_bytes
    }

    #[getter]
    fn candidate_execution_copy_bytes(&self) -> usize {
        self.inner.candidate_execution_copy_bytes
    }

    #[getter]
    fn intent_ingest_bytes(&self) -> usize {
        self.inner.intent_ingest_bytes
    }

    #[getter]
    fn worker_pool_creations(&self) -> u64 {
        self.inner.worker_pool_creations
    }

    #[getter]
    fn worker_pool_batches(&self) -> u64 {
        self.inner.worker_pool_batches
    }

    #[getter]
    fn poison_recoveries(&self) -> u64 {
        self.inner.poison_recoveries
    }

    #[getter]
    fn worker_tasks(&self) -> Vec<u64> {
        self.inner.worker_tasks.clone()
    }

    /// Explicit cold-path conversion for pandas/Optuna adapters. Execution
    /// and metric collection always complete before this dictionary exists.
    fn as_dict(&self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        let payload = PyDict::new(py);
        payload.set_item("candidate_id", self.candidate_ids(py))?;
        payload.set_item("fold_id", self.fold_ids(py))?;
        payload.set_item("scenario_id", self.scenario_ids(py))?;
        payload.set_item("status", self.statuses(py))?;
        payload.set_item("final_equity", self.f64_column(py, |row| row.final_equity))?;
        payload.set_item("fold_return", self.f64_column(py, |row| row.fold_return))?;
        payload.set_item("fold_sharpe", self.f64_column(py, |row| row.fold_sharpe))?;
        payload.set_item("fold_sortino", self.f64_column(py, |row| row.fold_sortino))?;
        payload.set_item("max_drawdown", self.f64_column(py, |row| row.max_drawdown))?;
        payload.set_item("turnover", self.f64_column(py, |row| row.turnover))?;
        payload.set_item("total_fee", self.f64_column(py, |row| row.total_fee))?;
        payload.set_item(
            "total_funding",
            self.f64_column(py, |row| row.total_funding),
        )?;
        payload.set_item("fill_rate", self.f64_column(py, |row| row.fill_rate))?;
        payload.set_item("fill_count", self.u64_column(py, |row| row.fill_count))?;
        payload.set_item(
            "rejected_count",
            self.u64_column(py, |row| row.rejected_count),
        )?;
        payload.set_item("liquidated", self.bool_column(py, |row| row.liquidated))?;
        payload.set_item(
            "request_fingerprint",
            self.fingerprint_column(py, |row| row.request_fingerprint),
        )?;
        payload.set_item(
            "terminal_fingerprint",
            self.fingerprint_column(py, |row| row.terminal_fingerprint),
        )?;
        payload.set_item(
            "error_slot",
            PyArray1::from_vec(
                py,
                self.inner.rows.iter().map(|row| row.error_slot).collect(),
            ),
        )?;
        payload.set_item("errors", self.inner.errors.clone())?;
        payload.set_item("errors_dropped", self.inner.errors_dropped)?;
        payload.set_item("plan_fingerprint", self.inner.plan_fingerprint_hex())?;
        payload.set_item("intent_fingerprint", self.inner.intent_fingerprint_hex())?;
        payload.set_item("audit", self.inner.audit)?;
        payload.set_item("worker_count", self.inner.worker_count)?;
        payload.set_item("active_worker_count", self.inner.active_worker_count)?;
        payload.set_item("worker_tasks", self.inner.worker_tasks.clone())?;
        payload.set_item("market_copy_bytes", self.inner.market_copy_bytes)?;
        payload.set_item(
            "candidate_execution_copy_bytes",
            self.inner.candidate_execution_copy_bytes,
        )?;
        payload.set_item("intent_ingest_bytes", self.inner.intent_ingest_bytes)?;
        payload.set_item("worker_pool_creations", self.inner.worker_pool_creations)?;
        payload.set_item("worker_pool_batches", self.inner.worker_pool_batches)?;
        payload.set_item("poison_recoveries", self.inner.poison_recoveries)?;
        Ok(payload.unbind())
    }
}

/// Persistent prepared WFO runtime. One instance owns an immutable template,
/// causal fold views, and a reusable Rust worker pool. It deliberately accepts
/// only bounded strategy-IR signal batches in V2; generic Python callbacks and
/// portfolio/package targets fail at construction rather than silently taking
/// a compatibility path.
#[pyclass(name = "NativeWfoRuntimeV2", module = "_quantbt_native")]
struct NativeWfoRuntimeCore {
    inner: Arc<batch::NativeWfoRuntimeV2>,
}

impl NativeWfoRuntimeCore {
    fn parse_parameters(
        parameters: Option<PyReadonlyArray2<'_, f64>>,
        candidates: usize,
    ) -> PyResult<Option<Vec<f64>>> {
        parameters
            .map(|values| {
                let shape = values.shape();
                if shape != [candidates, strategy_ir::PARAMETER_WIDTH] {
                    return Err(pyo3::exceptions::PyValueError::new_err(
                        "native WFO parameter matrix must have shape (candidates, 4)",
                    ));
                }
                Ok(values.as_slice()?.to_vec())
            })
            .transpose()
    }

    fn shared_batch(
        &self,
        candidate_ids: PyReadonlyArray1<'_, u64>,
        signals: PyReadonlyArray2<'_, f64>,
        parameters: Option<PyReadonlyArray2<'_, f64>>,
    ) -> PyResult<Arc<batch::PreparedWfoSignalBatchV2>> {
        let candidate_ids = candidate_ids.as_slice()?.to_vec();
        let shape = signals.shape();
        if shape != [candidate_ids.len(), self.inner.plan().bar_count()] {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "native WFO shared signal matrix must have shape (candidates, prepared_market_bars)",
            ));
        }
        let parameters = Self::parse_parameters(parameters, candidate_ids.len())?;
        batch::PreparedWfoSignalBatchV2::shared(
            candidate_ids,
            signals.as_slice()?.to_vec(),
            shape[1],
            parameters,
        )
        .map(Arc::new)
        .map_err(pyo3::exceptions::PyValueError::new_err)
    }

    fn per_fold_batch(
        &self,
        candidate_ids: PyReadonlyArray1<'_, u64>,
        signals: PyReadonlyArray3<'_, f64>,
        parameters: Option<PyReadonlyArray2<'_, f64>>,
    ) -> PyResult<Arc<batch::PreparedWfoSignalBatchV2>> {
        let candidate_ids = candidate_ids.as_slice()?.to_vec();
        let shape = signals.shape();
        if shape
            != [
                self.inner.plan().folds().len(),
                candidate_ids.len(),
                self.inner.plan().bar_count(),
            ]
        {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "native WFO per-fold signal cube must have shape (folds, candidates, prepared_market_bars)",
            ));
        }
        let parameters = Self::parse_parameters(parameters, candidate_ids.len())?;
        batch::PreparedWfoSignalBatchV2::per_fold(
            candidate_ids,
            signals.as_slice()?.to_vec(),
            shape[2],
            shape[0],
            parameters,
        )
        .map(Arc::new)
        .map_err(pyo3::exceptions::PyValueError::new_err)
    }

    fn execute_score(
        &self,
        py: Python<'_>,
        batch: Arc<batch::PreparedWfoSignalBatchV2>,
    ) -> PyResult<NativeWfoMetricMatrixCore> {
        let runtime = self.inner.clone();
        let inner = py
            .detach(move || runtime.score(batch))
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(NativeWfoMetricMatrixCore { inner })
    }

    fn execute_audit(
        &self,
        py: Python<'_>,
        batch: Arc<batch::PreparedWfoSignalBatchV2>,
        candidate_ids: Vec<u64>,
        expected_intent_fingerprint: [u8; 32],
    ) -> PyResult<NativeWfoMetricMatrixCore> {
        let runtime = self.inner.clone();
        let inner = py
            .detach(move || {
                runtime.audit_selected(batch, &candidate_ids, expected_intent_fingerprint)
            })
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(NativeWfoMetricMatrixCore { inner })
    }
}

#[pymethods]
impl NativeWfoRuntimeCore {
    #[classmethod]
    #[pyo3(signature = (
        template,
        program,
        folds,
        intent_kind="strategy_ir_signal_target_v1",
        optimizer_schedule="certified_sequential_v1",
        workers=1,
        max_metric_rows=1_000_000,
        max_error_rows=64,
        max_bars=None,
        max_wall_time_ms=None,
        max_commands=None,
        max_orders=None,
        max_active_orders=None,
        max_fills=None,
        max_audit_rows=None,
        max_native_memory_bytes=None,
        max_workers=None,
    ))]
    #[allow(clippy::too_many_arguments)]
    fn from_template(
        _cls: &Bound<'_, PyType>,
        py: Python<'_>,
        template: Py<NativeExecutionTemplateCore>,
        program: PyRef<'_, NativeStrategyProgramCore>,
        folds: PyReadonlyArray2<'_, u32>,
        intent_kind: &str,
        optimizer_schedule: &str,
        workers: usize,
        max_metric_rows: usize,
        max_error_rows: usize,
        max_bars: Option<u64>,
        max_wall_time_ms: Option<u64>,
        max_commands: Option<u64>,
        max_orders: Option<u64>,
        max_active_orders: Option<u64>,
        max_fills: Option<u64>,
        max_audit_rows: Option<u64>,
        max_native_memory_bytes: Option<u64>,
        max_workers: Option<u16>,
    ) -> PyResult<Self> {
        let shape = folds.shape();
        if shape.len() != 2 || shape[1] != 6 || shape[0] == 0 {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "native WFO folds must have shape (fold_count, 6)",
            ));
        }
        let fold_values = folds.as_slice()?;
        let fold_plan = fold_values
            .chunks_exact(6)
            .map(|values| batch::FoldPlan {
                fold_id: values[0],
                warmup_start: values[1],
                train_start: values[2],
                train_end: values[3],
                test_start: values[4],
                test_end: values[5],
            })
            .collect::<Vec<_>>();
        let intent = batch::PreparedWfoIntentKindV2::from_name(intent_kind)
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let schedule = batch::WfoOptimizerScheduleV1::from_name(optimizer_schedule)
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let template = template.borrow(py).inner.clone();
        let batch_template = batch::BatchTemplate::from_execution_template(
            template,
            Arc::new(program.inner.clone()),
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let plan = batch::NativeWfoPlanV2::new(
            batch_template,
            fold_plan,
            intent,
            schedule,
            batch::RuntimeBudgetV1 {
                workers,
                max_metric_rows,
                max_error_rows,
                max_bars,
                max_wall_time_ms,
                max_commands,
                max_orders,
                max_active_orders,
                max_fills,
                max_audit_rows,
                max_native_memory_bytes,
                max_workers,
            },
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let inner = batch::NativeWfoRuntimeV2::new(Arc::new(plan))
            .map_err(pyo3::exceptions::PyRuntimeError::new_err)?;
        Ok(Self {
            inner: Arc::new(inner),
        })
    }

    #[pyo3(signature = (candidate_ids, signals, parameters=None))]
    fn score_shared(
        &self,
        py: Python<'_>,
        candidate_ids: PyReadonlyArray1<'_, u64>,
        signals: PyReadonlyArray2<'_, f64>,
        parameters: Option<PyReadonlyArray2<'_, f64>>,
    ) -> PyResult<NativeWfoMetricMatrixCore> {
        let batch = self.shared_batch(candidate_ids, signals, parameters)?;
        self.execute_score(py, batch)
    }

    #[pyo3(signature = (candidate_ids, signals, parameters=None))]
    fn prepare_shared(
        &self,
        candidate_ids: PyReadonlyArray1<'_, u64>,
        signals: PyReadonlyArray2<'_, f64>,
        parameters: Option<PyReadonlyArray2<'_, f64>>,
    ) -> PyResult<NativeWfoPreparedSignalBatchCore> {
        Ok(NativeWfoPreparedSignalBatchCore {
            inner: self.shared_batch(candidate_ids, signals, parameters)?,
        })
    }

    #[pyo3(signature = (candidate_ids, signals, parameters=None))]
    fn score_per_fold(
        &self,
        py: Python<'_>,
        candidate_ids: PyReadonlyArray1<'_, u64>,
        signals: PyReadonlyArray3<'_, f64>,
        parameters: Option<PyReadonlyArray2<'_, f64>>,
    ) -> PyResult<NativeWfoMetricMatrixCore> {
        let batch = self.per_fold_batch(candidate_ids, signals, parameters)?;
        self.execute_score(py, batch)
    }

    #[pyo3(signature = (candidate_ids, signals, parameters=None))]
    fn prepare_per_fold(
        &self,
        candidate_ids: PyReadonlyArray1<'_, u64>,
        signals: PyReadonlyArray3<'_, f64>,
        parameters: Option<PyReadonlyArray2<'_, f64>>,
    ) -> PyResult<NativeWfoPreparedSignalBatchCore> {
        Ok(NativeWfoPreparedSignalBatchCore {
            inner: self.per_fold_batch(candidate_ids, signals, parameters)?,
        })
    }

    fn score_prepared(
        &self,
        py: Python<'_>,
        batch: PyRef<'_, NativeWfoPreparedSignalBatchCore>,
    ) -> PyResult<NativeWfoMetricMatrixCore> {
        self.execute_score(py, batch.inner.clone())
    }

    #[pyo3(signature = (candidate_ids, signals, selected_candidate_ids, expected_intent_fingerprint, parameters=None))]
    #[allow(clippy::too_many_arguments)]
    fn audit_shared(
        &self,
        py: Python<'_>,
        candidate_ids: PyReadonlyArray1<'_, u64>,
        signals: PyReadonlyArray2<'_, f64>,
        selected_candidate_ids: PyReadonlyArray1<'_, u64>,
        expected_intent_fingerprint: &str,
        parameters: Option<PyReadonlyArray2<'_, f64>>,
    ) -> PyResult<NativeWfoMetricMatrixCore> {
        let batch = self.shared_batch(candidate_ids, signals, parameters)?;
        self.execute_audit(
            py,
            batch,
            selected_candidate_ids.as_slice()?.to_vec(),
            parse_fingerprint(expected_intent_fingerprint)?,
        )
    }

    #[pyo3(signature = (candidate_ids, signals, selected_candidate_ids, expected_intent_fingerprint, parameters=None))]
    #[allow(clippy::too_many_arguments)]
    fn audit_per_fold(
        &self,
        py: Python<'_>,
        candidate_ids: PyReadonlyArray1<'_, u64>,
        signals: PyReadonlyArray3<'_, f64>,
        selected_candidate_ids: PyReadonlyArray1<'_, u64>,
        expected_intent_fingerprint: &str,
        parameters: Option<PyReadonlyArray2<'_, f64>>,
    ) -> PyResult<NativeWfoMetricMatrixCore> {
        let batch = self.per_fold_batch(candidate_ids, signals, parameters)?;
        self.execute_audit(
            py,
            batch,
            selected_candidate_ids.as_slice()?.to_vec(),
            parse_fingerprint(expected_intent_fingerprint)?,
        )
    }

    #[pyo3(signature = (batch, selected_candidate_ids, expected_intent_fingerprint))]
    fn audit_prepared(
        &self,
        py: Python<'_>,
        batch: PyRef<'_, NativeWfoPreparedSignalBatchCore>,
        selected_candidate_ids: PyReadonlyArray1<'_, u64>,
        expected_intent_fingerprint: &str,
    ) -> PyResult<NativeWfoMetricMatrixCore> {
        self.execute_audit(
            py,
            batch.inner.clone(),
            selected_candidate_ids.as_slice()?.to_vec(),
            parse_fingerprint(expected_intent_fingerprint)?,
        )
    }

    fn cancel(&self) {
        self.inner.cancel();
    }

    fn clear_cancellation(&self) {
        self.inner.clear_cancellation();
    }

    fn reset(&self) -> PyResult<()> {
        self.inner
            .reset()
            .map_err(pyo3::exceptions::PyRuntimeError::new_err)
    }

    fn close(&self) -> PyResult<()> {
        self.inner
            .close()
            .map_err(pyo3::exceptions::PyRuntimeError::new_err)
    }

    #[getter]
    fn closed(&self) -> bool {
        self.inner.closed()
    }

    #[getter]
    fn plan_fingerprint(&self) -> String {
        self.inner.plan().fingerprint_hex()
    }

    #[getter]
    fn intent_kind(&self) -> &'static str {
        self.inner.plan().intent_kind().name()
    }

    #[getter]
    fn optimizer_schedule(&self) -> &'static str {
        self.inner.plan().optimizer_schedule().name()
    }

    fn diagnostics(&self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        let stats = self.inner.stats();
        let payload = PyDict::new(py);
        payload.set_item("runtime_version", batch::NATIVE_WFO_RUNTIME_VERSION_V2)?;
        payload.set_item("plan_fingerprint", self.inner.plan().fingerprint_hex())?;
        payload.set_item("intent_kind", self.inner.plan().intent_kind().name())?;
        payload.set_item(
            "optimizer_schedule",
            self.inner.plan().optimizer_schedule().name(),
        )?;
        payload.set_item("bars", self.inner.plan().bar_count())?;
        payload.set_item("fold_count", self.inner.plan().folds().len())?;
        payload.set_item("market_bytes", self.inner.plan().market_bytes())?;
        payload.set_item("worker_pool_creations", stats.worker_pool_creations)?;
        payload.set_item("score_batches", stats.score_batches)?;
        payload.set_item("audit_batches", stats.audit_batches)?;
        payload.set_item("completed_tasks", stats.completed_tasks)?;
        payload.set_item("canceled_tasks", stats.canceled_tasks)?;
        payload.set_item("poison_recoveries", stats.poison_recoveries)?;
        payload.set_item("worker_generation", self.inner.generation())?;
        payload.set_item("max_bars", self.inner.plan().budget().max_bars)?;
        payload.set_item(
            "max_wall_time_ms",
            self.inner.plan().budget().max_wall_time_ms,
        )?;
        payload.set_item(
            "max_native_memory_bytes",
            self.inner.plan().budget().max_native_memory_bytes,
        )?;
        payload.set_item("max_workers", self.inner.plan().budget().max_workers)?;
        payload.set_item("worker_tasks", stats.worker_tasks)?;
        payload.set_item("closed", self.inner.closed())?;
        Ok(payload.unbind())
    }

    #[cfg(test)]
    fn inject_poison_for_test(&self, count: u64) {
        self.inner.inject_poison_for_test(count);
    }
}

/// Immutable Rust-owned direct-target WFO ingress. Creating this object is the
/// only candidate-tape boundary for the target route; score and audit borrow
/// its Rust allocation and never compile a command tape or recreate Python
/// target objects.
#[pyclass(name = "NativeWfoPreparedTargetBatchV1", module = "_quantbt_native")]
struct NativeWfoPreparedTargetBatchCore {
    inner: Arc<batch::target_wfo::PreparedWfoTargetBatchV1>,
}

#[pymethods]
impl NativeWfoPreparedTargetBatchCore {
    #[getter]
    fn rows(&self) -> usize {
        self.inner.rows()
    }

    #[getter]
    fn bars(&self) -> usize {
        self.inner.bars()
    }

    #[getter]
    fn symbols(&self) -> usize {
        self.inner.symbols()
    }

    #[getter]
    fn fold_count(&self) -> usize {
        self.inner.fold_count()
    }

    #[getter]
    fn per_fold(&self) -> bool {
        self.inner.is_per_fold()
    }

    #[getter]
    fn intent_fingerprint(&self) -> String {
        self.inner.fingerprint_hex()
    }

    #[getter]
    fn intent_ingest_bytes(&self) -> usize {
        self.inner.ingest_bytes()
    }
}

/// Typed direct-target WFO runtime. It is intentionally distinct from the
/// Strategy-IR runtime: a target matrix is already a research-level execution
/// intent, and lowering it to signal or generic commands would introduce a
/// second accounting authority.
#[pyclass(name = "NativeTargetWfoRuntimeV2", module = "_quantbt_native")]
struct NativeTargetWfoRuntimeCore {
    inner: Arc<batch::target_wfo::NativeTargetWfoRuntimeV2>,
}

impl NativeTargetWfoRuntimeCore {
    fn matrix_or_default(
        values: Option<PyReadonlyArray2<'_, bool>>,
        expected_shape: [usize; 2],
        default: bool,
        name: &str,
    ) -> PyResult<Vec<bool>> {
        match values {
            Some(values) => {
                if values.shape() != expected_shape {
                    return Err(pyo3::exceptions::PyValueError::new_err(format!(
                        "native target WFO {name} mask must match template (bars, symbols)"
                    )));
                }
                Ok(values.as_slice()?.to_vec())
            }
            None => Ok(vec![default; expected_shape[0] * expected_shape[1]]),
        }
    }

    fn vector_or_default(
        values: Option<PyReadonlyArray1<'_, f64>>,
        symbols: usize,
        default: f64,
        name: &str,
    ) -> PyResult<Vec<f64>> {
        match values {
            Some(values) => {
                if values.len() != symbols {
                    return Err(pyo3::exceptions::PyValueError::new_err(format!(
                        "native target WFO {name} length must match template symbols"
                    )));
                }
                Ok(values.as_slice()?.to_vec())
            }
            None => Ok(vec![default; symbols]),
        }
    }

    fn shared_batch(
        &self,
        candidate_ids: PyReadonlyArray1<'_, u64>,
        targets: PyReadonlyArray3<'_, f64>,
    ) -> PyResult<Arc<batch::target_wfo::PreparedWfoTargetBatchV1>> {
        let candidate_ids = candidate_ids.as_slice()?.to_vec();
        let shape = targets.shape();
        let expected = [
            candidate_ids.len(),
            self.inner.plan().bar_count(),
            self.inner.plan().symbol_count(),
        ];
        if shape != expected {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "native target WFO shared targets must have shape (candidates, prepared_market_bars, symbols)",
            ));
        }
        batch::target_wfo::PreparedWfoTargetBatchV1::shared(
            candidate_ids,
            targets.as_slice()?.to_vec(),
            shape[1],
            shape[2],
        )
        .map(Arc::new)
        .map_err(pyo3::exceptions::PyValueError::new_err)
    }

    fn per_fold_batch(
        &self,
        candidate_ids: PyReadonlyArray1<'_, u64>,
        targets: PyReadonlyArray4<'_, f64>,
    ) -> PyResult<Arc<batch::target_wfo::PreparedWfoTargetBatchV1>> {
        let candidate_ids = candidate_ids.as_slice()?.to_vec();
        let shape = targets.shape();
        let expected = [
            self.inner.plan().folds().len(),
            candidate_ids.len(),
            self.inner.plan().bar_count(),
            self.inner.plan().symbol_count(),
        ];
        if shape != expected {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "native target WFO per-fold targets must have shape (folds, candidates, prepared_market_bars, symbols)",
            ));
        }
        batch::target_wfo::PreparedWfoTargetBatchV1::per_fold(
            candidate_ids,
            targets.as_slice()?.to_vec(),
            shape[2],
            shape[3],
            shape[0],
        )
        .map(Arc::new)
        .map_err(pyo3::exceptions::PyValueError::new_err)
    }

    fn execute_score(
        &self,
        py: Python<'_>,
        batch: Arc<batch::target_wfo::PreparedWfoTargetBatchV1>,
    ) -> PyResult<NativeWfoMetricMatrixCore> {
        let runtime = self.inner.clone();
        let inner = py
            .detach(move || runtime.score(batch))
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(NativeWfoMetricMatrixCore { inner })
    }

    fn execute_audit(
        &self,
        py: Python<'_>,
        batch: Arc<batch::target_wfo::PreparedWfoTargetBatchV1>,
        candidate_ids: Vec<u64>,
        expected_intent_fingerprint: [u8; 32],
    ) -> PyResult<NativeWfoMetricMatrixCore> {
        let runtime = self.inner.clone();
        let inner = py
            .detach(move || {
                runtime.audit_selected(batch, &candidate_ids, expected_intent_fingerprint)
            })
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(NativeWfoMetricMatrixCore { inner })
    }
}

#[pymethods]
impl NativeTargetWfoRuntimeCore {
    #[classmethod]
    #[pyo3(signature = (
        template,
        folds,
        target_kind=0,
        timing=execution::target::TARGET_TIMING_CLOSE_TARGET_V2_SAME_CLOSE,
        invalid_target_policy=0,
        admission_policy=None,
        tradable=None,
        stale=None,
        qty_step=None,
        min_qty=None,
        min_notional=None,
        equity_fraction=None,
        workers=1,
        max_metric_rows=1_000_000,
        max_error_rows=64,
        max_bars=None,
        max_wall_time_ms=None,
        max_commands=None,
        max_orders=None,
        max_active_orders=None,
        max_fills=None,
        max_audit_rows=None,
        max_native_memory_bytes=None,
        max_workers=None,
    ))]
    #[allow(clippy::too_many_arguments)]
    fn from_template(
        _cls: &Bound<'_, PyType>,
        py: Python<'_>,
        template: Py<NativeExecutionTemplateCore>,
        folds: PyReadonlyArray2<'_, u32>,
        target_kind: u8,
        timing: u8,
        invalid_target_policy: u8,
        admission_policy: Option<u8>,
        tradable: Option<PyReadonlyArray2<'_, bool>>,
        stale: Option<PyReadonlyArray2<'_, bool>>,
        qty_step: Option<PyReadonlyArray1<'_, f64>>,
        min_qty: Option<PyReadonlyArray1<'_, f64>>,
        min_notional: Option<PyReadonlyArray1<'_, f64>>,
        equity_fraction: Option<PyReadonlyArray1<'_, f64>>,
        workers: usize,
        max_metric_rows: usize,
        max_error_rows: usize,
        max_bars: Option<u64>,
        max_wall_time_ms: Option<u64>,
        max_commands: Option<u64>,
        max_orders: Option<u64>,
        max_active_orders: Option<u64>,
        max_fills: Option<u64>,
        max_audit_rows: Option<u64>,
        max_native_memory_bytes: Option<u64>,
        max_workers: Option<u16>,
    ) -> PyResult<Self> {
        if workers != 1 {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "native target WFO V1 is deliberately serial; workers must be 1 until a bounded parallel target scheduler is certified",
            ));
        }
        let fold_shape = folds.shape();
        if fold_shape.len() != 2 || fold_shape[1] != 6 || fold_shape[0] == 0 {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "native target WFO folds must have shape (fold_count, 6)",
            ));
        }
        let fold_values = folds.as_slice()?;
        let fold_plan = fold_values
            .chunks_exact(6)
            .map(|values| batch::FoldPlan {
                fold_id: values[0],
                warmup_start: values[1],
                train_start: values[2],
                train_end: values[3],
                test_start: values[4],
                test_end: values[5],
            })
            .collect::<Vec<_>>();
        let template = template.borrow(py).inner.clone();
        let expected_shape = [template.bar_count(), template.n_symbols()];
        let kind = execution::target::DirectTargetKindV1::try_from(target_kind)
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let policy = execution::target::InvalidTargetPolicyV1::try_from(invalid_target_policy)
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let admission_policy = admission_policy
            .map(execution::target::PortfolioAdmissionPolicyV1::try_from)
            .transpose()
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let plan = batch::target_wfo::NativeTargetWfoPlanV1::new(
            template,
            fold_plan,
            kind,
            timing,
            policy,
            Self::matrix_or_default(tradable, expected_shape, true, "tradable")?,
            Self::matrix_or_default(stale, expected_shape, false, "stale")?,
            Self::vector_or_default(qty_step, expected_shape[1], 0.0, "qty_step")?,
            Self::vector_or_default(min_qty, expected_shape[1], 0.0, "min_qty")?,
            Self::vector_or_default(min_notional, expected_shape[1], 0.0, "min_notional")?,
            Self::vector_or_default(equity_fraction, expected_shape[1], 1.0, "equity_fraction")?,
            admission_policy,
            batch::RuntimeBudgetV1 {
                workers,
                max_metric_rows,
                max_error_rows,
                max_bars,
                max_wall_time_ms,
                max_commands,
                max_orders,
                max_active_orders,
                max_fills,
                max_audit_rows,
                max_native_memory_bytes,
                max_workers,
            },
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let inner = batch::target_wfo::NativeTargetWfoRuntimeV2::new(Arc::new(plan))
            .map_err(pyo3::exceptions::PyRuntimeError::new_err)?;
        Ok(Self {
            inner: Arc::new(inner),
        })
    }

    fn score_shared(
        &self,
        py: Python<'_>,
        candidate_ids: PyReadonlyArray1<'_, u64>,
        targets: PyReadonlyArray3<'_, f64>,
    ) -> PyResult<NativeWfoMetricMatrixCore> {
        let batch = self.shared_batch(candidate_ids, targets)?;
        self.execute_score(py, batch)
    }

    fn prepare_shared(
        &self,
        candidate_ids: PyReadonlyArray1<'_, u64>,
        targets: PyReadonlyArray3<'_, f64>,
    ) -> PyResult<NativeWfoPreparedTargetBatchCore> {
        Ok(NativeWfoPreparedTargetBatchCore {
            inner: self.shared_batch(candidate_ids, targets)?,
        })
    }

    fn score_per_fold(
        &self,
        py: Python<'_>,
        candidate_ids: PyReadonlyArray1<'_, u64>,
        targets: PyReadonlyArray4<'_, f64>,
    ) -> PyResult<NativeWfoMetricMatrixCore> {
        let batch = self.per_fold_batch(candidate_ids, targets)?;
        self.execute_score(py, batch)
    }

    fn prepare_per_fold(
        &self,
        candidate_ids: PyReadonlyArray1<'_, u64>,
        targets: PyReadonlyArray4<'_, f64>,
    ) -> PyResult<NativeWfoPreparedTargetBatchCore> {
        Ok(NativeWfoPreparedTargetBatchCore {
            inner: self.per_fold_batch(candidate_ids, targets)?,
        })
    }

    fn score_prepared(
        &self,
        py: Python<'_>,
        batch: PyRef<'_, NativeWfoPreparedTargetBatchCore>,
    ) -> PyResult<NativeWfoMetricMatrixCore> {
        self.execute_score(py, batch.inner.clone())
    }

    fn audit_shared(
        &self,
        py: Python<'_>,
        candidate_ids: PyReadonlyArray1<'_, u64>,
        targets: PyReadonlyArray3<'_, f64>,
        selected_candidate_ids: PyReadonlyArray1<'_, u64>,
        expected_intent_fingerprint: &str,
    ) -> PyResult<NativeWfoMetricMatrixCore> {
        let batch = self.shared_batch(candidate_ids, targets)?;
        self.execute_audit(
            py,
            batch,
            selected_candidate_ids.as_slice()?.to_vec(),
            parse_fingerprint(expected_intent_fingerprint)?,
        )
    }

    fn audit_per_fold(
        &self,
        py: Python<'_>,
        candidate_ids: PyReadonlyArray1<'_, u64>,
        targets: PyReadonlyArray4<'_, f64>,
        selected_candidate_ids: PyReadonlyArray1<'_, u64>,
        expected_intent_fingerprint: &str,
    ) -> PyResult<NativeWfoMetricMatrixCore> {
        let batch = self.per_fold_batch(candidate_ids, targets)?;
        self.execute_audit(
            py,
            batch,
            selected_candidate_ids.as_slice()?.to_vec(),
            parse_fingerprint(expected_intent_fingerprint)?,
        )
    }

    fn audit_prepared(
        &self,
        py: Python<'_>,
        batch: PyRef<'_, NativeWfoPreparedTargetBatchCore>,
        selected_candidate_ids: PyReadonlyArray1<'_, u64>,
        expected_intent_fingerprint: &str,
    ) -> PyResult<NativeWfoMetricMatrixCore> {
        self.execute_audit(
            py,
            batch.inner.clone(),
            selected_candidate_ids.as_slice()?.to_vec(),
            parse_fingerprint(expected_intent_fingerprint)?,
        )
    }

    fn reset(&self) -> PyResult<()> {
        self.inner
            .reset()
            .map_err(pyo3::exceptions::PyRuntimeError::new_err)
    }

    fn cancel(&self) {
        self.inner.cancel();
    }

    fn clear_cancellation(&self) {
        self.inner.clear_cancellation();
    }

    fn close(&self) -> PyResult<()> {
        self.inner
            .close()
            .map_err(pyo3::exceptions::PyRuntimeError::new_err)
    }

    #[getter]
    fn closed(&self) -> bool {
        self.inner.closed()
    }

    #[getter]
    fn plan_fingerprint(&self) -> String {
        self.inner.plan().fingerprint_hex()
    }

    #[getter]
    fn target_kind(&self) -> &'static str {
        self.inner.plan().kind().name()
    }

    #[getter]
    fn timing(&self) -> u8 {
        self.inner.plan().timing()
    }

    fn diagnostics(&self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        let stats = self.inner.stats();
        let plan = self.inner.plan();
        let payload = PyDict::new(py);
        payload.set_item(
            "runtime_version",
            batch::target_wfo::NATIVE_TARGET_WFO_RUNTIME_VERSION_V1,
        )?;
        payload.set_item("plan_fingerprint", plan.fingerprint_hex())?;
        payload.set_item("target_kind", plan.kind().name())?;
        payload.set_item("target_timing", "close_target_v2_same_close")?;
        payload.set_item("invalid_target_policy", "reject_run")?;
        payload.set_item("bars", plan.bar_count())?;
        payload.set_item("symbols", plan.symbol_count())?;
        payload.set_item("fold_count", plan.folds().len())?;
        payload.set_item("market_bytes", plan.market_bytes())?;
        payload.set_item("worker_count", 1)?;
        payload.set_item("worker_pool_creations", 0)?;
        payload.set_item("score_batches", stats.score_batches)?;
        payload.set_item("audit_batches", stats.audit_batches)?;
        payload.set_item("completed_tasks", stats.completed_tasks)?;
        payload.set_item("worker_generation", self.inner.generation())?;
        payload.set_item("max_bars", self.inner.plan().budget().max_bars)?;
        payload.set_item(
            "max_wall_time_ms",
            self.inner.plan().budget().max_wall_time_ms,
        )?;
        payload.set_item(
            "max_native_memory_bytes",
            self.inner.plan().budget().max_native_memory_bytes,
        )?;
        payload.set_item("max_workers", self.inner.plan().budget().max_workers)?;
        payload.set_item("native_target_no_order_arena", true)?;
        payload.set_item("closed", self.inner.closed())?;
        Ok(payload.unbind())
    }
}

fn hex_fingerprint(value: &[u8; 32]) -> String {
    value.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn parse_fingerprint(value: &str) -> PyResult<[u8; 32]> {
    if value.len() != 64 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "native WFO fingerprint must contain exactly 64 hexadecimal characters",
        ));
    }
    let mut bytes = [0_u8; 32];
    for (index, pair) in value.as_bytes().chunks_exact(2).enumerate() {
        let high = hex_digit(pair[0]).ok_or_else(|| {
            pyo3::exceptions::PyValueError::new_err("native WFO fingerprint is not hexadecimal")
        })?;
        let low = hex_digit(pair[1]).ok_or_else(|| {
            pyo3::exceptions::PyValueError::new_err("native WFO fingerprint is not hexadecimal")
        })?;
        bytes[index] = (high << 4) | low;
    }
    Ok(bytes)
}

const fn hex_digit(value: u8) -> Option<u8> {
    match value {
        b'0'..=b'9' => Some(value - b'0'),
        b'a'..=b'f' => Some(value - b'a' + 10),
        b'A'..=b'F' => Some(value - b'A' + 10),
        _ => None,
    }
}

/// Immutable, validated native strategy IR. It contains no Python callback or
/// object reference and may therefore be cloned into a detached Rust run.
#[pyclass]
struct NativeStrategyProgramCore {
    inner: strategy_ir::StrategyProgram,
}

#[pymethods]
impl NativeStrategyProgramCore {
    #[new]
    #[pyo3(signature = (
        kind,
        symbol_id=0,
        quantity=1.0,
        threshold=0.0,
        take_profit_pct=0.0,
        stop_loss_pct=0.0,
        dca_period=1,
        max_levels=1,
        max_instructions_per_bar=16,
        max_commands_per_bar=8,
        state_slots=3,
    ))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        kind: u8,
        symbol_id: u32,
        quantity: f64,
        threshold: f64,
        take_profit_pct: f64,
        stop_loss_pct: f64,
        dca_period: u32,
        max_levels: u32,
        max_instructions_per_bar: u16,
        max_commands_per_bar: u16,
        state_slots: u16,
    ) -> PyResult<Self> {
        let kind = strategy_ir::StrategyKind::try_from(kind)
            .map_err(|error| pyo3::exceptions::PyValueError::new_err(error.to_string()))?;
        let inner = strategy_ir::StrategyProgram::new(
            strategy_ir::STRATEGY_IR_VERSION,
            kind,
            quantbt_domain::ids::SymbolId(symbol_id),
            strategy_ir::StrategyParameters {
                quantity,
                threshold,
                take_profit_pct,
                stop_loss_pct,
                dca_period,
                max_levels,
            },
            strategy_ir::ProgramLimits {
                max_instructions_per_bar,
                max_commands_per_bar,
                state_slots,
            },
        )
        .map_err(|error| pyo3::exceptions::PyValueError::new_err(error.to_string()))?;
        Ok(Self { inner })
    }

    #[getter]
    fn version(&self) -> u16 {
        self.inner.version()
    }

    #[getter]
    fn kind(&self) -> &'static str {
        self.inner.kind().name()
    }

    #[getter]
    fn symbol_id(&self) -> u32 {
        self.inner.symbol().0
    }

    #[getter]
    fn parameter_width(&self) -> usize {
        strategy_ir::PARAMETER_WIDTH
    }

    #[getter]
    fn fingerprint(&self) -> String {
        self.inner.fingerprint_hex()
    }

    fn disassemble(&self) -> Vec<String> {
        self.inner.disassemble()
    }
}

#[pyclass]
struct FullReactiveSessionCore {
    inner: FullSession,
    total_fee: f64,
    total_turnover: f64,
    total_funding: f64,
    total_rejected: i64,
    total_canceled: i64,
    fill_cursor: u64,
    event_cursor: u64,
    order_delta_cursor: u64,
    position_delta_cursor: u64,
    last_positions: Vec<f64>,
}

impl FullReactiveSessionCore {
    fn wrap(inner: FullSession) -> Self {
        let last_positions = vec![0.0; inner.market.n_symbols];
        Self {
            inner,
            total_fee: 0.0,
            total_turnover: 0.0,
            total_funding: 0.0,
            total_rejected: 0,
            total_canceled: 0,
            fill_cursor: 0,
            event_cursor: 0,
            order_delta_cursor: 0,
            position_delta_cursor: 0,
            last_positions,
        }
    }
}

#[pymethods]
impl FullReactiveSessionCore {
    #[new]
    #[allow(clippy::too_many_arguments)]
    fn new(
        timestamps_ns: PyReadonlyArray1<'_, i64>,
        opens: PyReadonlyArray2<'_, f64>,
        highs: PyReadonlyArray2<'_, f64>,
        lows: PyReadonlyArray2<'_, f64>,
        closes: PyReadonlyArray2<'_, f64>,
        volumes: PyReadonlyArray2<'_, f64>,
        funding: PyReadonlyArray2<'_, f64>,
        funding_mask: PyReadonlyArray1<'_, bool>,
        contract_sizes: PyReadonlyArray1<'_, f64>,
        leverages: PyReadonlyArray1<'_, f64>,
        fee_rates: PyReadonlyArray1<'_, f64>,
        initial_capital: f64,
        maintenance_ratio: f64,
        slippage_rate: f64,
        use_funding: bool,
    ) -> PyResult<Self> {
        let prepared = FullPreparedMarketCore::new(
            timestamps_ns,
            opens,
            highs,
            lows,
            closes,
            volumes,
            funding,
            funding_mask,
        )?;
        let inner = FullSession::new(
            prepared.inner.clone(),
            contract_sizes.as_slice()?.to_vec(),
            leverages.as_slice()?.to_vec(),
            fee_rates.as_slice()?.to_vec(),
            initial_capital,
            maintenance_ratio,
            slippage_rate,
            use_funding,
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(Self::wrap(inner))
    }

    #[classmethod]
    #[allow(clippy::too_many_arguments)]
    fn from_prepared(
        _cls: &Bound<'_, PyType>,
        py: Python<'_>,
        prepared: Py<FullPreparedMarketCore>,
        contract_sizes: PyReadonlyArray1<'_, f64>,
        leverages: PyReadonlyArray1<'_, f64>,
        fee_rates: PyReadonlyArray1<'_, f64>,
        initial_capital: f64,
        maintenance_ratio: f64,
        slippage_rate: f64,
        use_funding: bool,
    ) -> PyResult<Self> {
        let market = prepared.borrow(py).inner.clone();
        let inner = FullSession::new(
            market,
            contract_sizes.as_slice()?.to_vec(),
            leverages.as_slice()?.to_vec(),
            fee_rates.as_slice()?.to_vec(),
            initial_capital,
            maintenance_ratio,
            slippage_rate,
            use_funding,
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(Self::wrap(inner))
    }

    fn set_event_contract(&mut self, contract_code: i64) -> PyResult<()> {
        self.inner
            .set_event_contract(contract_code)
            .map_err(pyo3::exceptions::PyValueError::new_err)
    }

    #[getter]
    fn event_contract_code(&self) -> i64 {
        self.inner.event_contract_code
    }

    fn step(
        &mut self,
        py: Python<'_>,
        bar_index: usize,
        command_codes: PyReadonlyArray2<'_, i64>,
        command_values: PyReadonlyArray2<'_, f64>,
        command_expiry: PyReadonlyArray1<'_, i64>,
    ) -> PyResult<Py<PyDict>> {
        let codes_shape = command_codes.shape();
        let values_shape = command_values.shape();
        if codes_shape.len() != 2 || codes_shape[1] != full::CODE_WIDTH {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "full command_codes must have shape (n, 16)",
            ));
        }
        if values_shape.len() != 2
            || values_shape[0] != codes_shape[0]
            || values_shape[1] != full::VALUE_WIDTH
        {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "full command_values must have shape (n, 3)",
            ));
        }
        if command_expiry.len() != codes_shape[0] {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "command_expiry must have length n",
            ));
        }
        let result = self
            .inner
            .step_with_mask(
                bar_index,
                command_codes.as_slice()?,
                command_values.as_slice()?,
                command_expiry.as_slice()?,
                codes_shape[0],
                self.inner.output_mask,
            )
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        full_step_payload(py, result)
    }

    /// Typed per-bar result for API 0.4 reactive callers. Scalar accounting is
    /// always present; projected vectors are `None` unless requested by the
    /// session output mask. The legacy dict-returning `step()` remains stable.
    fn step_typed(
        &mut self,
        py: Python<'_>,
        bar_index: usize,
        command_codes: PyReadonlyArray2<'_, i64>,
        command_values: PyReadonlyArray2<'_, f64>,
        command_expiry: PyReadonlyArray1<'_, i64>,
    ) -> PyResult<Py<FullStepResultCore>> {
        let codes_shape = command_codes.shape();
        let values_shape = command_values.shape();
        if codes_shape.len() != 2 || codes_shape[1] != full::CODE_WIDTH {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "full command_codes must have shape (n, 16)",
            ));
        }
        if values_shape.len() != 2
            || values_shape[0] != codes_shape[0]
            || values_shape[1] != full::VALUE_WIDTH
        {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "full command_values must have shape (n, 3)",
            ));
        }
        if command_expiry.len() != codes_shape[0] {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "command_expiry must have length n",
            ));
        }
        let mask = self.inner.output_mask;
        let result = self
            .inner
            .step_with_mask(
                bar_index,
                command_codes.as_slice()?,
                command_values.as_slice()?,
                command_expiry.as_slice()?,
                codes_shape[0],
                mask,
            )
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let changed_positions = self
            .inner
            .positions
            .iter()
            .zip(self.last_positions.iter())
            .filter(|(current, previous)| (*current - *previous).abs() > 1e-15)
            .count() as u64;
        self.last_positions.clone_from(&self.inner.positions);
        self.total_fee += result.fee;
        self.total_turnover += result.turnover;
        self.total_funding += result.funding;
        self.total_rejected += result.rejected_count;
        self.total_canceled += result.canceled_count;
        let projected = FullStepResultCore::from_result(
            result,
            mask,
            self.total_fee,
            self.total_turnover,
            self.total_funding,
            self.total_rejected,
            self.total_canceled,
            self.fill_cursor,
            self.event_cursor,
            self.order_delta_cursor,
            self.position_delta_cursor,
            changed_positions,
        );
        self.fill_cursor = projected.fill_end;
        self.event_cursor = projected.event_end;
        self.order_delta_cursor = projected.order_delta_end;
        self.position_delta_cursor = projected.position_delta_end;
        Py::new(py, projected)
    }

    /// Set reactive projection requirements without changing the stable
    /// constructor ABI.  Unknown bits are rejected instead of silently
    /// falling back to a wider allocation profile.
    fn set_output_mask(&mut self, output_mask: u8) -> PyResult<()> {
        if output_mask & !full::OUTPUT_ALL != 0 {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "full output mask contains unsupported bits",
            ));
        }
        self.inner.output_mask = output_mask;
        Ok(())
    }

    /// Return terminal active orders without advancing the market clock.
    fn terminal_active_orders(&self) -> Vec<Vec<f64>> {
        self.inner.terminal_active_order_rows()
    }

    fn reset(&mut self) {
        self.inner.reset();
        self.total_fee = 0.0;
        self.total_turnover = 0.0;
        self.total_funding = 0.0;
        self.total_rejected = 0;
        self.total_canceled = 0;
        self.fill_cursor = 0;
        self.event_cursor = 0;
        self.order_delta_cursor = 0;
        self.position_delta_cursor = 0;
        self.last_positions.fill(0.0);
    }

    fn order_arena_counters(&self) -> (usize, usize, u64, u64) {
        (
            self.inner.orders_len(),
            self.inner.orders_capacity(),
            self.inner.compaction_count,
            self.inner.terminal_orders_removed,
        )
    }

    fn release_step_buffer_capacity(&mut self, max_capacity: usize) {
        self.inner.release_resettable_scratch_capacity(max_capacity);
    }

    fn step_buffer_capacities(&self) -> (usize, usize, usize) {
        self.inner.step_buffer_capacities()
    }

    fn margin_recompute_count(&self) -> u64 {
        self.inner.margin_recompute_count()
    }

    fn engine_scan_counters(&self) -> (u64, u64, u64) {
        self.inner.engine_scan_counters()
    }

    /// Cold-path reset/derived-account observability for reusable reactive
    /// sessions. This does not materialize a result or execute accounting.
    fn session_diagnostics(&self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        let payload = PyDict::new(py);
        let versions = self.inner.derived_account_versions();
        payload.set_item("reset_manifest", "quantbt-native-reset-manifest-v1")?;
        payload.set_item("retained_output_policy", "owned_transfer_no_lease_v1")?;
        payload.set_item("session_reset_count", self.inner.session_reset_count())?;
        payload.set_item(
            "derived_account_cache_hits",
            self.inner.derived_account_cache_hits(),
        )?;
        payload.set_item(
            "derived_account_recomputes",
            self.inner.derived_account_recomputes(),
        )?;
        payload.set_item("mark_version", versions.mark)?;
        payload.set_item("position_version", versions.position)?;
        payload.set_item("wallet_version", versions.wallet)?;
        payload.set_item("reservation_version", versions.reservation)?;
        payload.set_item("fee_version", versions.fee)?;
        payload.set_item("funding_version", versions.funding)?;
        payload.set_item("risk_version", versions.risk)?;
        payload.set_item("instrument_version", versions.instrument)?;
        payload.set_item(
            "matching_candidate_capacity",
            self.inner.matching_candidate_capacity(),
        )?;
        payload.set_item(
            "order_arena_retired_slots",
            self.inner.order_arena_retired_slots(),
        )?;
        Ok(payload.unbind())
    }

    fn run_tape_score(
        &mut self,
        py: Python<'_>,
        command_ptr: PyReadonlyArray1<'_, i64>,
        command_codes: PyReadonlyArray2<'_, i64>,
        command_values: PyReadonlyArray2<'_, f64>,
        command_expiry: PyReadonlyArray1<'_, i64>,
    ) -> PyResult<Py<PyDict>> {
        let ptr = command_ptr.as_slice()?;
        let codes = command_codes.as_slice()?;
        let code_shape = command_codes.shape();
        let values = command_values.as_slice()?;
        let value_shape = command_values.shape();
        let expiry = command_expiry.as_slice()?;
        let output = py
            .detach(|| {
                run_full_tape(
                    &mut self.inner,
                    ptr,
                    codes,
                    code_shape,
                    values,
                    value_shape,
                    expiry,
                    false,
                )
            })
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let payload = PyDict::new(py);
        payload.set_item("final_equity", output.final_equity)?;
        payload.set_item("final_positions", output.final_positions)?;
        payload.set_item("total_fee", output.total_fee)?;
        payload.set_item("total_turnover", output.total_turnover)?;
        payload.set_item("total_funding", output.total_funding)?;
        payload.set_item("fill_count", output.fill_count)?;
        payload.set_item("event_count", output.event_count)?;
        payload.set_item("rejected_count", output.rejected_count)?;
        payload.set_item("canceled_count", output.canceled_count)?;
        payload.set_item("max_initial_margin", output.max_initial_margin)?;
        payload.set_item("max_maintenance_margin", output.max_maintenance_margin)?;
        payload.set_item("liquidated", output.liquidated)?;
        payload.set_item("liquidation_bar", output.liquidation_bar)?;
        payload.set_item("liquidation_reason", output.liquidation_reason)?;
        payload.set_item("bars", self.inner.market.n_bars)?;
        Ok(payload.unbind())
    }

    /// Retain dense account paths for metrics/research while deliberately
    /// omitting fill/event rows. The execution tape and scalar counters are
    /// identical to score and audit profiles.
    fn run_tape_compact(
        &mut self,
        py: Python<'_>,
        command_ptr: PyReadonlyArray1<'_, i64>,
        command_codes: PyReadonlyArray2<'_, i64>,
        command_values: PyReadonlyArray2<'_, f64>,
        command_expiry: PyReadonlyArray1<'_, i64>,
    ) -> PyResult<Py<PyDict>> {
        let ptr = command_ptr.as_slice()?;
        let codes = command_codes.as_slice()?;
        let code_shape = command_codes.shape();
        let values = command_values.as_slice()?;
        let value_shape = command_values.shape();
        let expiry = command_expiry.as_slice()?;
        let output = py
            .detach(|| {
                run_full_tape_profile(
                    &mut self.inner,
                    ptr,
                    codes,
                    code_shape,
                    values,
                    value_shape,
                    expiry,
                    quantbt_engine::StaticOutputProfile::Compact,
                )
            })
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let payload = PyDict::new(py);
        payload.set_item("equity", output.equity)?;
        payload.set_item("positions", output.positions)?;
        payload.set_item("fees", output.fees)?;
        payload.set_item("turnover", output.turnover)?;
        payload.set_item("funding", output.funding)?;
        payload.set_item("initial_margin", output.initial_margin)?;
        payload.set_item("maintenance_margin", output.maintenance_margin)?;
        payload.set_item("final_equity", output.final_equity)?;
        payload.set_item("final_positions", output.final_positions)?;
        payload.set_item("total_fee", output.total_fee)?;
        payload.set_item("total_turnover", output.total_turnover)?;
        payload.set_item("total_funding", output.total_funding)?;
        payload.set_item("fill_count", output.fill_count)?;
        payload.set_item("event_count", output.event_count)?;
        payload.set_item("rejected_count", output.rejected_count)?;
        payload.set_item("canceled_count", output.canceled_count)?;
        payload.set_item("max_initial_margin", output.max_initial_margin)?;
        payload.set_item("max_maintenance_margin", output.max_maintenance_margin)?;
        payload.set_item("liquidated", output.liquidated)?;
        payload.set_item("liquidation_bar", output.liquidation_bar)?;
        payload.set_item("liquidation_reason", output.liquidation_reason)?;
        payload.set_item("bars", self.inner.market.n_bars)?;
        Ok(payload.unbind())
    }

    fn run_tape_audit(
        &mut self,
        py: Python<'_>,
        command_ptr: PyReadonlyArray1<'_, i64>,
        command_codes: PyReadonlyArray2<'_, i64>,
        command_values: PyReadonlyArray2<'_, f64>,
        command_expiry: PyReadonlyArray1<'_, i64>,
    ) -> PyResult<Py<PyDict>> {
        let ptr = command_ptr.as_slice()?;
        let codes = command_codes.as_slice()?;
        let code_shape = command_codes.shape();
        let values = command_values.as_slice()?;
        let value_shape = command_values.shape();
        let expiry = command_expiry.as_slice()?;
        let output = py
            .detach(|| {
                run_full_tape(
                    &mut self.inner,
                    ptr,
                    codes,
                    code_shape,
                    values,
                    value_shape,
                    expiry,
                    true,
                )
            })
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let payload = PyDict::new(py);
        payload.set_item("equity", output.equity)?;
        payload.set_item("positions", output.positions)?;
        payload.set_item("fees", output.fees)?;
        payload.set_item("turnover", output.turnover)?;
        payload.set_item("funding", output.funding)?;
        payload.set_item("initial_margin", output.initial_margin)?;
        payload.set_item("maintenance_margin", output.maintenance_margin)?;
        payload.set_item("fill_bar", output.fill_bar)?;
        payload.set_item("fill_order_id", output.fill_order_id)?;
        payload.set_item("fill_symbol", output.fill_symbol)?;
        payload.set_item("fill_side", output.fill_side)?;
        payload.set_item("fill_qty", output.fill_qty)?;
        payload.set_item("fill_price", output.fill_price)?;
        payload.set_item("fill_fee", output.fill_fee)?;
        payload.set_item("fill_reason", output.fill_reason)?;
        payload.set_item("fill_ambiguity", output.fill_ambiguity)?;
        payload.set_item("event_bar", output.event_bar)?;
        payload.set_item("event_kind", output.event_kind)?;
        payload.set_item("event_status", output.event_status)?;
        payload.set_item("event_order_id", output.event_order_id)?;
        payload.set_item("event_target_id", output.event_target_id)?;
        payload.set_item("event_symbol", output.event_symbol)?;
        payload.set_item("event_reject_code", output.event_reject_code)?;
        payload.set_item("total_fee", output.total_fee)?;
        payload.set_item("total_turnover", output.total_turnover)?;
        payload.set_item("total_funding", output.total_funding)?;
        payload.set_item("fill_count", output.fill_count)?;
        payload.set_item("event_count", output.event_count)?;
        payload.set_item("rejected_count", output.rejected_count)?;
        payload.set_item("canceled_count", output.canceled_count)?;
        payload.set_item("max_initial_margin", output.max_initial_margin)?;
        payload.set_item("max_maintenance_margin", output.max_maintenance_margin)?;
        payload.set_item("liquidated", output.liquidated)?;
        payload.set_item("liquidation_bar", output.liquidation_bar)?;
        payload.set_item("liquidation_reason", output.liquidation_reason)?;
        payload.set_item("bars", self.inner.market.n_bars)?;
        Ok(payload.unbind())
    }

    /// Execute a bounded, declarative native strategy in one detached call.
    /// Python supplies only an immutable signal array and optional parameter
    /// row; the program compiles a typed ABI-0.5 command tape inside Rust.
    #[pyo3(signature = (program, signal, parameters=None))]
    fn run_ir_score(
        &mut self,
        py: Python<'_>,
        program: PyRef<'_, NativeStrategyProgramCore>,
        signal: PyReadonlyArray1<'_, f64>,
        parameters: Option<PyReadonlyArray1<'_, f64>>,
    ) -> PyResult<Py<PyDict>> {
        let signal = signal.as_slice()?.to_vec();
        let parameters = match parameters {
            Some(values) => Some(values.as_slice()?.to_vec()),
            None => None,
        };
        let program = program.inner.clone();
        let fingerprint = program.fingerprint_hex();
        let kind = program.kind().name();
        let closes = ir_close_column(&self.inner.market, program.symbol().0)?;
        let (output, command_count) = py
            .detach(|| {
                let tape = program
                    .compile_tape(&signal, &closes, parameters.as_deref())
                    .map_err(|error| error.to_string())?;
                let command_count = tape.command_count();
                let output = self.inner.run_typed_score(&tape)?;
                Ok::<_, String>((output, command_count))
            })
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        score_output_payload(
            py,
            output,
            self.inner.market.n_bars,
            &fingerprint,
            kind,
            command_count,
        )
    }

    /// Native IR compact profile. It shares the exact command compiler and
    /// lifecycle/accounting path with score/audit while retaining only paths.
    #[pyo3(signature = (program, signal, parameters=None))]
    fn run_ir_compact(
        &mut self,
        py: Python<'_>,
        program: PyRef<'_, NativeStrategyProgramCore>,
        signal: PyReadonlyArray1<'_, f64>,
        parameters: Option<PyReadonlyArray1<'_, f64>>,
    ) -> PyResult<Py<PyDict>> {
        let signal = signal.as_slice()?.to_vec();
        let parameters = match parameters {
            Some(values) => Some(values.as_slice()?.to_vec()),
            None => None,
        };
        let program = program.inner.clone();
        let fingerprint = program.fingerprint_hex();
        let kind = program.kind().name();
        let closes = ir_close_column(&self.inner.market, program.symbol().0)?;
        let (output, command_count) = py
            .detach(|| {
                let tape = program
                    .compile_tape(&signal, &closes, parameters.as_deref())
                    .map_err(|error| error.to_string())?;
                let command_count = tape.command_count();
                let output = self.inner.run_typed_compact(&tape)?;
                Ok::<_, String>((output, command_count))
            })
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        compact_output_payload(
            py,
            output,
            self.inner.market.n_bars,
            &fingerprint,
            kind,
            command_count,
        )
    }

    /// Native IR audit profile. Only this explicit route materializes the
    /// typed fill/event columns required for detailed trace comparison.
    #[pyo3(signature = (program, signal, parameters=None))]
    fn run_ir_audit(
        &mut self,
        py: Python<'_>,
        program: PyRef<'_, NativeStrategyProgramCore>,
        signal: PyReadonlyArray1<'_, f64>,
        parameters: Option<PyReadonlyArray1<'_, f64>>,
    ) -> PyResult<Py<PyDict>> {
        let signal = signal.as_slice()?.to_vec();
        let parameters = match parameters {
            Some(values) => Some(values.as_slice()?.to_vec()),
            None => None,
        };
        let program = program.inner.clone();
        let fingerprint = program.fingerprint_hex();
        let kind = program.kind().name();
        let closes = ir_close_column(&self.inner.market, program.symbol().0)?;
        let (output, command_count) = py
            .detach(|| {
                let tape = program
                    .compile_tape(&signal, &closes, parameters.as_deref())
                    .map_err(|error| error.to_string())?;
                let command_count = tape.command_count();
                let output = self.inner.run_typed_audit(&tape)?;
                Ok::<_, String>((output, command_count))
            })
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        audit_output_payload(
            py,
            output,
            self.inner.market.n_bars,
            &fingerprint,
            kind,
            command_count,
        )
    }

    /// Score a matrix of independent native-IR scenarios through one prepared
    /// immutable market. This is deliberately a scalar-only optimizer path:
    /// selected candidates are re-run through `run_ir_audit` after stable
    /// ranking instead of retaining fill/event rows for every trial.
    #[pyo3(signature = (program, signals, parameters=None, workers=1, chunk_size=256, fail_fast=false))]
    #[allow(clippy::too_many_arguments)]
    fn run_ir_batch_score(
        &self,
        py: Python<'_>,
        program: PyRef<'_, NativeStrategyProgramCore>,
        signals: PyReadonlyArray2<'_, f64>,
        parameters: Option<PyReadonlyArray2<'_, f64>>,
        workers: usize,
        chunk_size: usize,
        fail_fast: bool,
    ) -> PyResult<Py<PyDict>> {
        let signal_shape = signals.shape();
        if signal_shape.len() != 2 || signal_shape[1] != self.inner.market.n_bars {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "native IR signal matrix must have shape (scenarios, prepared_market_bars)",
            ));
        }
        let scenario_count = signal_shape[0];
        let signal_values = signals.as_slice()?.to_vec();
        let parameter_values = match parameters {
            Some(values) => {
                let shape = values.shape();
                if shape.len() != 2
                    || shape[0] != scenario_count
                    || shape[1] != strategy_ir::PARAMETER_WIDTH
                {
                    return Err(pyo3::exceptions::PyValueError::new_err(
                        "native IR parameter matrix must have shape (scenarios, 4)",
                    ));
                }
                Some(values.as_slice()?.to_vec())
            }
            None => None,
        };
        let program = Arc::new(program.inner.clone());
        let fingerprint = program.fingerprint_hex();
        let kind = program.kind().name();
        let template = batch::BatchTemplate::from_session(&self.inner, program)
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let market_bytes = template.market_bytes();
        let bars = self.inner.market.n_bars;
        let plan = batch::BatchPlan {
            workers,
            chunk_size,
            failure_policy: if fail_fast {
                batch::ScenarioFailurePolicy::FailFast
            } else {
                batch::ScenarioFailurePolicy::CollectPerScenarioErrors
            },
        };
        let result = py
            .detach(move || {
                let inputs = (0..scenario_count)
                    .map(|scenario| batch::ScenarioInput {
                        scenario: batch::ScenarioId(scenario as u32),
                        signal: &signal_values[scenario * bars..(scenario + 1) * bars],
                        parameters: parameter_values.as_ref().map(|values| {
                            &values[scenario * strategy_ir::PARAMETER_WIDTH
                                ..(scenario + 1) * strategy_ir::PARAMETER_WIDTH]
                        }),
                    })
                    .collect::<Vec<_>>();
                template.score_batch(&inputs, plan)
            })
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let actual_workers = workers.min(scenario_count).max(1);
        let payload =
            batch_output_payload(py, result, scenario_count, &fingerprint, kind, market_bytes)?;
        let bound = payload.bind(py);
        bound.set_item("requested_workers", workers)?;
        bound.set_item("actual_workers", actual_workers)?;
        bound.set_item("chunk_size", chunk_size)?;
        Ok(payload)
    }

    /// Score independent native-IR scenarios on one causal walk-forward OOS
    /// window. The supplied signals remain aligned to the full prepared tape;
    /// only ``test_start..test_end`` is sliced for execution and every
    /// scenario starts with a fresh account. This is a batch execution
    /// primitive, not a parameter-selection policy.
    #[pyo3(signature = (
        program,
        signals,
        fold_id,
        warmup_start,
        train_start,
        train_end,
        test_start,
        test_end,
        parameters=None,
        workers=1,
        chunk_size=256,
        fail_fast=false
    ))]
    #[allow(clippy::too_many_arguments)]
    fn run_ir_fold_batch_score(
        &self,
        py: Python<'_>,
        program: PyRef<'_, NativeStrategyProgramCore>,
        signals: PyReadonlyArray2<'_, f64>,
        fold_id: u32,
        warmup_start: u32,
        train_start: u32,
        train_end: u32,
        test_start: u32,
        test_end: u32,
        parameters: Option<PyReadonlyArray2<'_, f64>>,
        workers: usize,
        chunk_size: usize,
        fail_fast: bool,
    ) -> PyResult<Py<PyDict>> {
        let signal_shape = signals.shape();
        if signal_shape.len() != 2 || signal_shape[1] != self.inner.market.n_bars {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "native IR fold signal matrix must have shape (scenarios, prepared_market_bars)",
            ));
        }
        let fold = batch::FoldPlan {
            fold_id,
            warmup_start,
            train_start,
            train_end,
            test_start,
            test_end,
        }
        .validate(self.inner.market.n_bars)
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let scenario_count = signal_shape[0];
        let signal_values = signals.as_slice()?.to_vec();
        let parameter_values = match parameters {
            Some(values) => {
                let shape = values.shape();
                if shape.len() != 2
                    || shape[0] != scenario_count
                    || shape[1] != strategy_ir::PARAMETER_WIDTH
                {
                    return Err(pyo3::exceptions::PyValueError::new_err(
                        "native IR fold parameter matrix must have shape (scenarios, 4)",
                    ));
                }
                Some(values.as_slice()?.to_vec())
            }
            None => None,
        };
        let program = Arc::new(program.inner.clone());
        let fingerprint = program.fingerprint_hex();
        let kind = program.kind().name();
        let template = batch::BatchTemplate::from_session(&self.inner, program)
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let parent_market_bytes = template.market_bytes();
        let bars = self.inner.market.n_bars;
        let plan = batch::BatchPlan {
            workers,
            chunk_size,
            failure_policy: if fail_fast {
                batch::ScenarioFailurePolicy::FailFast
            } else {
                batch::ScenarioFailurePolicy::CollectPerScenarioErrors
            },
        };
        let result = py
            .detach(move || {
                let inputs = (0..scenario_count)
                    .map(|scenario| batch::ScenarioInput {
                        scenario: batch::ScenarioId(scenario as u32),
                        signal: &signal_values[scenario * bars..(scenario + 1) * bars],
                        parameters: parameter_values.as_ref().map(|values| {
                            &values[scenario * strategy_ir::PARAMETER_WIDTH
                                ..(scenario + 1) * strategy_ir::PARAMETER_WIDTH]
                        }),
                    })
                    .collect::<Vec<_>>();
                template.score_fold_batch(&inputs, fold, plan)
            })
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let market_window_bytes = result.market_window_bytes;
        let market_view_bytes = result.market_view_bytes;
        let source_market_bytes = result.source_market_bytes;
        let execution_bars = result.execution_bars;
        let payload = batch_output_payload(
            py,
            result.rows,
            scenario_count,
            &fingerprint,
            kind,
            parent_market_bytes,
        )?;
        let bound = payload.bind(py);
        bound.set_item("fold_id", fold.fold_id)?;
        bound.set_item("warmup_start", fold.warmup_start)?;
        bound.set_item("train_start", fold.train_start)?;
        bound.set_item("train_end", fold.train_end)?;
        bound.set_item("test_start", fold.test_start)?;
        bound.set_item("test_end", fold.test_end)?;
        bound.set_item("execution_bars", execution_bars)?;
        // Fold execution uses a local bar clock over the same immutable Rust
        // market allocation. The old materialized fold market is deliberately
        // not created here.
        bound.set_item("market_windows_created", 0)?;
        bound.set_item("fold_market_window_bytes", market_window_bytes)?;
        bound.set_item("fold_market_view_bytes", market_view_bytes)?;
        bound.set_item("source_market_bytes", source_market_bytes)?;
        bound.set_item("market_view_shared", true)?;
        bound.set_item("requested_workers", workers)?;
        bound.set_item("actual_workers", workers.min(scenario_count).max(1))?;
        bound.set_item("chunk_size", chunk_size)?;
        Ok(payload)
    }
}

fn ir_close_column(market: &FullMarketData, symbol: u32) -> PyResult<Vec<f64>> {
    let symbol = symbol as usize;
    if symbol >= market.n_symbols {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "native strategy IR symbol_id is outside prepared market",
        ));
    }
    Ok((0..market.n_bars)
        .map(|bar| market.closes[bar * market.n_symbols + symbol])
        .collect())
}

fn add_ir_metadata(
    payload: &Bound<'_, PyDict>,
    fingerprint: &str,
    kind: &str,
    command_count: usize,
) -> PyResult<()> {
    payload.set_item("strategy_ir_version", strategy_ir::STRATEGY_IR_VERSION)?;
    payload.set_item("strategy_ir_fingerprint", fingerprint)?;
    payload.set_item("strategy_ir_kind", kind)?;
    payload.set_item("strategy_ir_command_count", command_count)?;
    payload.set_item("python_callbacks", 0)?;
    payload.set_item("boundary_calls", 1)?;
    Ok(())
}

fn score_output_payload(
    py: Python<'_>,
    output: quantbt_engine::StaticTapeOutput,
    bars: usize,
    fingerprint: &str,
    kind: &str,
    command_count: usize,
) -> PyResult<Py<PyDict>> {
    let payload = PyDict::new(py);
    payload.set_item("final_equity", output.final_equity)?;
    payload.set_item("final_positions", output.final_positions)?;
    payload.set_item("total_fee", output.total_fee)?;
    payload.set_item("total_turnover", output.total_turnover)?;
    payload.set_item("total_funding", output.total_funding)?;
    payload.set_item("fill_count", output.fill_count)?;
    payload.set_item("event_count", output.event_count)?;
    payload.set_item("rejected_count", output.rejected_count)?;
    payload.set_item("canceled_count", output.canceled_count)?;
    payload.set_item("max_initial_margin", output.max_initial_margin)?;
    payload.set_item("max_maintenance_margin", output.max_maintenance_margin)?;
    payload.set_item("liquidated", output.liquidated)?;
    payload.set_item("liquidation_bar", output.liquidation_bar)?;
    payload.set_item("liquidation_reason", output.liquidation_reason)?;
    payload.set_item("bars", bars)?;
    add_ir_metadata(&payload, fingerprint, kind, command_count)?;
    Ok(payload.unbind())
}

/// Cold-path serialization for bounded dynamic workload provenance.  The
/// native fill/event output remains the authoritative execution trace; these
/// arrays explain target/package admission and never reconstruct execution in
/// Python.
fn add_workload_audit_retention(
    payload: &Bound<'_, PyDict>,
    retention: quantbt_engine::AuditRetentionV1,
) -> PyResult<()> {
    payload.set_item(
        "native_workload_audit_detail_truncated",
        retention.truncated(),
    )?;
    payload.set_item(
        "native_workload_audit_retained_rows",
        retention.retained_rows,
    )?;
    payload.set_item("native_workload_audit_dropped_rows", retention.dropped_rows)?;
    Ok(())
}

/// Materialize the bounded V2 package audit only on the cold audit/report
/// path. Score and compact results retain its exact scalar accounting in Rust
/// without allocating these NumPy arrays.
fn add_package_market_v2_audit_fields(
    py: Python<'_>,
    payload: &Bound<'_, PyDict>,
    audit: &execution::package::PackageMarketAuditV2,
) -> PyResult<()> {
    payload.set_item("package_v2_package_count", audit.package_count)?;
    payload.set_item(
        "package_v2_accepted_package_count",
        audit.accepted_package_count,
    )?;
    payload.set_item(
        "package_v2_residual_package_count",
        audit.residual_package_count,
    )?;
    payload.set_item(
        "package_v2_reservation_created_total",
        audit.reservation_created_total,
    )?;
    payload.set_item(
        "package_v2_reservation_consumed_total",
        audit.reservation_consumed_total,
    )?;
    payload.set_item(
        "package_v2_reservation_released_total",
        audit.reservation_released_total,
    )?;
    payload.set_item("package_v2_package_fee_total", audit.package_fee_total)?;
    payload.set_item(
        "package_v2_residual_gross_notional_total",
        audit.residual_gross_notional_total,
    )?;
    payload.set_item(
        "package_v2_outstanding_residual_gross_notional_total",
        audit.outstanding_residual_gross_notional_total,
    )?;
    payload.set_item(
        "package_v2_package_id",
        PyArray1::from_vec(py, audit.package_id.clone()),
    )?;
    payload.set_item(
        "package_v2_command_bar",
        PyArray1::from_vec(py, audit.command_bar.clone()),
    )?;
    payload.set_item(
        "package_v2_policy_code",
        PyArray1::from_vec(py, audit.policy_code.clone()),
    )?;
    payload.set_item(
        "package_v2_final_state_code",
        PyArray1::from_vec(py, audit.final_state_code.clone()),
    )?;
    payload.set_item(
        "package_v2_reservation_created",
        PyArray1::from_vec(py, audit.reservation_created.clone()),
    )?;
    payload.set_item(
        "package_v2_reservation_consumed",
        PyArray1::from_vec(py, audit.reservation_consumed.clone()),
    )?;
    payload.set_item(
        "package_v2_reservation_released",
        PyArray1::from_vec(py, audit.reservation_released.clone()),
    )?;
    payload.set_item(
        "package_v2_package_fee",
        PyArray1::from_vec(py, audit.package_fee.clone()),
    )?;
    payload.set_item(
        "package_v2_residual_gross_notional",
        PyArray1::from_vec(py, audit.residual_gross_notional.clone()),
    )?;
    payload.set_item(
        "package_v2_outstanding_residual_gross_notional",
        PyArray1::from_vec(py, audit.outstanding_residual_gross_notional.clone()),
    )?;
    payload.set_item(
        "package_v2_leg_package_id",
        PyArray1::from_vec(py, audit.leg_package_id.clone()),
    )?;
    payload.set_item(
        "package_v2_leg_index",
        PyArray1::from_vec(py, audit.leg_index.clone()),
    )?;
    payload.set_item(
        "package_v2_leg_order_id",
        PyArray1::from_vec(py, audit.leg_order_id.clone()),
    )?;
    payload.set_item(
        "package_v2_leg_symbol",
        PyArray1::from_vec(py, audit.leg_symbol.clone()),
    )?;
    payload.set_item(
        "package_v2_leg_requested_qty",
        PyArray1::from_vec(py, audit.leg_requested_qty.clone()),
    )?;
    payload.set_item(
        "package_v2_leg_filled_qty",
        PyArray1::from_vec(py, audit.leg_filled_qty.clone()),
    )?;
    payload.set_item(
        "package_v2_leg_compensation_qty",
        PyArray1::from_vec(py, audit.leg_compensation_qty.clone()),
    )?;
    payload.set_item(
        "package_v2_leg_accepted",
        PyArray1::from_vec(py, audit.leg_accepted.clone()),
    )?;
    payload.set_item(
        "package_v2_leg_rejection_code",
        PyArray1::from_vec(py, audit.leg_rejection_code.clone()),
    )?;
    payload.set_item(
        "package_v2_residual_package_id",
        PyArray1::from_vec(py, audit.residual_package_id.clone()),
    )?;
    payload.set_item(
        "package_v2_residual_leg_index",
        PyArray1::from_vec(py, audit.residual_leg_index.clone()),
    )?;
    payload.set_item(
        "package_v2_residual_symbol",
        PyArray1::from_vec(py, audit.residual_symbol.clone()),
    )?;
    payload.set_item(
        "package_v2_residual_qty",
        PyArray1::from_vec(py, audit.residual_qty.clone()),
    )?;
    payload.set_item(
        "package_v2_residual_notional",
        PyArray1::from_vec(py, audit.residual_notional.clone()),
    )?;
    payload.set_item(
        "package_v2_residual_reason_code",
        PyArray1::from_vec(py, audit.residual_reason_code.clone()),
    )?;
    payload.set_item(
        "package_v2_transition_package_id",
        PyArray1::from_vec(py, audit.transition_package_id.clone()),
    )?;
    payload.set_item(
        "package_v2_transition_code",
        PyArray1::from_vec(py, audit.transition_code.clone()),
    )?;
    Ok(())
}

fn add_native_workload_audit_fields(
    py: Python<'_>,
    payload: &Bound<'_, PyDict>,
    audit: &execution::NativeWorkloadAuditV1,
) -> PyResult<()> {
    match audit {
        execution::NativeWorkloadAuditV1::None => {
            payload.set_item("native_workload_audit_kind", "none")?;
            add_workload_audit_retention(payload, audit.detail_retention())?;
        }
        execution::NativeWorkloadAuditV1::PortfolioTarget(audit) => {
            payload.set_item("native_workload_audit_kind", "portfolio_target_market_v1")?;
            add_workload_audit_retention(payload, audit.detail_retention)?;
            payload.set_item("portfolio_target_decision_count", audit.decision_count)?;
            payload.set_item(
                "portfolio_target_rejected_decision_count",
                audit.rejected_decision_count,
            )?;
            payload.set_item(
                "portfolio_target_decision_bar",
                PyArray1::from_vec(py, audit.bar.clone()),
            )?;
            payload.set_item(
                "portfolio_target_requested_units",
                PyArray1::from_vec(py, audit.requested_units.clone()),
            )?;
            payload.set_item(
                "portfolio_target_accepted_units",
                PyArray1::from_vec(py, audit.accepted_units.clone()),
            )?;
            payload.set_item(
                "portfolio_target_rejection_code",
                PyArray1::from_vec(py, audit.rejection_code.clone()),
            )?;
        }
        execution::NativeWorkloadAuditV1::PackageAtomic(audit) => {
            payload.set_item("native_workload_audit_kind", "package_atomic_market_v1")?;
            add_workload_audit_retention(payload, audit.detail_retention)?;
            payload.set_item("package_command_bar", audit.command_bar)?;
            payload.set_item("package_id", audit.package_id)?;
            payload.set_item("package_attempted", audit.attempted)?;
            payload.set_item(
                "package_accepted",
                PyArray1::from_vec(py, audit.accepted.clone()),
            )?;
            payload.set_item(
                "package_rejection_code",
                PyArray1::from_vec(py, audit.rejection_code.clone()),
            )?;
            payload.set_item(
                "package_transition_code",
                PyArray1::from_vec(py, audit.transition_code.clone()),
            )?;
            payload.set_item("package_reserved_margin", audit.reserved_margin)?;
            payload.set_item("package_released_margin", audit.released_margin)?;
            payload.set_item("package_fee", audit.package_fee)?;
            payload.set_item("package_residual_notional", audit.residual_notional)?;
        }
        execution::NativeWorkloadAuditV1::PackageMarketV2(audit) => {
            payload.set_item("native_workload_audit_kind", "package_market_v2")?;
            add_workload_audit_retention(payload, audit.detail_retention)?;
            add_package_market_v2_audit_fields(py, payload, audit)?;
        }
    }
    Ok(())
}

fn add_native_workload_audit_core_fields(
    py: Python<'_>,
    payload: &Bound<'_, PyDict>,
    audit: &NativeWorkloadAuditFieldsCore,
) -> PyResult<()> {
    payload.set_item("native_workload_audit_kind", audit.kind())?;
    add_workload_audit_retention(payload, audit.retention())?;
    match audit {
        NativeWorkloadAuditFieldsCore::None => {}
        NativeWorkloadAuditFieldsCore::DirectTarget {
            target_kind,
            timing,
            invalid_target_policy,
            decision_count,
            rejected_decision_count,
            bar,
            symbol,
            requested_units,
            accepted_units,
            rejection_code,
            rejected_by_bar,
            reject_code_by_bar,
            ..
        } => {
            payload.set_item("direct_target_kind", *target_kind)?;
            payload.set_item("direct_target_timing", *timing)?;
            payload.set_item(
                "direct_target_invalid_target_policy",
                *invalid_target_policy,
            )?;
            payload.set_item("direct_target_decision_count", *decision_count)?;
            payload.set_item(
                "direct_target_rejected_decision_count",
                *rejected_decision_count,
            )?;
            payload.set_item("direct_target_decision_bar", bar.clone_ref(py))?;
            payload.set_item("direct_target_decision_symbol", symbol.clone_ref(py))?;
            payload.set_item(
                "direct_target_requested_units",
                requested_units.clone_ref(py),
            )?;
            payload.set_item("direct_target_accepted_units", accepted_units.clone_ref(py))?;
            payload.set_item("direct_target_rejection_code", rejection_code.clone_ref(py))?;
            if let Some(values) = rejected_by_bar {
                payload.set_item("direct_target_rejected_by_bar", values.clone_ref(py))?;
            }
            if let Some(values) = reject_code_by_bar {
                payload.set_item("direct_target_reject_code_by_bar", values.clone_ref(py))?;
            }
        }
        NativeWorkloadAuditFieldsCore::PortfolioTarget {
            decision_count,
            rejected_decision_count,
            bar,
            requested_units,
            accepted_units,
            rejection_code,
            ..
        } => {
            payload.set_item("portfolio_target_decision_count", *decision_count)?;
            payload.set_item(
                "portfolio_target_rejected_decision_count",
                *rejected_decision_count,
            )?;
            payload.set_item("portfolio_target_decision_bar", bar.clone_ref(py))?;
            payload.set_item(
                "portfolio_target_requested_units",
                requested_units.clone_ref(py),
            )?;
            payload.set_item(
                "portfolio_target_accepted_units",
                accepted_units.clone_ref(py),
            )?;
            payload.set_item(
                "portfolio_target_rejection_code",
                rejection_code.clone_ref(py),
            )?;
        }
        NativeWorkloadAuditFieldsCore::PackageAtomic {
            command_bar,
            package_id,
            attempted,
            reserved_margin,
            released_margin,
            package_fee,
            residual_notional,
            accepted,
            rejection_code,
            transition_code,
            ..
        } => {
            payload.set_item("package_command_bar", *command_bar)?;
            payload.set_item("package_id", *package_id)?;
            payload.set_item("package_attempted", *attempted)?;
            payload.set_item("package_accepted", accepted.clone_ref(py))?;
            payload.set_item("package_rejection_code", rejection_code.clone_ref(py))?;
            payload.set_item("package_transition_code", transition_code.clone_ref(py))?;
            payload.set_item("package_reserved_margin", *reserved_margin)?;
            payload.set_item("package_released_margin", *released_margin)?;
            payload.set_item("package_fee", *package_fee)?;
            payload.set_item("package_residual_notional", *residual_notional)?;
        }
        NativeWorkloadAuditFieldsCore::PackageMarketV2(audit) => {
            add_package_market_v2_audit_fields(py, payload, audit)?;
        }
    }
    Ok(())
}

fn compact_output_payload(
    py: Python<'_>,
    output: quantbt_engine::StaticTapeOutput,
    bars: usize,
    fingerprint: &str,
    kind: &str,
    command_count: usize,
) -> PyResult<Py<PyDict>> {
    let payload = score_output_payload(py, output.clone(), bars, fingerprint, kind, command_count)?;
    let bound = payload.bind(py);
    bound.set_item("equity", output.equity)?;
    bound.set_item("positions", output.positions)?;
    bound.set_item("fees", output.fees)?;
    bound.set_item("turnover", output.turnover)?;
    bound.set_item("funding", output.funding)?;
    bound.set_item("initial_margin", output.initial_margin)?;
    bound.set_item("maintenance_margin", output.maintenance_margin)?;
    Ok(payload)
}

fn batch_output_payload(
    py: Python<'_>,
    result: batch::BatchResult,
    scenario_count: usize,
    fingerprint: &str,
    kind: &str,
    market_bytes: usize,
) -> PyResult<Py<PyDict>> {
    let payload = PyDict::new(py);
    let scenario_id = result
        .rows
        .iter()
        .map(|row| row.score.scenario.0)
        .collect::<Vec<_>>();
    let status = result
        .rows
        .iter()
        .map(|row| row.status.code())
        .collect::<Vec<_>>();
    let final_equity = result
        .rows
        .iter()
        .map(|row| row.score.final_equity)
        .collect::<Vec<_>>();
    let total_fee = result
        .rows
        .iter()
        .map(|row| row.score.total_fee)
        .collect::<Vec<_>>();
    let total_funding = result
        .rows
        .iter()
        .map(|row| row.score.total_funding)
        .collect::<Vec<_>>();
    let turnover = result
        .rows
        .iter()
        .map(|row| row.score.turnover)
        .collect::<Vec<_>>();
    let fill_count = result
        .rows
        .iter()
        .map(|row| row.score.fill_count)
        .collect::<Vec<_>>();
    let rejected_count = result
        .rows
        .iter()
        .map(|row| row.score.rejected_count)
        .collect::<Vec<_>>();
    let liquidated = result
        .rows
        .iter()
        .map(|row| row.score.liquidated)
        .collect::<Vec<_>>();
    let errors = result
        .rows
        .iter()
        .map(|row| row.error.clone())
        .collect::<Vec<_>>();
    payload.set_item("scenario_id", PyArray1::from_vec(py, scenario_id))?;
    payload.set_item("status", PyArray1::from_vec(py, status))?;
    payload.set_item("final_equity", PyArray1::from_vec(py, final_equity))?;
    payload.set_item("total_fee", PyArray1::from_vec(py, total_fee))?;
    payload.set_item("total_funding", PyArray1::from_vec(py, total_funding))?;
    payload.set_item("turnover", PyArray1::from_vec(py, turnover))?;
    payload.set_item("fill_count", PyArray1::from_vec(py, fill_count))?;
    payload.set_item("rejected_count", PyArray1::from_vec(py, rejected_count))?;
    payload.set_item("liquidated", PyArray1::from_vec(py, liquidated))?;
    payload.set_item("error", errors)?;
    payload.set_item("scenario_count", scenario_count)?;
    payload.set_item("shared_market_copies_per_scenario", 0)?;
    payload.set_item("shared_market_bytes", market_bytes)?;
    payload.set_item("audit_materialized", false)?;
    add_ir_metadata(&payload, fingerprint, kind, 0)?;
    Ok(payload.unbind())
}

fn audit_output_payload(
    py: Python<'_>,
    output: quantbt_engine::StaticTapeOutput,
    bars: usize,
    fingerprint: &str,
    kind: &str,
    command_count: usize,
) -> PyResult<Py<PyDict>> {
    let payload =
        compact_output_payload(py, output.clone(), bars, fingerprint, kind, command_count)?;
    let bound = payload.bind(py);
    bound.set_item("fill_bar", output.fill_bar)?;
    bound.set_item("fill_order_id", output.fill_order_id)?;
    bound.set_item("fill_symbol", output.fill_symbol)?;
    bound.set_item("fill_side", output.fill_side)?;
    bound.set_item("fill_qty", output.fill_qty)?;
    bound.set_item("fill_price", output.fill_price)?;
    bound.set_item("fill_fee", output.fill_fee)?;
    bound.set_item("fill_reason", output.fill_reason)?;
    bound.set_item("fill_ambiguity", output.fill_ambiguity)?;
    bound.set_item("event_bar", output.event_bar)?;
    bound.set_item("event_kind", output.event_kind)?;
    bound.set_item("event_status", output.event_status)?;
    bound.set_item("event_order_id", output.event_order_id)?;
    bound.set_item("event_target_id", output.event_target_id)?;
    bound.set_item("event_symbol", output.event_symbol)?;
    bound.set_item("event_reject_code", output.event_reject_code)?;
    Ok(payload)
}

fn full_step_payload(py: Python<'_>, result: full::FullStepResult) -> PyResult<Py<PyDict>> {
    let payload = PyDict::new(py);
    payload.set_item("equity", result.equity)?;
    payload.set_item("positions", result.positions)?;
    payload.set_item("fee", result.fee)?;
    payload.set_item("turnover", result.turnover)?;
    payload.set_item("funding", result.funding)?;
    payload.set_item("initial_margin", result.initial_margin)?;
    payload.set_item("maintenance_margin", result.maintenance_margin)?;
    payload.set_item("liquidated", result.liquidated)?;
    payload.set_item("liquidation_bar", result.liquidation_bar)?;
    payload.set_item("liquidation_reason", result.liquidation_reason)?;
    payload.set_item("fills", result.fills)?;
    payload.set_item("events", result.events)?;
    payload.set_item("active_orders", result.active_orders)?;
    payload.set_item("rejected_count", result.rejected_count)?;
    payload.set_item("canceled_count", result.canceled_count)?;
    payload.set_item("fill_count", result.fill_count)?;
    payload.set_item("event_count", result.event_count)?;
    Ok(payload.unbind())
}

#[allow(clippy::too_many_arguments)]
fn build_execution_template(
    market: Arc<FullMarketData>,
    contract_sizes: Vec<f64>,
    leverages: Vec<f64>,
    fee_rates: Vec<f64>,
    initial_capital: f64,
    maintenance_ratio: f64,
    slippage_rate: f64,
    use_funding: bool,
    event_contract_code: i64,
) -> Result<Arc<execution::NativeExecutionTemplateV1>, String> {
    let instruments =
        execution::InstrumentTableV1::sequential(contract_sizes, leverages, fee_rates)?;
    let account = execution::AccountModelV1::new(
        initial_capital,
        maintenance_ratio,
        slippage_rate,
        use_funding,
    )?;
    let contract = execution::ExecutionContractV1::new(event_contract_code)?;
    Ok(Arc::new(execution::NativeExecutionTemplateV1::new(
        market,
        instruments,
        account,
        contract,
    )?))
}

#[allow(clippy::too_many_arguments)]
fn build_command_request_from_template(
    template: Arc<execution::NativeExecutionTemplateV1>,
    ptr: &[i64],
    codes: &[i64],
    codes_shape: &[usize],
    values: &[f64],
    values_shape: &[usize],
    expiry: &[i64],
    output_profile: u8,
) -> Result<execution::NativeExecutionRequestV1, String> {
    let tape = translate_full_command_tape(
        template.bar_count(),
        template.n_symbols(),
        ptr,
        codes,
        codes_shape,
        values,
        values_shape,
        expiry,
    )?;
    let output = execution::NativeOutputProfileV1::try_from(output_profile)?;
    execution::NativeExecutionRequestV1::from_template(
        template,
        output,
        execution::WorkloadPayloadV1::CommandTape(tape),
    )
}

#[allow(clippy::too_many_arguments)]
fn build_command_request(
    market: Arc<FullMarketData>,
    ptr: &[i64],
    codes: &[i64],
    codes_shape: &[usize],
    values: &[f64],
    values_shape: &[usize],
    expiry: &[i64],
    contract_sizes: Vec<f64>,
    leverages: Vec<f64>,
    fee_rates: Vec<f64>,
    initial_capital: f64,
    maintenance_ratio: f64,
    slippage_rate: f64,
    use_funding: bool,
    event_contract_code: i64,
    output_profile: u8,
) -> Result<execution::NativeExecutionRequestV1, String> {
    let template = build_execution_template(
        market,
        contract_sizes,
        leverages,
        fee_rates,
        initial_capital,
        maintenance_ratio,
        slippage_rate,
        use_funding,
        event_contract_code,
    )?;
    build_command_request_from_template(
        template,
        ptr,
        codes,
        codes_shape,
        values,
        values_shape,
        expiry,
        output_profile,
    )
}

fn direct_target_output_bytes(result: &execution::target::DirectTargetExecutionResultV1) -> usize {
    let common = match &result.output {
        quantbt_engine::NativeExecutionOutputV1::Score(output) => score_output_bytes(output),
        quantbt_engine::NativeExecutionOutputV1::Compact(output) => compact_output_bytes(output),
        quantbt_engine::NativeExecutionOutputV1::Audit(output) => audit_output_bytes(output),
    };
    common
        .saturating_add(bytes_i64(&result.target_audit.bar))
        .saturating_add(bytes_i64(&result.target_audit.symbol))
        .saturating_add(bytes_f64(&result.target_audit.requested_units))
        .saturating_add(bytes_f64(&result.target_audit.accepted_units))
        .saturating_add(bytes_i64(&result.target_audit.rejection_code))
        .saturating_add(result.rejected_by_bar.as_deref().map_or(0, bytes_i64))
        .saturating_add(result.reject_code_by_bar.as_deref().map_or(0, bytes_i64))
}

fn direct_target_metadata(
    result: &execution::target::DirectTargetExecutionResultV1,
    output_bytes: usize,
) -> NativeOutputMetadataCore {
    let retention = result.output.detail_retention();
    NativeOutputMetadataCore {
        native_result_version: execution::NATIVE_RESULT_VERSION_V2,
        output_version: result.output.score().output_version,
        request_version: execution::target::DIRECT_TARGET_REQUEST_VERSION_V1,
        protocol_version: execution::NATIVE_EXECUTION_PROTOCOL_VERSION_V1,
        request_fingerprint: result.request_fingerprint_hex(),
        template_fingerprint: result.template_fingerprint_hex(),
        contract_bundle_hash: result.contract_bundle_hash_hex(),
        terminal_fingerprint: result.terminal_fingerprint_hex(),
        workload_kind: result.target_kind.name(),
        runtime_class: "rust_direct_target_v1",
        account_authority: "rust_linear_close_target_v2",
        execution_model_id: "close_target_v2_same_close",
        metric_contract_version: result.output.score().metrics_v2.metric_contract_version,
        output_profile: match result.output.profile() {
            quantbt_engine::StaticOutputProfile::Score => "score",
            quantbt_engine::StaticOutputProfile::Compact => "compact",
            quantbt_engine::StaticOutputProfile::Audit => "audit",
        },
        command_count: result.command_count,
        bars: result.bar_count,
        execution_generation: 0,
        runner_run_count: 1,
        detail_truncated: retention.truncated(),
        retained_rows: retention.retained_rows as u64,
        dropped_rows: retention.dropped_rows as u64,
        output_bytes,
    }
}

/// Explicit cold-path mapping for direct target output. It exists separately
/// from the command request adapter because the direct route has no
/// ``NativeExecutionResultV1`` command/lifecycle envelope to reconstruct.
fn direct_target_output_payload(
    py: Python<'_>,
    result: execution::target::DirectTargetExecutionResultV1,
) -> PyResult<Py<PyDict>> {
    let output_bytes = direct_target_output_bytes(&result);
    let metadata = direct_target_metadata(&result, output_bytes);
    let profile = result.output.profile();
    let metrics = NativeMetricFieldsCore::from_native(result.output.score());
    let target_kind = result.target_kind.name();
    let timing = result.timing;
    let invalid_target_policy = result.invalid_target_policy.name();
    let command_count = result.command_count;
    let target_audit = result.target_audit;
    let rejected_by_bar = result.rejected_by_bar;
    let reject_code_by_bar = result.reject_code_by_bar;
    let output = result.output.into_legacy_static();
    let payload = PyDict::new(py);
    payload.set_item("final_equity", output.final_equity)?;
    payload.set_item("final_positions", output.final_positions)?;
    payload.set_item("total_fee", output.total_fee)?;
    payload.set_item("total_turnover", output.total_turnover)?;
    payload.set_item("total_funding", output.total_funding)?;
    payload.set_item("fill_count", output.fill_count)?;
    payload.set_item("event_count", output.event_count)?;
    payload.set_item("rejected_count", output.rejected_count)?;
    payload.set_item("canceled_count", output.canceled_count)?;
    payload.set_item("max_initial_margin", output.max_initial_margin)?;
    payload.set_item("max_maintenance_margin", output.max_maintenance_margin)?;
    payload.set_item("liquidated", output.liquidated)?;
    payload.set_item("liquidation_bar", output.liquidation_bar)?;
    payload.set_item("liquidation_reason", output.liquidation_reason)?;
    add_typed_output_metadata(&payload, &metadata)?;
    add_metric_fields(&payload, &metrics)?;
    payload.set_item("native_direct_target", true)?;
    payload.set_item("native_target_no_order_arena", true)?;
    payload.set_item("direct_target_kind", target_kind)?;
    payload.set_item("direct_target_timing", timing)?;
    payload.set_item("direct_target_invalid_target_policy", invalid_target_policy)?;
    payload.set_item("direct_target_command_count", command_count)?;
    payload.set_item(
        "direct_target_report_trade_count",
        result.report_trade_count,
    )?;

    if matches!(
        profile,
        quantbt_engine::StaticOutputProfile::Compact | quantbt_engine::StaticOutputProfile::Audit
    ) {
        payload.set_item("equity", output.equity)?;
        payload.set_item("positions", output.positions)?;
        payload.set_item("fees", output.fees)?;
        payload.set_item("turnover", output.turnover)?;
        payload.set_item("funding", output.funding)?;
        payload.set_item("initial_margin", output.initial_margin)?;
        payload.set_item("maintenance_margin", output.maintenance_margin)?;
        if let Some(values) = rejected_by_bar {
            payload.set_item("direct_target_rejected_by_bar", values)?;
        }
        if let Some(values) = reject_code_by_bar {
            payload.set_item("direct_target_reject_code_by_bar", values)?;
        }
    }
    if matches!(profile, quantbt_engine::StaticOutputProfile::Audit) {
        payload.set_item("fill_bar", output.fill_bar)?;
        payload.set_item("fill_order_id", output.fill_order_id)?;
        payload.set_item("fill_symbol", output.fill_symbol)?;
        payload.set_item("fill_side", output.fill_side)?;
        payload.set_item("fill_qty", output.fill_qty)?;
        payload.set_item("fill_price", output.fill_price)?;
        payload.set_item("fill_fee", output.fill_fee)?;
        payload.set_item("fill_reason", output.fill_reason)?;
        payload.set_item("fill_ambiguity", output.fill_ambiguity)?;
        payload.set_item("event_bar", output.event_bar)?;
        payload.set_item("event_kind", output.event_kind)?;
        payload.set_item("event_status", output.event_status)?;
        payload.set_item("event_order_id", output.event_order_id)?;
        payload.set_item("event_target_id", output.event_target_id)?;
        payload.set_item("event_symbol", output.event_symbol)?;
        payload.set_item("event_reject_code", output.event_reject_code)?;
        add_workload_audit_retention(&payload, target_audit.detail_retention)?;
        payload.set_item("native_workload_audit_kind", "direct_target_v1")?;
        payload.set_item("direct_target_decision_count", target_audit.decision_count)?;
        payload.set_item(
            "direct_target_rejected_decision_count",
            target_audit.rejected_decision_count,
        )?;
        payload.set_item("direct_target_decision_bar", target_audit.bar)?;
        payload.set_item("direct_target_decision_symbol", target_audit.symbol)?;
        payload.set_item(
            "direct_target_requested_units",
            target_audit.requested_units,
        )?;
        payload.set_item("direct_target_accepted_units", target_audit.accepted_units)?;
        payload.set_item("direct_target_rejection_code", target_audit.rejection_code)?;
    }
    Ok(payload.unbind())
}

fn shared_portfolio_target_output_bytes(
    result: &execution::target::SharedPortfolioExecutionResultV1,
) -> usize {
    let common = match &result.output {
        quantbt_engine::NativeExecutionOutputV1::Score(output) => score_output_bytes(output),
        quantbt_engine::NativeExecutionOutputV1::Compact(output) => compact_output_bytes(output),
        quantbt_engine::NativeExecutionOutputV1::Audit(output) => audit_output_bytes(output),
    };
    let attribution = &result.attribution;
    common
        .saturating_add(bytes_i64(&result.target_audit.bar))
        .saturating_add(bytes_i64(&result.target_audit.symbol))
        .saturating_add(bytes_f64(&result.target_audit.requested_units))
        .saturating_add(bytes_f64(&result.target_audit.accepted_units))
        .saturating_add(bytes_i64(&result.target_audit.rejection_code))
        .saturating_add(bytes_f64(&attribution.realized_pnl))
        .saturating_add(bytes_f64(&attribution.unrealized_pnl))
        .saturating_add(bytes_f64(&attribution.mark_to_market_pnl))
        .saturating_add(bytes_f64(&attribution.fees))
        .saturating_add(bytes_f64(&attribution.slippage))
        .saturating_add(bytes_f64(&attribution.funding))
        .saturating_add(bytes_f64(&attribution.liquidation_loss))
        .saturating_add(bytes_f64(&attribution.turnover))
        .saturating_add(bytes_f64(&attribution.final_exposure))
        .saturating_add(bytes_f64(&attribution.final_initial_margin))
        .saturating_add(result.rejected_by_bar.as_deref().map_or(0, bytes_i64))
        .saturating_add(result.reject_code_by_bar.as_deref().map_or(0, bytes_i64))
}

fn shared_portfolio_target_metadata(
    result: &execution::target::SharedPortfolioExecutionResultV1,
    output_bytes: usize,
) -> NativeOutputMetadataCore {
    let retention = result.output.detail_retention();
    NativeOutputMetadataCore {
        native_result_version: execution::NATIVE_RESULT_VERSION_V2,
        output_version: result.output.score().output_version,
        request_version: 1,
        protocol_version: execution::NATIVE_EXECUTION_PROTOCOL_VERSION_V1,
        request_fingerprint: result.request_fingerprint_hex(),
        template_fingerprint: result.template_fingerprint_hex(),
        contract_bundle_hash: result.contract_bundle_hash_hex(),
        terminal_fingerprint: result.terminal_fingerprint_hex(),
        workload_kind: result.target_kind.name(),
        runtime_class: "rust_shared_portfolio_target_v1",
        account_authority: "rust_linear_shared_portfolio_close_target_v2",
        execution_model_id: "close_target_v2_same_close",
        metric_contract_version: result.output.score().metrics_v2.metric_contract_version,
        output_profile: match result.output.profile() {
            quantbt_engine::StaticOutputProfile::Score => "score",
            quantbt_engine::StaticOutputProfile::Compact => "compact",
            quantbt_engine::StaticOutputProfile::Audit => "audit",
        },
        command_count: result.command_count,
        bars: result.bar_count,
        execution_generation: 0,
        runner_run_count: 1,
        detail_truncated: retention.truncated(),
        retained_rows: retention.retained_rows as u64,
        dropped_rows: retention.dropped_rows as u64,
        output_bytes,
    }
}

/// Cold-path projection of the shared-account portfolio result.  Attribution
/// is emitted only for compact/audit retention, keeping score as a flat scalar
/// workload without per-symbol Python objects or DataFrames.
fn shared_portfolio_target_output_payload(
    py: Python<'_>,
    result: execution::target::SharedPortfolioExecutionResultV1,
) -> PyResult<Py<PyDict>> {
    let output_bytes = shared_portfolio_target_output_bytes(&result);
    let metadata = shared_portfolio_target_metadata(&result, output_bytes);
    let profile = result.output.profile();
    let metrics = NativeMetricFieldsCore::from_native(result.output.score());
    let target_kind = result.target_kind.name();
    let timing = result.timing;
    let invalid_target_policy = result.invalid_target_policy.name();
    let admission_policy = result.admission_policy.name();
    let command_count = result.command_count;
    let target_audit = result.target_audit;
    let attribution = result.attribution;
    let rejected_by_bar = result.rejected_by_bar;
    let reject_code_by_bar = result.reject_code_by_bar;
    let output = result.output.into_legacy_static();
    let payload = PyDict::new(py);
    payload.set_item("final_equity", output.final_equity)?;
    payload.set_item("final_positions", output.final_positions)?;
    payload.set_item("total_fee", output.total_fee)?;
    payload.set_item("total_turnover", output.total_turnover)?;
    payload.set_item("total_funding", output.total_funding)?;
    payload.set_item("fill_count", output.fill_count)?;
    payload.set_item("event_count", output.event_count)?;
    payload.set_item("rejected_count", output.rejected_count)?;
    payload.set_item("canceled_count", output.canceled_count)?;
    payload.set_item("max_initial_margin", output.max_initial_margin)?;
    payload.set_item("max_maintenance_margin", output.max_maintenance_margin)?;
    payload.set_item("liquidated", output.liquidated)?;
    payload.set_item("liquidation_bar", output.liquidation_bar)?;
    payload.set_item("liquidation_reason", output.liquidation_reason)?;
    add_typed_output_metadata(&payload, &metadata)?;
    add_metric_fields(&payload, &metrics)?;
    payload.set_item("native_shared_portfolio_target", true)?;
    payload.set_item("native_portfolio_shared_account", true)?;
    payload.set_item("native_target_no_order_arena", true)?;
    payload.set_item("portfolio_target_kind", target_kind)?;
    payload.set_item("portfolio_target_timing", timing)?;
    payload.set_item("portfolio_invalid_target_policy", invalid_target_policy)?;
    payload.set_item("portfolio_admission_policy", admission_policy)?;
    payload.set_item("portfolio_target_command_count", command_count)?;

    if matches!(
        profile,
        quantbt_engine::StaticOutputProfile::Compact | quantbt_engine::StaticOutputProfile::Audit
    ) {
        payload.set_item("equity", output.equity)?;
        payload.set_item("positions", output.positions)?;
        payload.set_item("fees", output.fees)?;
        payload.set_item("turnover", output.turnover)?;
        payload.set_item("funding", output.funding)?;
        payload.set_item("initial_margin", output.initial_margin)?;
        payload.set_item("maintenance_margin", output.maintenance_margin)?;
        payload.set_item(
            "portfolio_symbol_realized_pnl",
            PyArray1::from_vec(py, attribution.realized_pnl),
        )?;
        payload.set_item(
            "portfolio_symbol_unrealized_pnl",
            PyArray1::from_vec(py, attribution.unrealized_pnl),
        )?;
        payload.set_item(
            "portfolio_symbol_mark_to_market_pnl",
            PyArray1::from_vec(py, attribution.mark_to_market_pnl),
        )?;
        payload.set_item(
            "portfolio_symbol_fee",
            PyArray1::from_vec(py, attribution.fees),
        )?;
        payload.set_item(
            "portfolio_symbol_slippage",
            PyArray1::from_vec(py, attribution.slippage),
        )?;
        payload.set_item(
            "portfolio_symbol_funding",
            PyArray1::from_vec(py, attribution.funding),
        )?;
        payload.set_item(
            "portfolio_symbol_liquidation_loss",
            PyArray1::from_vec(py, attribution.liquidation_loss),
        )?;
        payload.set_item(
            "portfolio_symbol_turnover",
            PyArray1::from_vec(py, attribution.turnover),
        )?;
        payload.set_item(
            "portfolio_symbol_final_exposure",
            PyArray1::from_vec(py, attribution.final_exposure),
        )?;
        payload.set_item(
            "portfolio_symbol_final_initial_margin",
            PyArray1::from_vec(py, attribution.final_initial_margin),
        )?;
        if let Some(values) = rejected_by_bar {
            payload.set_item("portfolio_target_rejected_by_bar", values)?;
        }
        if let Some(values) = reject_code_by_bar {
            payload.set_item("portfolio_target_reject_code_by_bar", values)?;
        }
    }
    if matches!(profile, quantbt_engine::StaticOutputProfile::Audit) {
        payload.set_item("fill_bar", output.fill_bar)?;
        payload.set_item("fill_order_id", output.fill_order_id)?;
        payload.set_item("fill_symbol", output.fill_symbol)?;
        payload.set_item("fill_side", output.fill_side)?;
        payload.set_item("fill_qty", output.fill_qty)?;
        payload.set_item("fill_price", output.fill_price)?;
        payload.set_item("fill_fee", output.fill_fee)?;
        payload.set_item("fill_reason", output.fill_reason)?;
        payload.set_item("fill_ambiguity", output.fill_ambiguity)?;
        payload.set_item("event_bar", output.event_bar)?;
        payload.set_item("event_kind", output.event_kind)?;
        payload.set_item("event_status", output.event_status)?;
        payload.set_item("event_order_id", output.event_order_id)?;
        payload.set_item("event_target_id", output.event_target_id)?;
        payload.set_item("event_symbol", output.event_symbol)?;
        payload.set_item("event_reject_code", output.event_reject_code)?;
        add_workload_audit_retention(&payload, target_audit.detail_retention)?;
        payload.set_item("native_workload_audit_kind", "shared_portfolio_target_v1")?;
        payload.set_item(
            "portfolio_target_decision_count",
            target_audit.decision_count,
        )?;
        payload.set_item(
            "portfolio_target_rejected_decision_count",
            target_audit.rejected_decision_count,
        )?;
        payload.set_item("portfolio_target_decision_bar", target_audit.bar)?;
        payload.set_item("portfolio_target_decision_symbol", target_audit.symbol)?;
        payload.set_item(
            "portfolio_target_requested_units",
            target_audit.requested_units,
        )?;
        payload.set_item(
            "portfolio_target_accepted_units",
            target_audit.accepted_units,
        )?;
        payload.set_item(
            "portfolio_target_rejection_code",
            target_audit.rejection_code,
        )?;
    }
    Ok(payload.unbind())
}

/// Move a direct-target result into the existing profile-specific typed SoA
/// output family. The audit profile carries target-admission evidence beside
/// the canonical fill/event trace; score and compact retain no audit rows.
fn direct_target_typed_output(
    py: Python<'_>,
    result: execution::target::DirectTargetExecutionResultV1,
) -> PyResult<Py<PyAny>> {
    let output_bytes = direct_target_output_bytes(&result);
    let metadata = direct_target_metadata(&result, output_bytes);
    let execution::target::DirectTargetExecutionResultV1 {
        output,
        target_audit,
        rejected_by_bar,
        reject_code_by_bar,
        target_kind,
        timing,
        invalid_target_policy,
        ..
    } = result;
    match output {
        quantbt_engine::NativeExecutionOutputV1::Score(output) => Py::new(
            py,
            NativeScoreOutputCore {
                metadata,
                score: NativeScoreFieldsCore::from_native(py, output),
            },
        )
        .map(|output| output.into_any()),
        quantbt_engine::NativeExecutionOutputV1::Compact(output) => {
            let quantbt_engine::NativeCompactOutputV1 { score, paths } = *output;
            Py::new(
                py,
                NativeCompactOutputCore {
                    metadata,
                    score: NativeScoreFieldsCore::from_native(py, score),
                    paths: NativePathFieldsCore::from_native(py, paths),
                    direct_target: Some(DirectTargetCompactFieldsCore::from_required(
                        py,
                        rejected_by_bar,
                        reject_code_by_bar,
                    )),
                },
            )
            .map(|output| output.into_any())
        }
        quantbt_engine::NativeExecutionOutputV1::Audit(output) => {
            let quantbt_engine::NativeAuditOutputV1 {
                compact,
                fills,
                events,
                detail_retention: _,
            } = *output;
            let quantbt_engine::NativeCompactOutputV1 { score, paths } = compact;
            Py::new(
                py,
                NativeAuditOutputCore {
                    metadata,
                    score: NativeScoreFieldsCore::from_native(py, score),
                    paths: NativePathFieldsCore::from_native(py, paths),
                    audit: NativeAuditFieldsCore::from_native(py, fills, events),
                    workload_audit: NativeWorkloadAuditFieldsCore::from_direct_target(
                        py,
                        target_kind,
                        timing,
                        invalid_target_policy,
                        target_audit,
                        rejected_by_bar,
                        reject_code_by_bar,
                    ),
                },
            )
            .map(|output| output.into_any())
        }
    }
}

fn native_request_output_payload(
    py: Python<'_>,
    result: execution::NativeExecutionResultV1,
) -> PyResult<Py<PyDict>> {
    let profile = result.output_profile;
    let output_bytes = match &result.output {
        quantbt_engine::NativeExecutionOutputV1::Score(output) => score_output_bytes(output),
        quantbt_engine::NativeExecutionOutputV1::Compact(output) => compact_output_bytes(output),
        quantbt_engine::NativeExecutionOutputV1::Audit(output) => audit_output_bytes(output),
    }
    .saturating_add(workload_audit_output_bytes(&result.workload_audit));
    let metadata = NativeOutputMetadataCore::from_result(&result, output_bytes);
    let metrics = NativeMetricFieldsCore::from_native(result.output.score());
    // The frozen `execute()` API remains a cold-path mapping adapter. Moving
    // the typed SoA result into this legacy shape never reruns the engine.
    let output = result.output.into_legacy_static();
    let payload = PyDict::new(py);
    payload.set_item("final_equity", output.final_equity)?;
    payload.set_item("final_positions", output.final_positions)?;
    payload.set_item("total_fee", output.total_fee)?;
    payload.set_item("total_turnover", output.total_turnover)?;
    payload.set_item("total_funding", output.total_funding)?;
    payload.set_item("fill_count", output.fill_count)?;
    payload.set_item("event_count", output.event_count)?;
    payload.set_item("rejected_count", output.rejected_count)?;
    payload.set_item("canceled_count", output.canceled_count)?;
    payload.set_item("max_initial_margin", output.max_initial_margin)?;
    payload.set_item("max_maintenance_margin", output.max_maintenance_margin)?;
    payload.set_item("liquidated", output.liquidated)?;
    payload.set_item("liquidation_bar", output.liquidation_bar)?;
    payload.set_item("liquidation_reason", output.liquidation_reason)?;
    add_typed_output_metadata(&payload, &metadata)?;
    add_metric_fields(&payload, &metrics)?;
    add_native_workload_audit_fields(py, &payload, &result.workload_audit)?;

    if matches!(
        profile,
        execution::NativeOutputProfileV1::Compact | execution::NativeOutputProfileV1::Audit
    ) {
        payload.set_item("equity", output.equity)?;
        payload.set_item("positions", output.positions)?;
        payload.set_item("fees", output.fees)?;
        payload.set_item("turnover", output.turnover)?;
        payload.set_item("funding", output.funding)?;
        payload.set_item("initial_margin", output.initial_margin)?;
        payload.set_item("maintenance_margin", output.maintenance_margin)?;
    }
    if matches!(profile, execution::NativeOutputProfileV1::Audit) {
        payload.set_item("fill_bar", output.fill_bar)?;
        payload.set_item("fill_order_id", output.fill_order_id)?;
        payload.set_item("fill_symbol", output.fill_symbol)?;
        payload.set_item("fill_side", output.fill_side)?;
        payload.set_item("fill_qty", output.fill_qty)?;
        payload.set_item("fill_price", output.fill_price)?;
        payload.set_item("fill_fee", output.fill_fee)?;
        payload.set_item("fill_reason", output.fill_reason)?;
        payload.set_item("fill_ambiguity", output.fill_ambiguity)?;
        payload.set_item("event_bar", output.event_bar)?;
        payload.set_item("event_kind", output.event_kind)?;
        payload.set_item("event_status", output.event_status)?;
        payload.set_item("event_order_id", output.event_order_id)?;
        payload.set_item("event_target_id", output.event_target_id)?;
        payload.set_item("event_symbol", output.event_symbol)?;
        payload.set_item("event_reject_code", output.event_reject_code)?;
    }
    Ok(payload.unbind())
}

/// Move the authoritative typed Rust result into one profile-specific PyO3
/// object. `PyArray1::from_vec` transfers each Vec allocation to NumPy, so
/// output buffers remain valid after the request/session goes out of scope and
/// no per-row Python object is created.
fn native_request_typed_output(
    py: Python<'_>,
    result: execution::NativeExecutionResultV1,
) -> PyResult<Py<PyAny>> {
    let output_bytes = match &result.output {
        quantbt_engine::NativeExecutionOutputV1::Score(output) => score_output_bytes(output),
        quantbt_engine::NativeExecutionOutputV1::Compact(output) => compact_output_bytes(output),
        quantbt_engine::NativeExecutionOutputV1::Audit(output) => audit_output_bytes(output),
    }
    .saturating_add(workload_audit_output_bytes(&result.workload_audit));
    let metadata = NativeOutputMetadataCore::from_result(&result, output_bytes);
    let workload_audit = result.workload_audit;
    match result.output {
        quantbt_engine::NativeExecutionOutputV1::Score(output) => Py::new(
            py,
            NativeScoreOutputCore {
                metadata,
                score: NativeScoreFieldsCore::from_native(py, output),
            },
        )
        .map(|output| output.into_any()),
        quantbt_engine::NativeExecutionOutputV1::Compact(output) => {
            let quantbt_engine::NativeCompactOutputV1 { score, paths } = *output;
            Py::new(
                py,
                NativeCompactOutputCore {
                    metadata,
                    score: NativeScoreFieldsCore::from_native(py, score),
                    paths: NativePathFieldsCore::from_native(py, paths),
                    direct_target: None,
                },
            )
            .map(|output| output.into_any())
        }
        quantbt_engine::NativeExecutionOutputV1::Audit(output) => {
            let quantbt_engine::NativeAuditOutputV1 {
                compact,
                fills,
                events,
                detail_retention: _,
            } = *output;
            let quantbt_engine::NativeCompactOutputV1 { score, paths } = compact;
            Py::new(
                py,
                NativeAuditOutputCore {
                    metadata,
                    score: NativeScoreFieldsCore::from_native(py, score),
                    paths: NativePathFieldsCore::from_native(py, paths),
                    audit: NativeAuditFieldsCore::from_native(py, fills, events),
                    workload_audit: NativeWorkloadAuditFieldsCore::from_native(py, workload_audit),
                },
            )
            .map(|output| output.into_any())
        }
    }
}

#[allow(clippy::too_many_arguments)]
fn translate_full_command_tape(
    n_bars: usize,
    n_symbols: usize,
    ptr: &[i64],
    codes: &[i64],
    codes_shape: &[usize],
    values: &[f64],
    values_shape: &[usize],
    expiry: &[i64],
) -> Result<quantbt_domain::CommandTapeV5, String> {
    if codes_shape.len() != 2
        || codes_shape[1] != full::CODE_WIDTH
        || values_shape.len() != 2
        || values_shape[0] != codes_shape[0]
        || values_shape[1] != full::VALUE_WIDTH
        || codes.len() != codes_shape[0] * full::CODE_WIDTH
        || values.len() != values_shape[0] * full::VALUE_WIDTH
        || expiry.len() != codes_shape[0]
    {
        return Err("invalid full tape shapes".to_owned());
    }
    quantbt_domain::LegacyCommandTapeV4 {
        offsets_by_bar: ptr,
        codes,
        values,
        expiry,
        n_bars,
    }
    .translate(n_symbols)
    .map_err(|error| error.to_string())
}

/// API 0.4 adapter: validate public matrix dimensions once, then delegate the
/// complete run to the pure Rust engine. The engine returns flat SoA columns;
/// this binding no longer constructs nested rows or owns execution state.
#[allow(clippy::too_many_arguments)]
fn run_full_tape(
    session: &mut FullSession,
    ptr: &[i64],
    codes: &[i64],
    codes_shape: &[usize],
    values: &[f64],
    values_shape: &[usize],
    expiry: &[i64],
    audit: bool,
) -> Result<quantbt_engine::StaticTapeOutput, String> {
    let profile = if audit {
        quantbt_engine::StaticOutputProfile::Audit
    } else {
        quantbt_engine::StaticOutputProfile::Score
    };
    run_full_tape_profile(
        session,
        ptr,
        codes,
        codes_shape,
        values,
        values_shape,
        expiry,
        profile,
    )
}

#[allow(clippy::too_many_arguments)]
fn run_full_tape_profile(
    session: &mut FullSession,
    ptr: &[i64],
    codes: &[i64],
    codes_shape: &[usize],
    values: &[f64],
    values_shape: &[usize],
    expiry: &[i64],
    profile: quantbt_engine::StaticOutputProfile,
) -> Result<quantbt_engine::StaticTapeOutput, String> {
    // API 0.4 remains a compatibility wire format only.  Translate once at
    // ingress so every static full-tape run shares the ABI-0.5 `CommandTapeV5`
    // lifecycle path used by typed requests, IR, portfolio and packages.
    let tape = translate_full_command_tape(
        session.n_bars(),
        session.market.n_symbols,
        ptr,
        codes,
        codes_shape,
        values,
        values_shape,
        expiry,
    )?;
    match profile {
        quantbt_engine::StaticOutputProfile::Score => session.run_typed_score(&tape),
        quantbt_engine::StaticOutputProfile::Compact => session.run_typed_compact(&tape),
        quantbt_engine::StaticOutputProfile::Audit => session.run_typed_audit(&tape),
    }
}

#[pymodule]
fn _quantbt_native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add("__version__", VERSION)?;
    module.add_function(wrap_pyfunction!(version, module)?)?;
    module.add_function(wrap_pyfunction!(api_version, module)?)?;
    module.add_function(wrap_pyfunction!(core_abi_version, module)?)?;
    module.add_function(wrap_pyfunction!(capabilities, module)?)?;
    module.add_function(wrap_pyfunction!(semantic_descriptor, module)?)?;
    module.add_function(wrap_pyfunction!(product_descriptor, module)?)?;
    module.add_function(wrap_pyfunction!(run_fill_replay_v2_native, module)?)?;
    module.add_function(wrap_pyfunction!(native_portfolio_target_preflight, module)?)?;
    module.add_function(wrap_pyfunction!(
        native_package_transaction_preflight,
        module
    )?)?;
    module.add_function(wrap_pyfunction!(quantize_price_v1, module)?)?;
    module.add_function(wrap_pyfunction!(quantize_quantity_v1, module)?)?;
    module.add_function(wrap_pyfunction!(quantize_order_value_v1, module)?)?;
    module.add_function(wrap_pyfunction!(contract_registry_fingerprint, module)?)?;
    module.add_function(wrap_pyfunction!(event_contract_ids, module)?)?;
    module.add_class::<PreparedMarketCore>()?;
    module.add_class::<BatchedScoreResultCore>()?;
    module.add_class::<ReactiveSessionCore>()?;
    module.add_class::<FullStepResultCore>()?;
    module.add_class::<FullPreparedMarketCore>()?;
    module.add_class::<NativeScoreOutputCore>()?;
    module.add_class::<NativeCompactOutputCore>()?;
    module.add_class::<NativeAuditOutputCore>()?;
    module.add_class::<NativeIntrabarRequestCore>()?;
    module.add_class::<prepared_evaluation::NativePreparedEvaluationBindingCore>()?;
    module.add_class::<prepared_evaluation::NativePreparedEvaluationRuntimeCore>()?;
    module.add_class::<prepared_evaluation::NativePreparedEvaluationMatrixCore>()?;
    module.add_class::<NativeExecutionTemplateCore>()?;
    module.add_class::<NativeExecutionRequestCore>()?;
    module.add_class::<NativePackageScenarioBatchCore>()?;
    module.add_class::<NativeTargetExecutionRequestCore>()?;
    module.add_class::<NativeSharedPortfolioTargetRequestCore>()?;
    module.add_class::<NativeExecutionRunnerCore>()?;
    module.add_class::<NativeWfoMetricMatrixCore>()?;
    module.add_class::<NativeWfoPreparedSignalBatchCore>()?;
    module.add_class::<NativeWfoRuntimeCore>()?;
    module.add_class::<NativeWfoPreparedTargetBatchCore>()?;
    module.add_class::<NativeTargetWfoRuntimeCore>()?;
    module.add_class::<NativeStrategyProgramCore>()?;
    module.add_class::<FullReactiveSessionCore>()?;
    module.add_class::<ReactiveContextBufferV1>()?;
    module.add_class::<ReactiveCommandBufferV2>()?;
    module.add_class::<ReactiveCancellationTokenCore>()?;
    module.add_class::<ReactiveNumericRunOutputCore>()?;
    module.add_class::<ReactiveNumericRunnerCore>()?;
    module.add_class::<ReactiveCandidateBatchContextV1>()?;
    module.add_class::<ReactiveCandidateCommandBatchV1>()?;
    module.add_class::<ReactiveCandidateBatchRunOutputCore>()?;
    module.add_class::<ReactiveCandidateBatchRunnerCore>()?;
    Ok(())
}

#[cfg(test)]
mod phase51b_property_tests {
    use super::{integer_units, quantize_quantity_values};
    use proptest::prelude::*;

    proptest! {
        #[test]
        fn quantity_quantization_never_increases_requested_lots(
            raw_qty in 1u64..1_000_000u64,
            step_code in 1u64..10_000u64,
        ) {
            let qty = raw_qty as f64 / 1_000.0;
            let step = step_code as f64 / 1_000_000.0;
            let lots = integer_units(qty, step, false);
            let quantized = lots as f64 * step;
            prop_assert!(quantized <= qty + 1e-12);
            prop_assert!(quantized >= 0.0);
        }

        #[test]
        fn quantity_preflight_is_deterministic(
            raw_qty in 1u64..100_000u64,
            raw_price in 1u64..10_000_000u64,
        ) {
            let qty = raw_qty as f64 / 10_000.0;
            let price = raw_price as f64 / 100.0;
            let left = quantize_quantity_values(qty, price, 0.001, 0.001, 1_000.0, 5.0, 1.0);
            let right = quantize_quantity_values(qty, price, 0.001, 0.001, 1_000.0, 5.0, 1.0);
            prop_assert_eq!(left, right);
        }
    }
}
