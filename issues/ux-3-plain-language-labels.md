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
- New tests for the labels, the percentage and the legend are in `tests/test_web_labels.py`. No existing test file is edited. No analysis logic changes.

## Boundaries

UX-3, UX-4 and UX-7 run in parallel from the same `main`. Stay inside the files below so the three branches merge without conflicts. If you need to edit a file that is not listed as editable, stop and report which file and why. Do not edit it.

- **May edit:** `app/web/templates/_finding_body.html`, `_row.html`, `run.html` and `mapping.html` (text only), `app/web/views.py` (`threshold_text` and label helpers), and `app/web/static/nparity.css` only in a new block directly after the `.pbar .thr` rule, under the comment `/* UX-3 legend */`. New file `tests/test_web_labels.py`.
- **Must not touch:** `new_run.html`, `new-run.js`, `run_jobs.py`, `routes.py`, `runs.html`, `base.html`, `signoff.html`, `_decision.html`, `review.js`, any CSS outside your block (especially every `@media` block), and every existing test file. No existing test asserts the old label text today. If one fails after your change, stop and report it.
- **Do not change the structure of a finding row:** do not add, remove or reorder the children of `details.f > summary`. UX-4 styles them by class and position. Text and attributes only.
- `run.html` also holds the ledger, decision and sign-off controls from the review feature. Leave them exactly as they are.
- The "no template contains the strings" criterion covers every file in `app/web/templates`.
- **Tests:** all in `tests/test_web_labels.py`.
- **No drive-by changes:** no reformatting, no renamed variables.
- Port 8013, screenshots at 1280px of `demo` and the Petstore run, with one finding expanded.
- Visual check: start the app with this worktree's code and the real runs (the Petstore run is in the main checkout's gitignored `runs/`): `cd /Users/temba.mazingi/Projects/aiskillsday && .venv/bin/uvicorn app.main:app --app-dir <this worktree> --port PORT`. Screenshot with `~/Library/Caches/ms-playwright/chromium_headless_shell-1244/chrome-headless-shell-mac-arm64/chrome-headless-shell --no-sandbox --hide-scrollbars --window-size=W,H --virtual-time-budget=3000 --screenshot=/tmp/NAME.png URL` and read the PNG. Stop the server afterwards. Do not commit screenshots.
