# Native Event Workload Classes

Performance claims are attached to workload classes, not to “Rust” in general.

| Class | Strategy source | Boundary shape | Current status |
|---|---|---|---|
| E0 static tape | Precompiled commands | One native call per tape | Contract-tested |
| E1 callback | Python strategy callback | Python wake points plus execution | Compatibility route |
| E2 prepared session | Reused market context | Reused native preparation | Contract-tested |
| E3 strategy IR | Bounded native IR v1 | One call per scenario | Experimental explicit route |
| E6 batch/optimizer | Matrix of IR scenarios | Shared market, batch call | Experimental explicit route |

The profile matters too. `score` avoids audit materialization; `audit` retains
the data required for review. A score benchmark cannot be used to claim audit
throughput, and an IR benchmark cannot be used to claim speed for arbitrary
Python callbacks.

Each benchmark record must include fixture hash, contract, symbol count, bars,
command/fill churn, profile, warm/cold state, Python/Rust boundary-call count,
runtime distribution, RSS, toolchain, and parity result.
