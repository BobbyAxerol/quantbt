# Migrating Strategy Boundaries

Existing strategy callbacks remain supported. A migration is optional and only
useful when the strategy can be expressed by a bounded, auditable command model.

## Legacy callback

```python
def on_bar_close(context):
    return [OrderCommand.market(symbol="BTC", side=1, quantity=0.25)]
```

## Context and writer

```python
def on_bar_close(context, out):
    if context.bar_index % 24 == 0:
        out.market(symbol="BTC", side=1, quantity=0.25)
```

The writer makes command ownership explicit and avoids building large Python
lists in a hot callback. It does not change the event-clock or fill semantics.

## Native IR v1

Use native IR only for the documented bounded templates such as signal target,
grid level, periodic DCA, and fixed bracket. The IR is not a generic Python
strategy compiler and should not be used to hide dynamic or future-dependent
logic. Keep the Python strategy as the readable reference and verify it against
the generated corpus before adopting a native implementation.
