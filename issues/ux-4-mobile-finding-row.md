---
id: UX-4
type: Bug
title: Finding row layout breaks below 760px
---

## Description

At 390px width the finding summary row is broken. The path chip (`$.currency`, `$.items`, `$.total`) overlaps the kind text ("missing in new · 1 of 3 samples"), and the expand arrow sits beside the wrong element. Cause: in the `@media (max-width: 760px)` block of `app/web/static/nparity.css`, `details.f > summary` is a two-column grid (`14px 1fr`) with `> :nth-child(n+3) { grid-column: 2 }`. The summary's children are `.f-ep`, `.f-path`, `.f-kind`, `.pbar` and `.f-reason`, and the `::before` arrow is the first grid item. `.f-path` is child 2, so it lands in the narrow marker column.

Reproduce: open `/runs/demo` at 390px width (for example with Chrome devtools device mode).

## Acceptance Criteria

- At 390px width, each finding row shows endpoint, path, kind text and confidence bar stacked in one column, with no overlap.
- The expand arrow stays beside the endpoint line.
- Desktop layout at 1280px is unchanged.
- Check the run page for `demo` and the Petstore run at 390px and 768px.
- The `.f-static` rows (noise, errors) use the same stacked layout on small screens.

## Boundaries

UX-3, UX-4 and UX-7 run in parallel from the same `main`. Stay inside the files below so the three branches merge without conflicts. If you need to edit a file that is not listed as editable, stop and report which file and why. Do not edit it.

- **May edit:** `app/web/static/nparity.css`, and only inside the existing `@media (max-width: 760px)` block. Do not touch `@media print`, the `details.g` group rules or any rule outside that block. New file `tests/test_web_mobile.py`.
- **Must not touch:** any template, `views.py`, `routes.py`, `new-run.js`, `review.js`, and every existing test file.
- **Row markup is fixed:** `details.f > summary` has the children `.f-ep`, `.f-path`, `.f-kind`, `.pbar` and `.f-reason`. This is a CSS-only fix. UX-3 is changing the text inside those elements at the same time, so select by class name and never depend on the text.
- **Tests:** write what can be asserted from the stylesheet text in `tests/test_web_mobile.py`. The rendered check is manual, see below.
- **No drive-by changes:** no reformatting, no renamed variables.
- Port 8014, screenshots at 390px and 768px of `demo` and the Petstore run (`2026-11-26T124642-petstore-4676e543c67a`).
- Visual check: start the app with this worktree's code and the real runs (the Petstore run is in the main checkout's gitignored `runs/`): `cd /Users/temba.mazingi/Projects/aiskillsday && .venv/bin/uvicorn app.main:app --app-dir <this worktree> --port PORT`. Screenshot with `~/Library/Caches/ms-playwright/chromium_headless_shell-1244/chrome-headless-shell-mac-arm64/chrome-headless-shell --no-sandbox --hide-scrollbars --window-size=W,H --virtual-time-budget=3000 --screenshot=/tmp/NAME.png URL` and read the PNG. Stop the server afterwards. Do not commit screenshots.
