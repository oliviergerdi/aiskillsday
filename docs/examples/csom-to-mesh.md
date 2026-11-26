# Worked example: CSOM to Mesh

**Status:** DRAFT v2 for engineer review. **BLUF:** One provider (ComplyAdvantage) replaced its searches API (CSOM) with a customer and workflow API (Mesh). Ten old calls map to new calls, one of them only partly. Three old calls have no counterpart found. Five new calls have no old counterpart. Each old call becomes one or several new calls, and the hits move from the create response to a second call. This is the case nParity must handle (PRD 0005, PRD 0006). It is the evidence example, not the live demo.

Checked against the vendor documentation (Mesh API FAQs and docs, CSOM API docs) for how each API behaves. The old-to-new pairing is a judgement and is **not yet confirmed by an engineer**. Machine-readable key: `fixtures/flows/csom-to-mesh.key.yaml`.

## What changed in my first draft
The first draft said Mesh completes asynchronously through a webhook. The documentation says Mesh has both. The synchronous create-and-screen blocks until a chosen step (`last_sync_step`). With `ALERTING` the response carries the alert ids, and the hits come from a second call, `GET /v2/alerts/{id}/risks`. The `WORKFLOW_COMPLETED` webhook belongs to the asynchronous call. The key now lists both as variants and accepts either.

## What the engineer sees today
A plain diff says: old `POST /searches` is missing, and the new calls are added. It cannot say which new calls replace which old call, or that the hits moved.

## What nParity should show
| Old call | Becomes (in order) | Roles |
|---|---|---|
| `POST /searches` (hits in the response, first 100) | **sync:** token, list configurations, create-and-screen (sync), read risks (paged). **async:** token, configurations, create-and-screen (async), wait for `WORKFLOW_COMPLETED`, read cases, alerts, risks | auth, configure, start, page (sync). Adds await, read, read (async) |
| `GET /searches/{id}/details` | find customer, cases, alerts, risks (paged) | read, read, read, page |
| `GET /searches/{id}` | find customer by external id | direct |
| `PATCH /searches/{id}` | update-and-rescore | start |
| `GET` and `PATCH /searches/{id}/monitors` | `GET` and `PATCH /v2/customers/{id}/monitor` | direct |
| `DELETE /searches/{id}` | `PATCH .../monitor` (monitoring off) | direct, partial |
| `GET /searches/{ref}/entities/{provider}` (hits beyond 100) | risks, paged | page |
| `PATCH /searches/{id}/entities` (decision on a hit) | `POST /v2/alerts/{id}/risks/{id}/decision` | direct |
| `PATCH /searches/{id}/search-profile` | `PATCH .../monitor` with a configuration id (to confirm) | direct |
| `GET /searches`, monitor differences, monitor acknowledge | none found | unmatched |

New calls with no old counterpart: rescreen on demand, audit log, edit a configuration, batch processing, list cases.

## What the report should say about the biggest change
The hits are no longer in the create response. The engineer now handles a token fetch, a configuration choice, a choice between synchronous and asynchronous screening, and a paged second call for the hits. These are the rows to focus on first.

## How a run is scored against the key
- **Op recall:** old ops with the correct set of new ops (any one variant), divided by old ops in the key.
- **Step precision:** correct steps, divided by steps reported.
- **Order and roles:** steps in the right order with the right role, divided by steps in the key.
- **Unmatched:** old and new unmatched lists compared as sets.
- **No source, no credit:** a step without a cited source line counts as wrong.
Targets are set per run (PRD 0006 #9). Suggested starting values: **[TO FILL]** after the engineer reviews the key.

## Open questions for the engineer
1. Do the monitor `differences` and `acknowledge` calls map to the `CASE_ALERT_LIST_UPDATED` and `CASE_TRANSITIONED` webhooks, or to nothing?
2. Is `GET /searches` used for anything we lose?
3. Does `PATCH .../search-profile` really map to the monitor configuration call?
4. Which variant do you use, sync or async? Add a doc URL or quote for each row.
