---
id: UX-7
type: Task
title: Show run progress as named steps and open the report when the run completes
---

## Description

When a run starts from `/compare`, the page shows a raw text console (`new_run.html`, `static/new-run.js` `followJob`). The user must read log lines to tell where the run is, and click "Open report" once it finishes. The pipeline already reports named stages through `progress(...)` in `nparity/pipeline.py`: reading endpoints, mapping, replaying, comparing, triaging.

Changes:
- Show the stages (see Boundaries for the real list) as a step list with states (waiting, running, done, failed), driven by the existing progress lines. Keep the raw console collapsed under "Details".
- On `complete`, go to the report automatically after a short pause, with a visible "Opening report..." line and the link as a fallback.
- On `failed`, show the error message in the step that failed and keep the form values so the user can fix and retry.
- Keep the `?job=` reload behaviour so a refresh resumes the same job.

## Acceptance Criteria

- Toy run from the preset shows each step in turn and lands on the report with no click.
- A failing run (unreachable URL) marks the failing step and shows the error text.
- Reloading the page mid-run resumes the same step list.
- No change to the `/run-jobs` API shape, or any addition is covered by tests in `tests/test_web_progress.py`.

## Notes

Step detection from progress strings is brittle. If matching text proves fragile, add a `stage` field to the progress callback instead and keep the string for the console.

## Boundaries

UX-3, UX-4 and UX-7 run in parallel from the same `main`. Stay inside the files below so the three branches merge without conflicts. If you need to edit a file that is not listed as editable, stop and report which file and why. Do not edit it.

- **May edit:** `app/web/templates/new_run.html`, `app/web/static/new-run.js`, `app/web/run_jobs.py`, `app/web/routes.py` (only the run-job models and handlers), and `app/web/static/nparity.css` only in a new block directly after the `.run-output [hidden]` rule, under the comment `/* UX-7 progress steps */`. New file `tests/test_web_progress.py`.
- **Must not touch:** `run.html`, `_row.html`, `_finding_body.html`, `_decision.html`, `mapping.html`, `runs.html`, `signoff.html`, `base.html`, `views.py`, `review.js`, any other CSS rule, and every existing test file.
- **Do not break what is already there:** the saved-configuration menu, the rerun and baseline controls and "Save as configuration" in `new-run.js` and `new_run.html`. The `/run-jobs` response keeps `state`, `lines`, `report_url` and `error`. Add fields only if you need them, never rename or remove one.
- **Stages come from the real progress lines**, not from a guess. Today they are: "Loading before source", "Loading after source", "Reading API endpoints", "Mapping endpoints and fields (...)", "Replaying N requests", "Comparing responses and schemas", "Triaging N findings", "Saving report with ...". There are also optional lines ("Baseline: ...", "Saved configuration ..."). Group them into steps and show unknown lines in the details console. Do not reword the lines in `nparity/pipeline.py`.
- **Tests:** all in `tests/test_web_progress.py`.
- **No drive-by changes:** no reformatting, no renamed variables.
- Port 8017. Check a toy run through the API (POST `/run-jobs`, poll `/run-jobs/{id}`) and screenshot `/compare` with the step list showing.
- Visual check: start the app with this worktree's code and the real runs (the Petstore run is in the main checkout's gitignored `runs/`): `cd /Users/temba.mazingi/Projects/aiskillsday && .venv/bin/uvicorn app.main:app --app-dir <this worktree> --port PORT`. Screenshot with `~/Library/Caches/ms-playwright/chromium_headless_shell-1244/chrome-headless-shell-mac-arm64/chrome-headless-shell --no-sandbox --hide-scrollbars --window-size=W,H --virtual-time-budget=3000 --screenshot=/tmp/NAME.png URL` and read the PNG. Stop the server afterwards. Do not commit screenshots.
