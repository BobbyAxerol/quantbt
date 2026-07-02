# Backend Selection

QuantBT now has two native engines plus an optional Nautilus adapter. The
public V2 facade keeps selection explicit:

```python
from quantbt import BacktestEngineV2

engine = BacktestEngineV2(
    data=data,
    signals=signals,
    backend="native_vectorized",  # native_vectorized | native_event | nautilus
)
result = engine.result
```

## native_vectorized

Use this as the default research and optimizer path.

Best fit:

- signal already means target exposure or structural target;
- many symbols, many bars, many parameter combinations;
- deterministic close/high/low rules are acceptable;
- result speed matters more than exchange-like object lifecycle.

Current strengths:

- Numba hot loops;
- multi-symbol arrays;
- margin, fee, funding, liquidation diagnostics;
- target-unit and `signal_notional` sizing through `BacktestEngineV2`.

Avoid it when:

- exact order lifecycle, TIF, limit waiting, or rejection status is part of the alpha;
- pair/basket orders must be treated as a coordinated event;
- you need a production-like report from a trading engine.

## native_event

Use this when order domain matters but the run still needs to be fast.

Best fit:

- single order backtests;
- limit and IOC/GTC behavior;
- grid/DCA order plans;
- pair/basket entry and exit with frozen hedge ratios;
- validation of order status, fill price, fee, margin rejection.

Execution model:

- market orders fill at bar close with configured slippage;
- limit orders fill at the order price when `low <= price <= high`;
- IOC limit orders cancel when not touched on the order bar;
- GTC limit orders remain active until touched;
- insufficient margin rejects the order.

## nautilus

Use this as a high-fidelity validation oracle, not as the optimizer hot path.

Best fit:

- checking native behavior against a production-grade event model;
- instrument precision and exchange-style reports;
- lower-volume validation runs;
- experiments where the extra dependency and callback overhead are acceptable.

The Nautilus adapter is optional. Importing `quantbt` does not require
`nautilus_trader`; the adapter raises a clear install error only when selected.
