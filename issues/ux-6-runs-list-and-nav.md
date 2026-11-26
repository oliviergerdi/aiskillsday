---
id: UX-6
type: Task
title: Make the runs list scannable and fix navigation naming
---

## Description

The runs list (`app/web/templates/runs.html`) is a 10-column table. At 1280px the Time and Cost columns are clipped with no cue that the table scrolls. The link text is a slug such as `2026-11-26T124642-petstore-4676e543c67a`. Zero counts look the same as non-zero ones. There is no "needs review" number, which is what a reader wants per run. The header nav has "Runs" and "Run" tabs side by side, and the brand text is not a link (`base.html:13`).

Changes:
- Run column: show the run name and a relative or short date as the link text, with the old and new URLs as the subtitle. Keep the id in a `title` attribute.
- Add a "Needs review" column (regressions plus unsure) and make it the first number column. Grey out zero counts.
- Drop the Backend column to a short label ("Fake", "Flash") with the full id in a tooltip. Merge Time and Cost into one column.
- Newest run first (check `store.list_runs` order) and a visible scroll cue or fewer columns so nothing is clipped at 1280px.
- Rename the in-run tabs to "Findings" and "Mapping". Make the brand a link to `/`.

## Acceptance Criteria

- At 1280px no column is clipped.
- A run with 40 regressions and 11 unsure shows "51" under "Needs review".
- Zero counts render in muted text.
- Brand links to `/`. Nav tabs read Runs, New run, and, inside a run, Findings and Mapping.
- `tests/test_web.py` updated for the new labels.
