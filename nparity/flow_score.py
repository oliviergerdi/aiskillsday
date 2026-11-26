"""Score flow suggestions against one of the engineer-reviewed variants."""

from nparity.models import (
    FlowKey, FlowKeyEntry, FlowKeyStep, FlowKeyUnmatched, FlowMapping, FlowScores, FlowStep,
)


def require_confirmation(key: FlowKey) -> None:
    if not (key.confirmed_by or "").strip():
        raise ValueError("Set confirmed_by in the flow key after engineer review before scoring.")


def _operation_matches(expected: FlowKeyStep, actual: FlowStep) -> bool:
    return actual.new_op in (expected.new_op, expected.alt)


def _ordered_matches(steps: list[FlowStep], expected: list[FlowKeyStep]) -> int:
    # Longest ordered subsequence with the same operations and roles.
    previous = [0] * (len(expected) + 1)
    for actual in steps:
        row = [0]
        for index, step in enumerate(expected, start=1):
            if _operation_matches(step, actual) and step.role == actual.role:
                row.append(previous[index - 1] + 1)
            else:
                row.append(max(previous[index], row[-1]))
        previous = row
    return previous[-1]


def _variant_score(steps: list[FlowStep], total: int, expected: list[FlowKeyStep]) -> tuple[bool, int, int, int]:
    # Count at most one credit per expected operation, even if both an operation and its alternative appear.
    remaining = list(expected)
    correct = 0
    for actual in steps:
        index = next((i for i, expected_step in enumerate(remaining) if _operation_matches(expected_step, actual)), None)
        if index is not None:
            remaining.pop(index)
            correct += 1
    return correct == total == len(expected), correct, _ordered_matches(steps, expected), len(expected)


def _ops(values: list[str | FlowKeyUnmatched]) -> set[str]:
    return {value if isinstance(value, str) else value.op for value in values}


def score_flows(mapping: FlowMapping, key: FlowKey) -> FlowScores:
    require_confirmation(key)
    reported = {flow.old_op: [step for step in flow.steps if step.role != "none"] for flow in mapping.flows}
    recall = precision = ordered = expected_steps = 0
    for flow in key.flows:
        all_steps = reported.get(flow.old_op, [])
        cited = [step for step in all_steps if step.status == "suggested" and step.source and step.source.quote.strip()]
        matched, correct, in_order, length = max(
            (_variant_score(cited, len(all_steps), variant.steps) for variant in flow.paths()),
            key=lambda score: (score[0], score[1], score[2] / (score[3] or 1), -score[3]),
        )
        recall += matched
        precision += correct
        ordered += in_order
        expected_steps += length
    total_reported = sum(map(len, reported.values()))
    return FlowScores(
        op_recall=recall / len(key.flows) if key.flows else None,
        step_precision=precision / total_reported if total_reported else None,
        order_and_roles=ordered / expected_steps if expected_steps else None,
        unmatched_old=set(mapping.unmatched_old) == _ops(key.unmatched_old),
        unmatched_new=set(mapping.unmatched_new) == _ops(key.unmatched_new),
    )


def key_skeleton(mapping: FlowMapping) -> FlowKey:
    return FlowKey(
        flows=[FlowKeyEntry(old_op=flow.old_op, steps=[
            FlowKeyStep(new_op=step.new_op, role=step.role) for step in flow.steps if step.role != "none"
        ]) for flow in mapping.flows if flow.old_op not in mapping.unmatched_old],
        unmatched_old=mapping.unmatched_old,
        unmatched_new=mapping.unmatched_new,
    )
