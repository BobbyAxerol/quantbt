"""Identity joins for retained clocks; list order never grants equivalence."""

from .inventory import identity


def join_task_revisions(tasks, revisions):
    """Join original tasks to exactly one complete matching revision by identity."""
    roster = {}
    for task in tasks:
        key = identity(task)
        if key in roster:
            raise ValueError("duplicate original task identity")
        roster[key] = task
    joined = {}
    for revision in revisions:
        key = identity(revision["task"])
        if key not in roster or revision["task"] != roster[key]:
            raise ValueError("revision has no identical original task")
        if key in joined:
            raise ValueError("multiple revisions require an explicit as-of revision policy")
        joined[key] = revision
    if set(joined) != set(roster):
        raise ValueError("missing original task revision")
    return [(roster[key], joined[key]) for key in sorted(roster, key=lambda k: roster[k]["origin"])]
