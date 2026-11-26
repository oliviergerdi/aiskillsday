# PRD 0002: Real-API readiness

**Status:** Draft · **Priority:** P0 · **Pitch promise:** "Built from the old API's OpenAPI spec and seed values", "mask timestamps and generated IDs, sort unordered lists, fixed rules", "backend engineer who owns both APIs"

## Problem

The prototype is proven on two toy services and the public Petstore. A backend engineer who owns a real service hits four walls:

1. **No auth.** Replay sends no request headers. Any service behind a token cannot be replayed (`nparity/replay.py`, `app/web/run_sources.py` have no header support).
2. **Noise rules are hand-written per toy.** `config/noise.yaml` names `POST /orders` and `GET /orders`. The pitch says timestamps, generated IDs and list order are handled by "fixed rules". A real API has none of those rules out of the box.
3. **Seeds are hand-written and mostly GET.** `fixtures/petstore/seeds.yaml` restricts to GET. Real services need request bodies, pagination and dependent values (an id returned by one call used in the next).
4. **No score outside the toys.** The pitch says each run is checked against an answer key. Only the toy key exists, so a real run has no accuracy signal.

## Goals

1. Run against an authenticated API with no secrets stored in run files.
2. Common noise removed by default, with a report of what was masked and why.
3. Request generation covers bodies and pagination from the OpenAPI schema plus seeds. Seed generation and per-endpoint coverage are specified in PRD 0008.
4. A real run can be scored against a small answer key the user writes.

## Requirements

| # | Requirement | Acceptance |
|---|---|---|
| 1 | `--old-header "Authorization: env:OLD_TOKEN"` and the same for new. Values read from environment at run time. Run YAML stores header names only | Test with a transport that asserts the header; test that the saved run contains no secret value |
| 2 | Default noise rules in `config/noise.yaml` under `defaults`: ISO 8601 timestamps, UUIDs, epoch-like integers in fields named `*At`, `*_at`, `timestamp`, `created`, `updated`. User rules override | Unit tests per rule; `Run.noise` lists each masked path with the rule name |
| 3 | List order: when items share a stable key (`id`, `uuid`, `key`), sort by it before diffing. Otherwise report order as a finding | Unit test with shuffled lists |
| 4 | Detect unstable fields without rules: replay the same request twice against the old API and mask paths that differ between the two calls | Test with a toy endpoint returning a random value; costs one extra old-API call per request, behind `--probe-noise` |
| 5 | Request bodies built from the schema (required fields, enums, examples) with `seeds.yaml` overriding by field name | Test on a POST endpoint of the toy v1 spec |
| 6 | Pagination: follow `page`/`offset`/`cursor` parameters for a configured number of pages, so off-by-one last pages are reachable | Toy seed `page=2` case scores as before |
| 7 | Answer-key template: `nparity key RUN_ID` writes a YAML skeleton from a run for the user to fill in and then use with `--answer-key` | CLI test |
| 8 | Safe mode stays default: non-GET methods require `methods:` in seeds, as today | Existing behaviour test stays green |

## Out of scope

Traffic capture, database side effects, OAuth flows that need a browser, GraphQL, non-JSON bodies.

## Risks

- Default noise rules can mask a real regression (a timestamp that should have kept its timezone). Every masked path is listed in the report and can be turned off per rule.
- Noise probing doubles old-API load. Keep it off by default.

## Success

An engineer points nParity at two authenticated staging services with two header flags, one seeds file and one intent paragraph, and gets a first report with no hand-written noise rules for timestamps, UUIDs or list order.
