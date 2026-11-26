# PRD 0008: Seed generation and per-endpoint coverage

**Status:** Draft · **Priority:** P1 · **Pitch promise:** "Requests come from the old API's OpenAPI spec and seed values", "tells you where the differences are and where to focus"

## Problem

1. **Seeds are hand-written** (`fixtures/*/seeds.yaml`, mostly GET). The engineer must know which ids exist and which values matter before the first run.
2. **A guessed value gives false parity.** An id that does not exist returns 404 on both sides, and "not found equals not found" looks like a match.
3. **The report does not say what was actually compared.** A run with a spec, a run with samples and a run with nothing but two URLs look the same.
4. **Contract and behaviour are mixed.** The spec already lists every method (POST, PUT, DELETE) and its schemas, so contract differences need no call. Only behaviour needs a call, and calls to mutating methods change data.

## Goals

1. Generate reasonable seeds automatically, with hand-written seeds always winning.
2. Compare the contract of every endpoint from the spec, without calls.
3. Compare behaviour only where a safe, meaningful request exists.
4. Tell the user, per endpoint, what was and was not compared. Without a spec the product does basic checks only, and says so.

## Seed sources, most trusted first

1. Hand-written seeds (`seeds.yaml`). Always override.
2. Spec `example`, `examples` and `default` on parameters and schemas.
3. Spec `enum` values (capped) and numeric bounds.
4. Discovery: GET calls to the old API's list or search endpoints, harvesting ids and values from responses for dependent parameters (for example `GET /pet/findByStatus` then `petId`). GET only.
5. Provided samples (curl lines, Postman collection, saved responses).
6. Type-only guesses (integer 1, string "test"). Lowest trust. Never used for path ids.

## Requirements

| # | Requirement | Acceptance |
|---|---|---|
| 1 | `nparity seeds` writes a seeds file from the spec using sources 2, 3 and 6, with every value tagged by source | Unit test on the toy v1 spec; file round-trips through `load_seeds` |
| 2 | Discovery (source 4) is opt-in, GET only, and ignores any endpoint not listed as safe. A harvested value is used only if a name rule matches (`petId` to `id` or `petId`). Ties may go to the model and are tagged `guessed` | Test against the toy API; test that a non-GET call is never made |
| 3 | A seed for a path parameter must come from sources 1, 2, 4 or 5. A type-only guess is never used for a path id | Test that such an endpoint is reported as `not seeded` |
| 4 | Contract layer: for every endpoint and method in the specs, compare operations, parameters, request and response schemas, required flags, enums and status codes with no calls. Findings follow PRD 0006 rules (declared differences, never labelled regression) | Test on a POST and a DELETE endpoint of the toy specs |
| 5 | Behaviour layer: replay GET by default. Other methods need `methods:` in the seeds (PRD 0002 #8). Discovery never changes that | Existing behaviour test stays green |
| 6 | A response pair where both sides return the same error (for example 404 and 404) is counted as `not compared`, never as a match | Test with a nonexistent id |
| 7 | The old and new side must serve the same data for a seed to count. Discovered values are checked on the new side, and a mismatch is reported as `data differs, comparison not valid` | Test with a seed present on one side only |
| 8 | Coverage table, per endpoint: seed source, contract compared (yes or no), behaviour compared (yes, no or why not: mutating, not seeded, both errors) | Page test |
| 9 | No spec on a side: no generated requests and no discovery. Only user-supplied sample requests are replayed, and only status code and response shape (keys and types) are compared. The report shows the banner below | Test with two URLs and one sample file |
| 10 | Banner for the no-spec case, shown at the top of the report and in the CLI summary: "No API spec: basic checks only. N of M endpoints compared. This is not a full comparison." | Page and CLI test |

## Out of scope

- Authenticated discovery. It needs the authorization token option, which is a release requirement and not built (see `docs/problem-definition.md`).
- Creating or deleting data to produce seeds.

## Demo

Not part of the live demo. The toy APIs and Petstore ship with seed files.

## Open

- Cap on enum values and on discovered values per parameter.
- Whether discovery results are saved into the run file so a re-run is repeatable.
