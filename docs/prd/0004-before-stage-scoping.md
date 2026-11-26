# PRD 0004: Before stage, scope the change from a prototype

**Status:** Draft · **Priority:** P2 · **Pitch promise:** "Run the old API against an early prototype. See what will differ before you commit to a plan, and write the intent note from it."

## Problem

The pitch names two moments: before and during. The product serves during. In the before stage there is no intent note yet, and the engineer needs to see differences first and write the note from them. Today `triage` requires an intent note, and an empty note makes every difference a regression. The run also assumes a mapped, mostly finished new API.

## Goals

1. A run with no intent note produces a "what differs" report grouped by kind, with no labels and no regression claims.
2. The engineer can turn that report into a first-draft intent note and edit it.
3. Re-running with the edited note triages the same differences, so the before run becomes the first during run.

## Requirements

| # | Requirement | Acceptance |
|---|---|---|
| 1 | `--no-intent` (or empty note) skips triage and sets every finding to `unlabelled`. Unlabelled items are not counted as regressions | CLI and pipeline test; no LLM calls made |
| 2 | Report groups unlabelled findings by kind: moved endpoints, renamed or dropped fields, type changes, value changes, status changes | Page and CLI test |
| 3 | `nparity draft-intent RUN_ID` writes a Markdown bullet list, one line per grouped difference, each marked `TODO: intended?`. Deterministic text, no model | Golden-file test |
| 4 | Partial prototypes: an old endpoint with no match in the new spec is reported as `not built yet`, not as a regression | Test with a new spec missing one endpoint |
| 5 | The web run form allows an empty intent with copy that explains the before stage | Page test |

## Out of scope

Model-written intent notes (a draft the model invents would be read as the team's intent), effort estimates, plan generation.

## Risks

- A model-drafted note would make "intended" labels circular. Keep the draft mechanical.
- `not built yet` can hide a dropped endpoint at cutover. Show the count prominently on the sign-off page (PRD 0001) so it cannot go unnoticed at cutover.

## Success

An engineer with a half-built new service gets a readable list of what will differ, and a note skeleton they can finish in minutes.
