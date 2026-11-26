---
id: UX-9
type: Task
title: UI polish found while reviewing the UX-1 to UX-8 work
---

## Description

Five small defects found while checking the merged UX work in a browser, including a dark-mode pass. Each is small. They are one issue because they all touch the same few files and none changes behaviour.

1. **Dark mode: native dropdowns are bright white.** The "Configuration" and "Compare with" selects in the "Rerun a configuration" panel on `/compare`, and the "compare with" select under the scope line on the run page, render with a white background in dark mode. Cause: only `.comparison-form select` is styled. Fix: set `color-scheme: light dark` on `:root`, and give every `select` the same background, text and border as the form inputs. Checked and fine in dark mode: runs list, mapping page, sign-off page, run page, new-run form fields.
2. **Header nav wraps at 390px.** "New run" breaks onto two lines. Keep each nav item on one line (`white-space: nowrap`) and tighten padding or gap on small screens so the four items fit.
3. **Repeated endpoint inside a group.** Each finding row inside an endpoint group repeats "GET /store/inventory → GET /store/inventory", which the group header already shows. Inside a group, show only what differs: the badges (`new`, accepted or rejected) and a `→ unmapped` marker when it applies. Keep the `.f-ep` element, because the mobile CSS selects it by class.
4. **Run progress can start off-screen.** On `/compare` the step list sits below a tall form (the "Rerun a configuration" panel plus the form). On a short window the progress is not visible when a run starts. When a run starts, scroll the step list into view. Check at 1280x720 and at 390px.
5. **Old run ids show raw in the runs list.** `views.run_name` only strips an id that ends in a 12-character hash, so `2026-11-26T124434-toy` shows in full while `...-petstore-4676e543c67a` shows as `petstore`. Make the hash suffix optional.

## Acceptance Criteria

- In dark mode (Playwright `color_scheme="dark"`) no native `select` on `/compare` or the run page has a white background. Screenshot both pages.
- At 390px the header nav shows Runs, New run, Findings and Mapping with no item wrapping.
- A group row no longer repeats the group's endpoint pair. The `new` and accepted or rejected badges still show on the row.
- Starting a run from `/compare` brings the step list into view at 1280x720 and 390px. Verify with a toy run.
- `run_name("2026-11-26T124434-toy") == "toy"` and the existing hashed case still gives `petstore`.
- Tests are in `tests/test_web_polish.py`. Rendering checks are done with screenshots, described in the PR.

## Out of scope

- The headline wording ("0 confirmed regressions" next to "Regressions to review") is a copy decision for the team.
- The number of findings in the Petstore run (51 for what the pitch calls a handful) is a findings-logic question in `nparity/`, not a UI one.
- Do not change the ledger, sign-off, saved-configuration or progress behaviour.

## Boundaries

No other UX issue is in flight, so this issue owns the web UI files. Stay inside them. If you need a file outside this list, stop and report which one and why.

- **May edit:** `app/web/static/nparity.css`, `app/web/templates/_row.html`, `app/web/templates/run.html` (group rows only), `app/web/templates/base.html` (nav markup only if CSS cannot do it), `app/web/static/new-run.js` (scroll into view only), `app/web/views.py` (`run_name` only). New file `tests/test_web_polish.py`.
- **Must not touch:** `nparity/`, `config/`, `review.js`, `signoff.html`, `_decision.html`, `run_jobs.py`, `routes.py`, and every existing test file.
- **Keep the structure of a finding row:** the children of `details.f > summary` stay `.f-ep`, `.f-path`, `.f-kind`, `.pbar`, `.f-reason`. The mobile CSS selects them by class.
- No reformatting and no drive-by changes.

## Verification recipe

Run the app from this worktree's own directory, so any test run you start is written under this worktree's `runs/` and not to the shared one. For the Petstore run, copy it in first (the folder is gitignored):

```
cp /Users/temba.mazingi/Projects/aiskillsday/runs/2026-11-26T124642-petstore-4676e543c67a.yaml runs/
/Users/temba.mazingi/Projects/aiskillsday/.venv/bin/uvicorn app.main:app --port 8019
```

Dark and light screenshots with Playwright, without adding it to the project (corporate TLS needs `--native-tls`). Save this as `/tmp/shot.py` and run `uv run --native-tls --with playwright python /tmp/shot.py URL OUT.png W H dark`:

```python
import sys
from playwright.sync_api import sync_playwright
url, out, w, h, scheme = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
exe = "/Users/temba.mazingi/Library/Caches/ms-playwright/chromium_headless_shell-1244/chrome-headless-shell-mac-arm64/chrome-headless-shell"
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=exe, args=["--no-sandbox"])
    pg = b.new_page(viewport={"width": w, "height": h}, color_scheme=scheme)
    pg.goto(url, wait_until="networkidle")
    pg.screenshot(path=out)
    b.close()
```

Read the PNG files to check them. Stop the server when done. Do not commit screenshots.
