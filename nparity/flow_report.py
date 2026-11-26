"""Render a saved flow mapping for Markdown export."""

import html

from nparity.models import Run

MARKDOWN_ESCAPES = str.maketrans({char: "\\" + char for char in "\\`*_[]"})


def _text(value: str) -> str:
    return html.escape(" ".join(value.splitlines()), quote=False).translate(MARKDOWN_ESCAPES)


def markdown(run: Run) -> str:
    result = run.flow_mapping
    if result is None:
        raise ValueError("This run has no flow mapping.")
    lines = [
        "# Flow mapping",
        "",
        "Review these suggested steps against the specifications before using them in a migration.",
        "",
        f"Before · {_text(run.config['old'])}",
        "",
        f"After · {_text(run.config['new'])}",
        "",
        f"{result.none_count} candidates classified as unrelated.",
    ]
    for flow in result.flows:
        lines.extend(["", f"## {_text(flow.old_op)}", "", "Needs review", ""])
        if flow.ordering_warning:
            lines.extend([flow.ordering_warning, ""])
        for index, step in enumerate(flow.steps, 1):
            lines.append(f"{index}. {_text(step.new_op)} · {step.role} · {step.status} · p={step.p:.3f}")
            if step.source:
                lines.extend([f"   > {_text(step.source.quote)}", "   >",
                              f"   > After spec · {_text(step.source.reference)}"])
            if step.warning:
                lines.append(f"   {_text(step.warning)}")
    for heading, unmatched in (("No counterpart before", result.unmatched_old),
                               ("No counterpart after", result.unmatched_new)):
        lines.extend(["", f"## {heading}", ""])
        lines.extend([f"- {_text(op)}" for op in unmatched] or ["None."])
    if result.score:
        lines.extend(["", "## Answer key score", ""])
        for label, value in (("Operation recall", result.score.op_recall),
                             ("Step precision", result.score.step_precision),
                             ("Order and roles", result.score.order_and_roles)):
            lines.append(f"- {label} · {value:.1%}" if value is not None else f"- {label} · unavailable")
        lines.append(f"- Unmatched before · {'matches' if result.score.unmatched_old else 'differs'}")
        lines.append(f"- Unmatched after · {'matches' if result.score.unmatched_new else 'differs'}")
    return "\n".join(lines) + "\n"
