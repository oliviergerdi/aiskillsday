# PRD 0001: Sign-off report and accepted ledger

**Status:** Draft · **Priority:** P0 · **Pitch promise:** "Hand the manager a short list at cutover, with a confidence on every item"

## Problem

The engineering manager approves the cutover and needs one short page, not a raw diff. Today `nparity run` prints a terminal summary and saves a run YAML. There is no sign-off artifact, no way to record that a human reviewed a difference, and no way to see what changed since the previous run. Every re-run during the project shows already-reviewed differences as if they were new.

## Users

- Backend engineer: reviews differences once and does not want to review them again on the next run.
- Engineering manager: wants open items, accepted items with who and when, the score and the thresholds, on one screen.

## Goals

1. A human can record a decision on a finding. It persists across runs.
2. A run can be compared with an earlier run: new, unchanged, resolved.
3. A sign-off page lists open items, accepted items, score, telemetry and thresholds used.

## Requirements

| # | Requirement | Acceptance |
|---|---|---|
| 1 | Ledger file `accepted.yaml`, checked into the repo. Key: endpoint pair + path + kind. Fields: decision, reviewer, date, note | A finding in the ledger is shown as `accepted (ledger)`. A ledger entry whose finding disappeared is listed as stale |
| 2 | `nparity accept RUN_ID FINDING_ID --by NAME --note TEXT` appends to the ledger | Round-trip test |
| 3 | `--baseline RUN_ID` marks each finding as new, unchanged or resolved against an earlier run | E2E test with two runs |
| 4 | `--format json\|md` writes the run summary to stdout or `--out` | JSON validates against the `Run` model; Markdown lists regressions, then unsure, with endpoint, path, p, reason |
| 5 | Web: `/runs/{id}/signoff` page, print-friendly, same data as the Markdown report, including each target (PRD 0006 #9) with pass or fail | Page test; no analysis in the template |

## Out of scope

CI integration, exit-code gating, PR comments, approval workflow inside the app, Jira or Slack integration. Hosted service and user accounts moved to PRD 0007.

## Risks

- A ledger that accepts too much hides regressions. Entries are explicit, per finding, never wildcarded. The tool never accepts a regression itself, only a named human does.
- The ledger key must survive small path changes. Start with exact match and report stale entries.

## Success

A re-run after review shows only new differences. The sign-off page for a clean run fits on one screen.
