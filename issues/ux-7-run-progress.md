---
id: UX-7
type: Task
title: Show run progress as named steps and open the report when the run completes
---

## Description

When a run starts from `/compare`, the page shows a raw text console (`new_run.html`, `static/new-run.js` `followJob`). The user must read log lines to tell where the run is, and click "Open report" once it finishes. The pipeline already reports named stages through `progress(...)` in `nparity/pipeline.py`: reading endpoints, mapping, replaying, comparing, triaging.

Changes:
- Show the five stages as a step list with states (waiting, running, done, failed), driven by the existing progress lines. Keep the raw console collapsed under "Details".
- On `complete`, go to the report automatically after a short pause, with a visible "Opening report..." line and the link as a fallback.
- On `failed`, show the error message in the step that failed and keep the form values so the user can fix and retry.
- Keep the `?job=` reload behaviour so a refresh resumes the same job.

## Acceptance Criteria

- Toy run from the preset shows each step in turn and lands on the report with no click.
- A failing run (unreachable URL) marks the failing step and shows the error text.
- Reloading the page mid-run resumes the same step list.
- No change to the `/run-jobs` API shape, or the change is covered by `tests/test_web_runs.py`.

## Notes

Step detection from progress strings is brittle. If matching text proves fragile, add a `stage` field to the progress callback instead and keep the string for the console.
