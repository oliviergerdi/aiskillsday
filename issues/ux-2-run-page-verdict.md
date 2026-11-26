---
id: UX-2
type: Task
title: Give the run page a verdict, a readable header and no dead controls
---

## Description

The run page does not answer "will we break anything?". The `<h1>` is two raw URLs (`app/web/templates/run.html:7`), and the verdict is five equal count tiles. Every expanded finding also shows disabled Confirm and Override buttons with the text "ledger: stretch" (`_finding_body.html:24`), which looks broken.

Changes:
- Add a one-line verdict above the tiles: "N regressions and M unsure need review" or "No regressions found". Colour follows the worst status.
- Replace the URL `<h1>` with the run name. Show `old → new` as the subtitle.
- Show the intent note path as a link only if the file is served, otherwise plain text.
- Remove the Confirm and Override buttons and the "ledger: stretch" text. PRD 0001 adds the ledger later.
- Remove the reason text from the row summary or from the expanded body, not both (`_row.html:8` and `_finding_body.html:23` both print it).
- A run with zero findings shows one "Nothing to review" panel instead of three "None." sections.
- Move "endpoint decisions by LLM" out of the answer-key line. It is not part of the score.

## Acceptance Criteria

- Run page for `demo` shows the verdict line "3 regressions and 1 unsure need review" above the tiles.
- A run with no findings shows "No regressions found" and one empty-state panel.
- No element with the text "ledger: stretch" or a disabled `.btn` remains in any template.
- Each finding's reason appears once on screen when expanded.
- `tests/test_web.py` asserts the verdict text for a run with regressions and for a clean run.
