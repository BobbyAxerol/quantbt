# PRE-E06-05 Generated Cost Tables

Source: `qms_pre_e06_05_cost.json`; 21 paired warm samples/cell.
Small synthetic source-level workload, not economic or installed/public certification.

## Domain, Prepared And Nested Public Calls

| Group/Route | Off p50 ms | Shadow p50 ms | Active Before/After ms | Active Change | Active/Off | Labels/Aux |
|---|---:|---:|---:|---:|---:|---:|
| domain/signal_notional | 81.09 | 206.15 | 213.57 / 207.88 | -2.66% | 2.564x | 3/0 |
| domain/notional | 117.71 | 232.29 | 240.65 / 236.55 | -1.70% | 2.010x | 3/0 |
| domain/unit | 119.09 | 245.67 | 257.24 / 253.13 | -1.60% | 2.125x | 3/0 |
| domain/pct_equity | 102.54 | 222.57 | 225.88 / 219.83 | -2.68% | 2.144x | 3/0 |
| domain/dca_ladder | 105.78 | 216.35 | 232.82 / 227.13 | -2.44% | 2.147x | 3/0 |
| domain/portfolio | 171.97 | 386.82 | 400.36 / 392.12 | -2.06% | 2.280x | 3/0 |
| domain/basket | 266.28 | 493.65 | 496.94 / 489.74 | -1.45% | 1.839x | 3/0 |
| domain/arbitrage | 498.33 | 806.10 | 796.58 / 780.42 | -2.03% | 1.566x | 3/0 |
| domain/intrabar | 188.79 | 342.71 | 340.45 / 334.32 | -1.80% | 1.771x | 3/0 |
| domain/event_driven | 900.81 | 1190.57 | 1181.45 / 1177.54 | -0.33% | 1.307x | 3/0 |
| domain/order_commands | 753.87 | 1043.51 | 1025.73 / 1026.38 | +0.06% | 1.361x | 3/0 |
| domain/delivery_arbitrage | 1116.38 | 1533.57 | 1536.66 / 1499.94 | -2.39% | 1.344x | 3/0 |
| domain/reactive_reset | 72.32 | 287.97 | 303.50 / 292.97 | -3.47% | 4.051x | 3/0 |
| prepared/signal_notional | 60.55 | 209.98 | 219.19 / 213.15 | -2.76% | 3.520x | 3/0 |
| prepared/notional | 60.38 | 213.81 | 224.29 / 218.55 | -2.56% | 3.620x | 3/0 |
| prepared/unit | 62.25 | 206.79 | 231.02 / 222.76 | -3.58% | 3.579x | 3/0 |
| prepared/pct_equity | 59.05 | 202.92 | 212.91 / 206.48 | -3.02% | 3.497x | 3/0 |
| nested/signal_notional | 123.66 | 280.02 | 297.56 / 289.66 | -2.65% | 2.342x | 3/3 |
| nested/notional | 215.72 | 386.42 | 413.63 / 406.37 | -1.76% | 1.884x | 3/3 |
| nested/unit | 224.60 | 390.11 | 405.12 / 397.73 | -1.83% | 1.771x | 3/3 |
| nested/pct_equity | 186.25 | 343.38 | 349.19 / 336.34 | -3.68% | 1.806x | 3/3 |
| nested/dca_ladder | 186.43 | 348.75 | 359.78 / 349.66 | -2.81% | 1.876x | 3/3 |

On/off changes logical work; that ratio is cost, not a speedup comparison.
W3 is prepared `backtest`, with constructor/history preparation recorded separately.

## Disabled Point Budgets

| Cell | Before/After p50 ms | p50 Change | Before/After p95 ms | p95 Change | Point Budget |
|---|---:|---:|---:|---:|---|
| legacy-signal_notional-off-mode_1_decay-global-false-false | 144.18 / 144.02 | -0.11% | 180.33 / 184.04 | +2.06% | PASS |
| legacy-signal_notional-off-mode_1_decay-per_fold_decay-false-false | 169.62 / 172.53 | +1.71% | 182.05 / 199.97 | +9.84% | NOT_MET |
| legacy-signal_notional-off-mode_1_decay-per_fold_causal-false-false | 414.80 / 419.38 | +1.10% | 447.09 / 479.39 | +7.22% | NOT_MET |
| legacy-signal_notional-off-mode_2_sbb-global-false-false | 197.32 / 197.48 | +0.08% | 216.77 / 205.35 | -5.27% | PASS |
| legacy-signal_notional-off-mode_3_flat_minima-global-false-false | 142.98 / 140.68 | -1.61% | 150.08 / 185.34 | +23.50% | NOT_MET |
| legacy-signal_notional-off-mode_4_is_only_robust-global-false-false | 211.63 / 213.54 | +0.90% | 222.34 / 261.99 | +17.83% | NOT_MET |
| legacy-signal_notional-off-mode_4_is_only_robust-per_fold_causal-false-false | 207.73 / 209.85 | +1.02% | 231.90 / 225.60 | -2.72% | PASS |
| legacy-signal_notional-off-mode_5_full_robust-global-false-false | 130.06 / 128.96 | -0.84% | 138.46 / 140.11 | +1.20% | PASS |
| domain-signal_notional-off-mode_4_is_only_robust-per_fold_causal-false-false | 83.66 / 81.09 | -3.08% | 88.76 / 86.83 | -2.17% | PASS |
| domain-notional-off-mode_4_is_only_robust-per_fold_causal-false-false | 118.03 / 117.71 | -0.27% | 124.09 / 128.89 | +3.86% | PASS |
| domain-unit-off-mode_4_is_only_robust-per_fold_causal-false-false | 118.02 / 119.09 | +0.91% | 126.70 / 137.46 | +8.49% | NOT_MET |
| domain-pct_equity-off-mode_4_is_only_robust-per_fold_causal-false-false | 103.33 / 102.54 | -0.77% | 118.32 / 116.02 | -1.94% | PASS |
| domain-dca_ladder-off-mode_4_is_only_robust-per_fold_causal-false-false | 106.01 / 105.78 | -0.22% | 113.73 / 117.94 | +3.70% | PASS |
| domain-portfolio-off-mode_4_is_only_robust-per_fold_causal-false-false | 176.49 / 171.97 | -2.57% | 196.08 / 199.90 | +1.95% | PASS |
| domain-basket-off-mode_4_is_only_robust-per_fold_causal-false-false | 269.85 / 266.28 | -1.33% | 303.49 / 299.78 | -1.22% | PASS |
| domain-arbitrage-off-mode_4_is_only_robust-per_fold_causal-false-false | 486.35 / 498.33 | +2.46% | 691.47 / 683.07 | -1.22% | PASS |
| domain-intrabar-off-mode_4_is_only_robust-per_fold_causal-false-false | 186.63 / 188.79 | +1.16% | 204.21 / 204.11 | -0.05% | PASS |
| domain-event_driven-off-mode_4_is_only_robust-per_fold_causal-false-false | 916.17 / 900.81 | -1.68% | 957.93 / 995.64 | +3.94% | PASS |
| domain-order_commands-off-mode_4_is_only_robust-per_fold_causal-false-false | 770.25 / 753.87 | -2.13% | 885.68 / 851.92 | -3.81% | PASS |
| domain-delivery_arbitrage-off-mode_4_is_only_robust-per_fold_causal-false-false | 1126.73 / 1116.38 | -0.92% | 1217.23 / 1166.49 | -4.17% | PASS |
| domain-reactive_reset-off-mode_4_is_only_robust-per_fold_causal-false-false | 71.15 / 72.32 | +1.64% | 75.97 / 83.17 | +9.48% | NOT_MET |
| prepared-signal_notional-off-mode_4_is_only_robust-per_fold_causal-true-false | 59.75 / 60.55 | +1.35% | 83.83 / 65.70 | -21.63% | PASS |
| prepared-notional-off-mode_4_is_only_robust-per_fold_causal-true-false | 60.59 / 60.38 | -0.34% | 73.53 / 65.23 | -11.29% | PASS |
| prepared-unit-off-mode_4_is_only_robust-per_fold_causal-true-false | 61.92 / 62.25 | +0.54% | 65.97 / 66.40 | +0.66% | PASS |
| prepared-pct_equity-off-mode_4_is_only_robust-per_fold_causal-true-false | 59.13 / 59.05 | -0.15% | 64.76 / 66.51 | +2.70% | PASS |
| nested-signal_notional-off-mode_1_decay-per_fold_causal-false-false | 124.75 / 123.66 | -0.87% | 132.05 / 127.27 | -3.62% | PASS |
| nested-notional-off-mode_1_decay-per_fold_causal-false-false | 210.44 / 215.72 | +2.51% | 229.30 / 240.18 | +4.74% | PASS |
| nested-unit-off-mode_1_decay-per_fold_causal-false-false | 223.05 / 224.60 | +0.69% | 247.07 / 244.97 | -0.85% | PASS |
| nested-pct_equity-off-mode_1_decay-per_fold_causal-false-false | 180.20 / 186.25 | +3.36% | 206.22 / 192.62 | -6.60% | NOT_MET |
| nested-dca_ladder-off-mode_1_decay-per_fold_causal-false-false | 186.58 / 186.43 | -0.08% | 195.16 / 194.32 | -0.43% | PASS |
| conditional-pct_equity-off-mode_4_is_only_robust-per_fold_causal-false-true | 283.97 / 270.12 | -4.88% | 358.26 / 346.97 | -3.15% | PASS |
| conditional-pct_equity-off-mode_5_full_robust-global-false-true | 353.55 / 346.85 | -1.90% | 389.09 / 390.05 | +0.25% | PASS |

Budgets +3% p50 / +5% p95 are unchanged. NOT_MET does not become PASS due to dispersion.

## Instrumented Profiles

| Cell/Arm | Instrumented ms | wire Calls/Cumulative ms | N/d/Origins/P |
|---|---:|---:|---|
| isolated-reference-legacy-signal_notional-off-mode_4_is_only_robust-per_fold_causal-false-false | 442.26 | 0/0.00 | N/A |
| isolated-optimized-legacy-signal_notional-off-mode_4_is_only_robust-per_fold_causal-false-false | 504.83 | 0/0.00 | N/A |
| isolated-reference-domain-pct_equity-off-mode_4_is_only_robust-per_fold_causal-false-false | 323.11 | 0/0.00 | N/A |
| isolated-optimized-domain-pct_equity-off-mode_4_is_only_robust-per_fold_causal-false-false | 343.98 | 0/0.00 | N/A |
| isolated-reference-domain-pct_equity-active-mode_4_is_only_robust-per_fold_causal-false-false | 447.32 | 3661/36.00 | 37/3/15/3 |
| isolated-optimized-domain-pct_equity-active-mode_4_is_only_robust-per_fold_causal-false-false | 421.17 | 3661/10.07 | 37/3/15/3 |
| isolated-reference-domain-intrabar-active-mode_4_is_only_robust-per_fold_causal-false-false | 692.80 | 4033/38.82 | 64/3/24/3 |
| isolated-optimized-domain-intrabar-active-mode_4_is_only_robust-per_fold_causal-false-false | 658.88 | 4033/11.28 | 64/3/24/3 |
| isolated-reference-domain-event_driven-active-mode_4_is_only_robust-per_fold_causal-false-false | 2466.27 | 3991/39.49 | 64/3/24/3 |
| isolated-optimized-domain-event_driven-active-mode_4_is_only_robust-per_fold_causal-false-false | 2283.84 | 3991/10.62 | 64/3/24/3 |
| isolated-reference-domain-reactive_reset-active-mode_4_is_only_robust-per_fold_causal-false-false | 645.09 | 8443/87.69 | 64/3/24/3 |
| isolated-optimized-domain-reactive_reset-active-mode_4_is_only_robust-per_fold_causal-false-false | 553.86 | 8443/27.12 | 64/3/24/3 |
| isolated-reference-domain-portfolio-active-mode_4_is_only_robust-per_fold_causal-false-false | 811.88 | 4556/44.62 | 64/3/24/3 |
| isolated-optimized-domain-portfolio-active-mode_4_is_only_robust-per_fold_causal-false-false | 728.26 | 4556/11.76 | 64/3/24/3 |
| isolated-reference-nested-pct_equity-active-mode_1_decay-per_fold_causal-false-false | 730.37 | 4876/49.41 | 36/3/14/3 |
| isolated-optimized-nested-pct_equity-active-mode_1_decay-per_fold_causal-false-false | 674.60 | 4876/15.00 | 36/3/14/3 |
| isolated-reference-legacy-signal_notional-off-mode_1_decay-per_fold_decay-false-false | 397.74 | 0/0.00 | N/A |
| isolated-optimized-legacy-signal_notional-off-mode_1_decay-per_fold_decay-false-false | 359.81 | 0/0.00 | N/A |
| isolated-reference-legacy-signal_notional-off-mode_1_decay-per_fold_causal-false-false | 818.82 | 0/0.00 | N/A |
| isolated-optimized-legacy-signal_notional-off-mode_1_decay-per_fold_causal-false-false | 882.56 | 0/0.00 | N/A |
| isolated-reference-legacy-signal_notional-off-mode_3_flat_minima-global-false-false | 326.58 | 0/0.00 | N/A |
| isolated-optimized-legacy-signal_notional-off-mode_3_flat_minima-global-false-false | 309.16 | 0/0.00 | N/A |
| isolated-reference-legacy-signal_notional-off-mode_4_is_only_robust-global-false-false | 439.14 | 0/0.00 | N/A |
| isolated-optimized-legacy-signal_notional-off-mode_4_is_only_robust-global-false-false | 433.78 | 0/0.00 | N/A |
| isolated-reference-domain-unit-off-mode_4_is_only_robust-per_fold_causal-false-false | 340.33 | 0/0.00 | N/A |
| isolated-optimized-domain-unit-off-mode_4_is_only_robust-per_fold_causal-false-false | 357.46 | 0/0.00 | N/A |
| isolated-reference-domain-reactive_reset-off-mode_4_is_only_robust-per_fold_causal-false-false | 139.89 | 0/0.00 | N/A |
| isolated-optimized-domain-reactive_reset-off-mode_4_is_only_robust-per_fold_causal-false-false | 143.68 | 0/0.00 | N/A |
| isolated-reference-nested-pct_equity-off-mode_1_decay-per_fold_causal-false-false | 394.18 | 0/0.00 | N/A |
| isolated-optimized-nested-pct_equity-off-mode_1_decay-per_fold_causal-false-false | 347.95 | 0/0.00 | N/A |

Profile spans are instrumented diagnostics, not latency gate samples.
Full profiles preserve exclusive/inclusive components and observed backend/thread/FFI telemetry.

## Memory

| Cell | Worker Peak MiB | Warm Reference/Optimized Retained MiB | First-to-Last Drift MiB |
|---|---:|---:|---:|
| legacy-signal_notional-off-mode_1_decay-global-false-false | 221.801 | 221.801/221.801 | +2.625 |
| legacy-signal_notional-off-mode_1_decay-per_fold_decay-false-false | 222.086 | 222.086/222.086 | +3.125 |
| legacy-signal_notional-off-mode_1_decay-per_fold_causal-false-false | 224.434 | 224.434/224.434 | +3.574 |
| legacy-signal_notional-off-mode_2_sbb-global-false-false | 222.320 | 222.320/222.320 | +2.680 |
| legacy-signal_notional-off-mode_3_flat_minima-global-false-false | 221.883 | 221.625/221.625 | +3.367 |
| legacy-signal_notional-off-mode_4_is_only_robust-global-false-false | 284.777 | 284.523/284.777 | +3.105 |
| legacy-signal_notional-off-mode_4_is_only_robust-per_fold_causal-false-false | 284.523 | 284.266/284.266 | +3.070 |
| legacy-signal_notional-off-mode_5_full_robust-global-false-false | 284.223 | 284.223/284.223 | +2.867 |
| domain-signal_notional-off-mode_4_is_only_robust-per_fold_causal-false-false | 286.887 | 286.629/286.629 | +4.195 |
| domain-signal_notional-shadow-mode_4_is_only_robust-per_fold_causal-false-false | 292.227 | 291.969/291.969 | +6.547 |
| domain-signal_notional-active-mode_4_is_only_robust-per_fold_causal-false-false | 292.777 | 292.777/292.777 | +6.523 |
| domain-notional-off-mode_4_is_only_robust-per_fold_causal-false-false | 285.277 | 285.277/285.277 | +4.082 |
| domain-notional-shadow-mode_4_is_only_robust-per_fold_causal-false-false | 291.844 | 291.844/291.844 | +6.449 |
| domain-notional-active-mode_4_is_only_robust-per_fold_causal-false-false | 291.824 | 291.824/291.824 | +6.379 |
| domain-unit-off-mode_4_is_only_robust-per_fold_causal-false-false | 285.176 | 285.176/285.176 | +4.145 |
| domain-unit-shadow-mode_4_is_only_robust-per_fold_causal-false-false | 292.203 | 291.945/292.203 | +6.453 |
| domain-unit-active-mode_4_is_only_robust-per_fold_causal-false-false | 292.094 | 292.094/292.094 | +6.395 |
| domain-pct_equity-off-mode_4_is_only_robust-per_fold_causal-false-false | 282.969 | 282.969/282.969 | +2.016 |
| domain-pct_equity-shadow-mode_4_is_only_robust-per_fold_causal-false-false | 289.707 | 289.707/289.707 | +4.344 |
| domain-pct_equity-active-mode_4_is_only_robust-per_fold_causal-false-false | 290.039 | 290.039/290.039 | +4.332 |
| domain-dca_ladder-off-mode_4_is_only_robust-per_fold_causal-false-false | 283.684 | 283.684/283.684 | +2.020 |
| domain-dca_ladder-shadow-mode_4_is_only_robust-per_fold_causal-false-false | 289.914 | 289.914/289.914 | +4.410 |
| domain-dca_ladder-active-mode_4_is_only_robust-per_fold_causal-false-false | 290.676 | 290.418/290.418 | +4.637 |
| domain-portfolio-off-mode_4_is_only_robust-per_fold_causal-false-false | 299.762 | 298.781/298.812 | +16.742 |
| domain-portfolio-shadow-mode_4_is_only_robust-per_fold_causal-false-false | 306.273 | 306.016/306.016 | +18.965 |
| domain-portfolio-active-mode_4_is_only_robust-per_fold_causal-false-false | 306.293 | 306.035/306.035 | +19.078 |
| domain-basket-off-mode_4_is_only_robust-per_fold_causal-false-false | 286.809 | 286.809/286.809 | +3.867 |
| domain-basket-shadow-mode_4_is_only_robust-per_fold_causal-false-false | 293.926 | 293.668/293.668 | +6.188 |
| domain-basket-active-mode_4_is_only_robust-per_fold_causal-false-false | 292.504 | 292.504/292.504 | +6.188 |
| domain-arbitrage-off-mode_4_is_only_robust-per_fold_causal-false-false | 294.297 | 294.039/294.039 | +10.312 |
| domain-arbitrage-shadow-mode_4_is_only_robust-per_fold_causal-false-false | 300.793 | 300.793/300.793 | +12.375 |
| domain-arbitrage-active-mode_4_is_only_robust-per_fold_causal-false-false | 301.035 | 301.035/301.035 | +12.633 |
| domain-intrabar-off-mode_4_is_only_robust-per_fold_causal-false-false | 287.184 | 287.184/287.184 | +5.156 |
| domain-intrabar-shadow-mode_4_is_only_robust-per_fold_causal-false-false | 294.020 | 293.762/293.762 | +7.785 |
| domain-intrabar-active-mode_4_is_only_robust-per_fold_causal-false-false | 294.262 | 294.004/294.004 | +7.805 |
| domain-event_driven-off-mode_4_is_only_robust-per_fold_causal-false-false | 293.867 | 293.609/293.609 | +2.836 |
| domain-event_driven-shadow-mode_4_is_only_robust-per_fold_causal-false-false | 299.594 | 299.336/299.336 | +3.609 |
| domain-event_driven-active-mode_4_is_only_robust-per_fold_causal-false-false | 300.098 | 299.926/299.984 | +3.668 |
| domain-order_commands-off-mode_4_is_only_robust-per_fold_causal-false-false | 294.824 | 294.668/294.617 | +2.832 |
| domain-order_commands-shadow-mode_4_is_only_robust-per_fold_causal-false-false | 299.496 | 299.086/299.086 | +3.812 |
| domain-order_commands-active-mode_4_is_only_robust-per_fold_causal-false-false | 299.387 | 299.234/299.242 | +3.895 |
| domain-delivery_arbitrage-off-mode_4_is_only_robust-per_fold_causal-false-false | 297.508 | 297.250/297.250 | +3.832 |
| domain-delivery_arbitrage-shadow-mode_4_is_only_robust-per_fold_causal-false-false | 302.863 | 302.434/302.449 | +4.398 |
| domain-delivery_arbitrage-active-mode_4_is_only_robust-per_fold_causal-false-false | 302.770 | 302.324/302.348 | +4.621 |
| domain-reactive_reset-off-mode_4_is_only_robust-per_fold_causal-false-false | 239.973 | 239.715/239.715 | +0.770 |
| domain-reactive_reset-shadow-mode_4_is_only_robust-per_fold_causal-false-false | 243.223 | 243.223/243.223 | +2.062 |
| domain-reactive_reset-active-mode_4_is_only_robust-per_fold_causal-false-false | 243.676 | 243.676/243.676 | +2.062 |
| prepared-signal_notional-off-mode_4_is_only_robust-per_fold_causal-true-false | 287.348 | 287.348/287.348 | +4.648 |
| prepared-signal_notional-shadow-mode_4_is_only_robust-per_fold_causal-true-false | 292.453 | 292.195/292.195 | +7.160 |
| prepared-signal_notional-active-mode_4_is_only_robust-per_fold_causal-true-false | 292.676 | 292.676/292.676 | +7.156 |
| prepared-notional-off-mode_4_is_only_robust-per_fold_causal-true-false | 242.289 | 242.289/242.289 | +5.016 |
| prepared-notional-shadow-mode_4_is_only_robust-per_fold_causal-true-false | 248.082 | 247.855/247.855 | +7.129 |
| prepared-notional-active-mode_4_is_only_robust-per_fold_causal-true-false | 247.762 | 247.504/247.504 | +6.188 |
| prepared-unit-off-mode_4_is_only_robust-per_fold_causal-true-false | 242.305 | 242.047/242.047 | +4.895 |
| prepared-unit-shadow-mode_4_is_only_robust-per_fold_causal-true-false | 247.734 | 247.477/247.477 | +6.188 |
| prepared-unit-active-mode_4_is_only_robust-per_fold_causal-true-false | 247.781 | 247.523/247.523 | +6.188 |
| prepared-pct_equity-off-mode_4_is_only_robust-per_fold_causal-true-false | 242.203 | 241.945/241.945 | +4.719 |
| prepared-pct_equity-shadow-mode_4_is_only_robust-per_fold_causal-true-false | 247.949 | 247.691/247.691 | +7.094 |
| prepared-pct_equity-active-mode_4_is_only_robust-per_fold_causal-true-false | 248.051 | 247.793/247.793 | +7.008 |
| nested-signal_notional-off-mode_1_decay-per_fold_causal-false-false | 222.941 | 222.699/222.699 | +4.109 |
| nested-signal_notional-shadow-mode_1_decay-per_fold_causal-false-false | 229.973 | 229.715/229.715 | +6.445 |
| nested-signal_notional-active-mode_1_decay-per_fold_causal-false-false | 230.043 | 229.785/230.043 | +6.445 |
| nested-notional-off-mode_1_decay-per_fold_causal-false-false | 222.562 | 222.562/222.562 | +4.125 |
| nested-notional-shadow-mode_1_decay-per_fold_causal-false-false | 229.223 | 229.223/229.223 | +6.230 |
| nested-notional-active-mode_1_decay-per_fold_causal-false-false | 229.805 | 229.547/229.547 | +6.445 |
| nested-unit-off-mode_1_decay-per_fold_causal-false-false | 222.844 | 222.586/222.586 | +4.125 |
| nested-unit-shadow-mode_1_decay-per_fold_causal-false-false | 230.066 | 229.809/229.809 | +6.445 |
| nested-unit-active-mode_1_decay-per_fold_causal-false-false | 229.613 | 229.355/229.355 | +6.496 |
| nested-pct_equity-off-mode_1_decay-per_fold_causal-false-false | 220.406 | 220.406/220.406 | +2.062 |
| nested-pct_equity-shadow-mode_1_decay-per_fold_causal-false-false | 227.473 | 227.215/227.215 | +4.641 |
| nested-pct_equity-active-mode_1_decay-per_fold_causal-false-false | 227.246 | 226.988/226.988 | +4.641 |
| nested-dca_ladder-off-mode_1_decay-per_fold_causal-false-false | 221.027 | 220.770/220.770 | +2.320 |
| nested-dca_ladder-shadow-mode_1_decay-per_fold_causal-false-false | 228.539 | 228.281/228.281 | +4.641 |
| nested-dca_ladder-active-mode_1_decay-per_fold_causal-false-false | 227.914 | 227.914/227.914 | +4.684 |
| conditional-pct_equity-off-mode_4_is_only_robust-per_fold_causal-false-true | 286.418 | 286.418/286.418 | +2.797 |
| conditional-pct_equity-off-mode_5_full_robust-global-false-true | 285.172 | 285.172/285.172 | +2.328 |

Peak covers the whole shared worker/harness. Independent arm peaks are not certified.
