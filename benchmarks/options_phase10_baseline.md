# Options Engine Phase 10 Benchmark

Status: **pass**

| metric | value |
| --- | ---: |
| snapshots | `48` |
| contracts | `24` |
| quotes | `1152` |
| packages | `48` |
| fills | `48` |
| hedges | `0` |
| peak memory MB | `2.020` |
| uncached seconds | `0.167057` |
| cached seconds | `0.133838` |
| cache speedup | `1.248x` |
| package cache size | `48` |

## Parity Guard

- Passed: `True`
- Final equity abs diff: `0.000000000000`
- Position max abs diff: `0.000000000000`
- Fills equal: `True`

## Manifest

- Data hash: `12424421059823038086`
- Margin model: `standard_venue_approx`
- Pricing model: `observed_chain_bid_ask_mark`
- Fidelity: `{'tape': 'prepared_csr_option_chain', 'execution': 'top_of_book_bbo', 'limit_fidelity': 'cross_only', 'depth_fidelity': 'top_of_book', 'margin': 'standard_venue_approx', 'venue_exact_margin': False, 'prepared_cache_used': True}`

## Cython / C++ Decision

not_recommended_yet: Phase 10 benchmark still targets pandas/tape/package facade and cache reuse; collect pure-kernel profile evidence before Cython/C++.
