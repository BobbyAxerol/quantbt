# Order Lifecycle Contract

Orders are modeled as explicit commands and state transitions. A command may be
accepted, rejected, outside the tape, or a no-op; those outcomes are distinct
from fills. An accepted order progresses through the lifecycle registry rather
than being inferred from a final position change.

```text
CREATED -> WAITING_PARENT -> ACTIVE -> PARTIALLY_FILLED -> FILLED
                                  |             |
                                  +--> CANCELED/EXPIRED/REJECTED/LIQUIDATED
```

The registry covers place, activate, amend, replace, cancel, expire, fill,
reject, liquidation, and package commit/abort actions. Parent-child and OCO
relationships are represented in the command model. The current OHLC execution
model has deterministic sibling cancellation semantics, not an exchange-native
order-list API or L2 queue simulation.

`audit` results retain command and order-event reports. `score` results may
retain only the accounting necessary to rank candidates. This retention choice
does not change lifecycle transitions.
