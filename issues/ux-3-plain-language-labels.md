---
id: UX-3
type: Task
title: Replace internal jargon with plain labels and add a confidence legend
---

## Description

The pages are read by an engineering manager as well as the engineer who built the service. They show internal terms with no explanation: "p(winner) · threshold", "Observed type", "Declared type", "Distribution", "Runners-up", "regression needs 0.999", and "leans regression". The probability bar has a threshold tick that nothing explains, and on the demo runs every bar is at 1.000, so the tick is invisible.

Changes:
- Rename labels: p(winner) to "Confidence", Observed type to "Type seen in responses", Declared type to "Type in the spec", Distribution to "Model's split between labels", Runners-up to "Next best matches".
- Replace "regression needs 0.999" with "needs 99.9% to be dismissed" or similar plain wording, built in `views.py` `threshold_text`.
- Show confidence as a percentage in row summaries, with the raw value in a `title` tooltip.
- Add a one-line legend under the first section: "Bar = confidence in the label. Line = confidence needed to accept without review."
- Apply the same labels on `mapping.html`.
- Keep `Source: rule | llm` but rename the badge text to "rule" and "model".

## Acceptance Criteria

- No template contains the strings `p(winner)`, `Observed type`, `Declared type`, `Distribution:` or `Runners-up`.
- Legend appears once per run page.
- Confidence shows as a percentage in row summaries and tooltips show the raw value.
- Existing tests that match old label text are updated. No analysis logic changes.
