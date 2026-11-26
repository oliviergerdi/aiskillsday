---
id: UX-8
type: Task
title: Serve HTMX locally so the demo works without internet
---

## Description

`app/web/templates/base.html:9` loads HTMX from `https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js`. Without network access the finding rows cannot expand (they load their body with `hx-get`), and the pages give no sign of why. The design (`docs/nparity-design.md`) says the demo must survive a bad connection, and the saved `demo` run and `fake` backend exist for that reason. The script tag also has no integrity hash.

Changes:
- Download `htmx.min.js` 1.9.12 to `app/web/static/htmx.min.js` and load it from `/static/`.
- Record the version and source URL in a comment at the top of `base.html` or in the README.
- Check the app for other external requests (fonts, scripts, images) and remove any found.

## Acceptance Criteria

- With the network disabled, the run page for `demo` loads, and expanding a finding row shows its body.
- A grep of `app/web/templates` and `app/web/static` finds no `http://` or `https://` asset URL.
- `tests/test_web.py` asserts the page references `/static/htmx.min.js`.
