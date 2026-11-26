---
id: UX-1
type: Story
title: Group findings by endpoint on the run page so a real run is readable
---

## Description

The run page lists every finding as its own row. The Petstore run (`runs/2026-11-26T124642-petstore-4676e543c67a.yaml`) renders 52 rows: 40 regressions and 11 unsure. Many are the same root difference repeated per field, for example `GET /pet/{petId}` appears for `$.category`, `$.code`, `$.message`, `$.photoUrls` and `$.photoUrls[0]`. The pitch promises "4 items for the engineer to read". A reviewer will stop reading long before row 52.

Group the findings inside each section (Regressions, Unsure, Intended) by endpoint pair. Each group shows one summary line and expands to its findings.

Changes:
- `app/web/views.py`: add a grouping step (display only, no analysis) that returns groups keyed by `(endpoint, new_endpoint)`, ordered by the worst finding in the group, then by count.
- `app/web/templates/run.html` and `_row.html`: render a group header (`endpoint → new endpoint`, number of findings, lowest confidence in the group) with the findings nested under it.
- Groups with more than 3 findings are collapsed by default. The first regression group stays open so the page still opens on an example.
- Reasons stay per finding, inside the group. Do not repeat the reason on the group header.

## Acceptance Criteria

- The Petstore run renders no more than one header row per endpoint pair per section, and the page shows the number of groups next to the section title.
- Group header shows finding count and the lowest `p` in the group.
- Expanding a group shows the same finding rows and the same HTMX body as today.
- Section order and the "never auto-dismissed" wording are unchanged. No finding disappears: the sum of group counts equals the section count.
- `tests/test_web.py` covers a run with two findings on one endpoint and one on another, and asserts two groups.
- Checked at 1280px and 390px width.

## Out of scope

Merging findings in the pipeline (`nparity/findings.py`) or reducing the number of findings. If the same root cause produces many findings, raise that as a separate issue against the findings logic.
