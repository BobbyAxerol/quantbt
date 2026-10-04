"""Repository-only QMS-03 history example; no public meta selection enabled."""

from tools.qms03_history import financial_fixture


def main():
    evidence, revisions, _ = financial_fixture()
    print("Original QuantBT engine; public SMA strategy; synthetic daily market")
    print("Replay diagnostics, not observed live or economic-edge certification")
    print(
        f"Matured origins: {evidence['origin_count']}; labels: {evidence['training_rows']}"
    )
    for revision in revisions:
        print(
            f"Origin {revision.task.origin.date()}: pool={len(revision.task.candidates)}, panel={len(revision.panel.members)}"
        )
        print(
            f"  Task={revision.task.task_id[:12]}, anchor={revision.task.anchor_candidate_evaluation_id[:12]}"
        )
        for row in revision.training_rows:
            print(
                f"  Trial label {row.candidate_evaluation_id[:12]}: I={row.raw_is:.6f}, O={row.raw_forward:.6f}, Y={row.y:.6f}, Q={row.q:.6f}, weight={row.origin_weight:.3f}"
            )


if __name__ == "__main__":
    main()
