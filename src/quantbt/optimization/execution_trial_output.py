"""Explicit transient WFO output policy; final financial config stays intact."""

from dataclasses import replace


def execution_trial_config(config, *, route, metadata):
    policy = metadata.get("execution_trial_output", "endpoint")
    if policy == "endpoint":
        return config
    if policy != "account_paths_v1":
        raise ValueError("execution_trial_output must be endpoint or account_paths_v1")
    if route not in {"event_driven", "order_commands"}:
        raise ValueError("account_paths_v1 requires event_driven or order_commands WFO")
    if config.audit_mode in {"dual_run_sampled", "sampled"}:
        raise ValueError("account_paths_v1 cannot remove sampled-oracle RNG consumption")
    # Standard retains account paths, fills and callback inputs, but does not
    # build public canonical traces. Independent final audit is still caller-owned.
    return replace(config, report_level="standard", reactive_kernel_mode="single_pass",
                   audit_mode="native_trace")
