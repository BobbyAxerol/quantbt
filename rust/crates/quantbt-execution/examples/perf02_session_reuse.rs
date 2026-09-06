//! PERF-02 reset-cost evidence for the shared native execution runner.
//!
//! The fixture intentionally separates a terminal 100k-order predecessor
//! (whose arena can reset in O(1) after terminal release) from a live 100k
//! predecessor (which must scan/cancel every active order to preserve domain
//! semantics). It is a native benchmark, not a public endpoint benchmark.

use std::env;
use std::fs;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Instant;

use quantbt_domain::commands::CommandTapeV5;
use quantbt_domain::enums::{ActivationPolicy, CommandAction, OrderType, Side, TimeInForce};
use quantbt_domain::generated_contracts::CONTRACT_EVENT_LIFECYCLE_V3_NEXT_OPEN;
use quantbt_domain::ids::{ExternalOrderId, SymbolId};
use quantbt_engine::FullMarketData;
use quantbt_execution::{
    AccountModelV1, ExecutionContractV1, InstrumentTableV1, NativeExecutionRequestV1,
    NativeExecutionRunnerV1, NativeExecutionTemplateV1, NativeOutputProfileV1, WorkloadPayloadV1,
};

fn parse_args() -> (usize, usize, Option<PathBuf>) {
    let mut outlier_orders = 100_000_usize;
    let mut repeats = 5_usize;
    let mut output = None;
    let mut values = env::args().skip(1);
    while let Some(flag) = values.next() {
        match flag.as_str() {
            "--outlier-orders" => {
                outlier_orders = values
                    .next()
                    .expect("--outlier-orders needs a value")
                    .parse()
                    .expect("--outlier-orders must be an integer");
            }
            "--repeats" => {
                repeats = values
                    .next()
                    .expect("--repeats needs a value")
                    .parse()
                    .expect("--repeats must be an integer");
            }
            "--output" => {
                output = Some(PathBuf::from(values.next().expect("--output needs a path")))
            }
            "--help" | "-h" => {
                println!(
                    "usage: cargo run -p quantbt-execution --release --example perf02_session_reuse -- [--outlier-orders 100000] [--repeats 5] [--output result.json]"
                );
                std::process::exit(0);
            }
            _ => panic!("unknown argument {flag}"),
        }
    }
    assert!(outlier_orders > 0, "outlier order count must be positive");
    assert!(repeats > 0, "repeat count must be positive");
    (outlier_orders, repeats, output)
}

fn template() -> Arc<NativeExecutionTemplateV1> {
    let market = Arc::new(
        FullMarketData::new(
            vec![0, 1, 2, 3],
            vec![100.0, 100.0, 101.0, 102.0],
            vec![101.0, 101.0, 102.0, 103.0],
            vec![99.0, 99.0, 100.0, 101.0],
            vec![100.0, 100.0, 101.0, 102.0],
            vec![1_000_000.0; 4],
            vec![0.0; 4],
            vec![false; 4],
            1,
        )
        .expect("valid benchmark market"),
    );
    Arc::new(
        NativeExecutionTemplateV1::new(
            market,
            InstrumentTableV1::sequential(vec![1.0], vec![5.0], vec![0.0002])
                .expect("valid instrument table"),
            AccountModelV1::new(100_000_000.0, 0.005, 0.0001, false).expect("valid account"),
            ExecutionContractV1::new(CONTRACT_EVENT_LIFECYCLE_V3_NEXT_OPEN)
                .expect("valid event contract"),
        )
        .expect("valid native template"),
    )
}

fn command(
    command_index: usize,
    order_type: OrderType,
    limit_price: f64,
) -> quantbt_domain::OrderCommandV5 {
    quantbt_domain::OrderCommandV5 {
        action: CommandAction::Place,
        symbol: Some(SymbolId(0)),
        side: Some(Side::Buy),
        order_type: Some(order_type),
        tif: Some(TimeInForce::Gtc),
        reduce_only: false,
        external_id: ExternalOrderId(100_000 + command_index as i64),
        target_id: ExternalOrderId(-1),
        parent_id: ExternalOrderId(-1),
        group_id: -1,
        oco_id: -1,
        activation: Some(ActivationPolicy::Immediate),
        command_index: command_index as u32,
        qty: 0.01,
        limit_price,
        stop_price: 0.0,
        expire_bar: None,
    }
}

fn outlier_tape(order_count: usize, order_type: OrderType) -> CommandTapeV5 {
    let limit_price = if order_type == OrderType::Limit {
        1.0
    } else {
        0.0
    };
    let commands = (0..order_count)
        .map(|index| command(index, order_type, limit_price))
        .collect();
    let count = u32::try_from(order_count).expect("outlier count exceeds ABI command capacity");
    // Bar zero is frozen by the static execution contract.
    CommandTapeV5::new(vec![0, 0, count, count, count], commands).expect("valid outlier tape")
}

fn small_tape() -> CommandTapeV5 {
    let mut buy = command(0, OrderType::Market, 0.0);
    buy.external_id = ExternalOrderId(1);
    let mut sell = command(1, OrderType::Market, 0.0);
    sell.external_id = ExternalOrderId(2);
    sell.side = Some(Side::Sell);
    sell.reduce_only = true;
    CommandTapeV5::new(vec![0, 0, 1, 2, 2], vec![buy, sell]).expect("valid small tape")
}

fn request(
    template: Arc<NativeExecutionTemplateV1>,
    tape: CommandTapeV5,
) -> NativeExecutionRequestV1 {
    NativeExecutionRequestV1::from_template(
        template,
        NativeOutputProfileV1::Score,
        WorkloadPayloadV1::CommandTape(tape),
    )
    .expect("valid benchmark request")
}

fn percentile(mut samples: Vec<u128>, quantile: f64) -> u128 {
    samples.sort_unstable();
    let index = ((samples.len() - 1) as f64 * quantile).round() as usize;
    samples[index]
}

fn summary(samples: &[u128]) -> String {
    format!(
        "{{\"median_ns\":{},\"p95_ns\":{},\"min_ns\":{},\"max_ns\":{}}}",
        percentile(samples.to_vec(), 0.50),
        percentile(samples.to_vec(), 0.95),
        samples.iter().min().copied().unwrap_or(0),
        samples.iter().max().copied().unwrap_or(0),
    )
}

fn rss_kib() -> Option<u64> {
    fs::read_to_string("/proc/self/status")
        .ok()?
        .lines()
        .find_map(|line| {
            line.strip_prefix("VmRSS:")?
                .split_whitespace()
                .next()?
                .parse()
                .ok()
        })
}

fn main() {
    let (outlier_orders, repeats, output_path) = parse_args();
    let template = template();
    let small = request(template.clone(), small_tape());
    let terminal_outlier = request(
        template.clone(),
        outlier_tape(outlier_orders, OrderType::Market),
    );
    let live_outlier = request(
        template.clone(),
        outlier_tape(outlier_orders, OrderType::Limit),
    );
    let expected = small.execute().expect("fresh small reference");
    let expected_equity = expected.output.score().final_equity;
    let rss_start_kib = rss_kib();

    let mut fresh_total_ns = Vec::with_capacity(repeats);
    let mut reuse_small_ns = Vec::with_capacity(repeats);
    let mut reset_normal_ns = Vec::with_capacity(repeats);
    let mut reset_after_terminal_ns = Vec::with_capacity(repeats);
    let mut reset_after_live_ns = Vec::with_capacity(repeats);
    let mut runner = NativeExecutionRunnerV1::new(template).expect("runner");

    for _ in 0..repeats {
        let started = Instant::now();
        let mut fresh = small.new_runner().expect("fresh runner");
        let fresh_output = fresh
            .execute_request(&small)
            .expect("fresh small execution");
        fresh_total_ns.push(started.elapsed().as_nanos());
        assert_eq!(fresh_output.output.score().final_equity, expected_equity);

        let started = Instant::now();
        let reused_output = runner
            .execute_request(&small)
            .expect("reused small execution");
        reuse_small_ns.push(started.elapsed().as_nanos());
        assert_eq!(reused_output.output.score().final_equity, expected_equity);

        runner.execute_request(&small).expect("normal predecessor");
        let started = Instant::now();
        runner.reset_account_and_orders().expect("normal reset");
        reset_normal_ns.push(started.elapsed().as_nanos());

        runner
            .execute_request(&terminal_outlier)
            .expect("terminal outlier execution");
        assert_eq!(runner.order_arena_counters().0, 0);
        let started = Instant::now();
        runner
            .reset_account_and_orders()
            .expect("terminal outlier reset");
        reset_after_terminal_ns.push(started.elapsed().as_nanos());

        runner
            .execute_request(&live_outlier)
            .expect("live outlier execution");
        assert_eq!(runner.order_arena_counters().0, outlier_orders);
        let started = Instant::now();
        runner
            .reset_account_and_orders()
            .expect("live outlier reset");
        reset_after_live_ns.push(started.elapsed().as_nanos());
    }

    let payload = format!(
        concat!(
            "{{\"schema\":\"quantbt-perf-02-session-reuse-v1\",",
            "\"outlier_orders\":{outlier_orders},\"repeats\":{repeats},",
            "\"fresh_small_total\":{fresh},\"reused_small_total\":{reuse},",
            "\"reset_normal\":{normal},\"reset_after_terminal_outlier\":{terminal},",
            "\"reset_after_live_outlier\":{live},\"rss_start_kib\":{rss_start},",
            "\"rss_end_kib\":{rss_end},\"contract\":{contract}}}"
        ),
        outlier_orders = outlier_orders,
        repeats = repeats,
        fresh = summary(&fresh_total_ns),
        reuse = summary(&reuse_small_ns),
        normal = summary(&reset_normal_ns),
        terminal = summary(&reset_after_terminal_ns),
        live = summary(&reset_after_live_ns),
        rss_start = rss_start_kib.map_or_else(|| "null".to_owned(), |value| value.to_string()),
        rss_end = rss_kib().map_or_else(|| "null".to_owned(), |value| value.to_string()),
        contract = "\"terminal outlier reset may skip an empty arena scan; live orders are deliberately scanned and canceled\"",
    );
    if let Some(path) = output_path {
        fs::write(path, &payload).expect("write PERF-02 benchmark output");
    }
    println!("{payload}");
}
