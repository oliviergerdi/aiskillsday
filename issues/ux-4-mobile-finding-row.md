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
