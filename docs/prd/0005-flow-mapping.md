# PRD 0005: Flow mapping, from one old call to a group of new calls

**Status:** Draft · **Priority:** P0 · **Pitch promise:** "Pair moved endpoints and renamed fields", "tells you where the differences are and where to focus"

## Problem

The mapper pairs each old endpoint with at most one new endpoint (`nparity/map.py`, `EndpointMap`). Real migrations do not stay one to one. Example from our own CSOM to Mesh move (same vendor, new process): one synchronous call that returns hits becomes several calls. Get a token, choose a screening configuration, create and screen a customer (synchronously, or asynchronously with a completion webhook), then read the hits with a second, paged call. Today nParity reports the old call as "missing in new" and the new calls as "added". That is the same false picture the pitch says a plain diff gives for renames, one level up.

## Users

- Backend engineer who must move code from the old API to the new one. Needs to know which new calls replace each old call, in what order, and what has no counterpart.

## Goals

1. Map each old operation to an ordered group of new operations, each with a role.
2. Show the same group on the report with a probability and the source text behind it.
3. Work when the new side has asynchronous steps (webhook, callback, polling) and paged reads.
4. Say clearly what has no counterpart on either side.

## Requirements

| # | Requirement | Acceptance |
|---|---|---|
| 1 | Data model: `FlowMap` with `old_op`, an ordered list of `steps` (`new_op`, `role`, `p`, `status`, `source`) and `unmatched_old`, `unmatched_new` | Model validates; JSON round trip |
| 2 | Roles, a closed list: `direct` (one to one), `auth` (get a token), `configure` (choose a profile or configuration), `start`, `await` (webhook, callback, poll), `read` (fetch results), `page` (pagination of results), `none`. `auth` and `direct` came from drafting the CSOM to Mesh key | Unit test per role on a toy flow |
| 3 | Candidates are found deterministically first: name, path, tag and schema-field overlap, and dependent ids (a field returned by one call and required by another) | Test: the toy sync-to-async pair is in the candidate set |
| 4 | The model answers one closed question per candidate: which role does this new operation play for this old operation. One token, same evaluator as today | Test with `FakeBackend`; no free-text answer is parsed |
| 5 | Steps are ordered by dependency edges, not by the model | Test: shuffled input gives the same order |
| 6 | Each step cites the spec or doc sentence it relied on (PRD 0003 rule: a quote not found verbatim is dropped and flagged) | Test with a made-up quote |
| 7 | Below `needs_review` a step shows as `unsure`. A flow is never auto-accepted as complete | Threshold test |
| 8 | Report page and Markdown group new calls under their old call, with a "no counterpart" section on each side | Page test |
| 9 | Answer key format for flows (`old_op` to ordered `new_ops` with roles, optional `variants` where the new API offers more than one valid path, any one accepted) and a score | `nparity key` writes a skeleton; score test |
| 10 | A toy flow pair in `app/toys`: one synchronous v1 call, and v2 as start, completion callback and paged read. No public sample has this shape, so the toy is the test fixture. The Wikipedia RESTBase to MediaWiki REST pair in `samples/api-versions/` covers a different URL tree | Pipeline test on the toy pair |

## Out of scope

Executing a flow, replaying webhooks, generating migration code, judging whether the new flow is better, mapping more than two API versions at once.

## Risks

- A plausible but wrong grouping. Mitigation: cited source, probability, `unsure` below the threshold, engineer confirms.
- A missing role (a step the docs never mention) is invisible. Show the count of new operations not placed in any flow.
- Closed role list may not fit every API. Keep `none` and report how many candidates land there.

## Success

On a real CSOM to Mesh example, the engineer sees for each old operation the new operations that replace it, in order, with roles, and the operations with no counterpart. Score against an engineer-written key (`fixtures/flows/csom-to-mesh.key.yaml`, worked example `docs/examples/csom-to-mesh.md`, scoring defined there): **[TO FILL: target, key confirmed_by]**.
