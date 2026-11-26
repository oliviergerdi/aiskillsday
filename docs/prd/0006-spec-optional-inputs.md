# PRD 0006: Spec optional, static comparison

**Status:** Draft · **Priority:** P0 · **Pitch promise:** "Same engine, before and during", "tells you where the differences are and where to focus"

## Problem

1. **A spec is required today.** `pipeline.run` calls `load_spec` for both sides and fails without one. `problem-definition.md` lists "services without an OpenAPI spec" as out of scope, and the pitch says "two OpenAPI specs". Many real providers publish reference pages, not a spec.
2. **Replay is required today.** Both services must be reachable, seeded and safe to call. For a provider migration the engineer often cannot or should not call both (calls create vendor state, accounts are per tenant). The product still has to say where the differences are.

## Goals

1. A run works from whatever describes each side: OpenAPI if present, otherwise documentation pages, otherwise sample requests and responses.
2. A run with no live calls reports the differences visible in the descriptions and ranks where the engineer should focus.
3. An OpenAPI spec improves the result but is never required.

## Requirements

| # | Requirement | Acceptance |
|---|---|---|
| 1 | `--old-source` and `--new-source` accept an OpenAPI file or URL, a docs URL, a Markdown file or a folder of sample responses. The type is detected, then reported | CLI test per type |
| 2 | Docs and Markdown are turned into the same `Endpoint` list as OpenAPI: operation, parameters, request and response fields where stated, auth, callbacks | Unit test on a saved docs page; fields the page does not state stay empty, never guessed |
| 3 | Each derived item records where it came from (URL, heading, line). The report shows the source | Page test |
| 4 | `--static` skips replay. Only declared differences are reported, as in the "Declared" step of the design. No sample-based finding is produced | Test with no network client |
| 5 | In static mode a difference is labelled against the intent note only if it is a declared one. Nothing is called a regression on declared evidence alone: the label is `declared difference`, with the intent verdict beside it | Pipeline test |
| 6 | Focus ranking: differences are ordered by kind and by what the old call's callers depend on (required, returned id, status codes, pagination, async). The rule order is fixed and shown | Golden-file test |
| 7 | Quality banner: the report states the input quality of each side (spec, docs, samples) and what that cannot show | Page test |
| 8 | Replay stays available when both sides are reachable. A run may mix: spec for one side, docs for the other | Test with mixed sources |
| 9 | Targets are configurable per run in `config/targets.yaml`, with separate defaults for replay and static mode. Configurable: accuracy against an answer key, maximum items for the engineer to read, run time, run cost, share of items with a source. The run reports pass or fail per target. Not configurable, always on: no regression auto-dismissed, no `regression` label from static evidence alone, every static item has a source | Config test; test that a config that disables an invariant is rejected |
| 10 | Fixtures from `samples/api-versions/`: Petstore spec pair (two specs), Open Food Facts v2 to v3 and Wikipedia RESTBase to MediaWiki REST (sample responses only, no spec) | One static run per pair, committed expected output |

## Out of scope

Crawling a whole documentation site, reading PDFs or images, authenticated documentation portals, inferring behaviour the documents do not state.

## Risks

- Parsing documentation pages is lossy. Mitigation: provenance on every item, an `unknown` state, and the quality banner.
- A static run can look more certain than it is. Mitigation: no `regression` label without behaviour evidence (requirement 5), and the banner.
- Documentation can be wrong or stale. Say so in the banner.

## Success

An engineer gives nParity the old and new API descriptions, with or without a spec and without calling either service, and gets a ranked list of differences, each with its source. Default static targets: every old operation is mapped or listed as unmatched (none dropped silently), every item has a source, run under 60 s. Accuracy against a key: **[TO FILL once the CSOM to Mesh key exists]**.
