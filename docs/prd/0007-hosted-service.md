# PRD 0007: Hosted service next to the CLI

**Status:** Draft · **Priority:** P1 · **Pitch promise:** "on whichever model your company has approved", "Cost to run", "Business model"

## Decision (26 Nov 2026)

**Open core.** The engine, CLI and file storage are free to self-host. The hosted service is the paid tier. The licence is **MIT** (`LICENSE`, 26 Nov 2026). MIT lets anyone run a competing hosted service, so the paid tier must win on what the code does not give: a managed model, accounts, retention and redaction handled for you, and support.

nParity ships two ways. A developer with a model that returns `log_probs` runs the CLI themselves (bring your own model, PRD 0003). A hosted service runs the same engine for teams that have no such model or do not want to run it. The hosted service runs on AWS and uses DeepSeek Flash, reached through Bedrock and served by Fireworks. Prices in USD.

## Problem

Today nParity is one user on one machine. State lives in files (`runs/`, `cache/`, `accepted.yaml`), the web UI has no accounts, and secrets come from the shell. PRD 0001 put "hosted service, user accounts" out of scope. A paid hosted product needs all of them.

## Users

- Backend engineer on a team with no logprobs model, who wants a link, not an install.
- Engineering manager who opens the sign-off page (PRD 0001) without running anything.

## Goals

1. The CLI and the hosted service run the same engine and produce the same run file.
2. A team can sign in, start a run, share it, and keep the accepted ledger.
3. A customer's tokens and API responses are handled by stated rules.
4. Usage is metered per run, so a price can be set (stage 3).

## Requirements

| # | Requirement | Acceptance |
|---|---|---|
| 1 | The engine is a library with one entry point. CLI and hosted worker both call it | Test: same inputs give the same `Run` JSON on both paths |
| 2 | Organisations and users: sign-in, one role to run, one to view. No approval workflow | Page tests; a viewer cannot start a run |
| 3 | Storage behind an interface: runs, cache, ledger per organisation (files for the CLI, object storage and a small database for hosted) | Contract test run against both |
| 4 | Runs execute on a queue and worker, not in the web request. Status and result are polled | Test with a long fake run |
| 5 | Tokens for the old and new API are supplied at run time and never stored. Only header names are saved (PRD 0002 #1) | Test: saved run and logs contain no secret |
| 6 | Model access through one configured backend per deployment. The hosted default is DeepSeek Flash through Bedrock | Conformance probe (evaluator spec section 7) passes on the Bedrock route before launch |
| 7 | Redaction option: mask configured JSON paths and patterns before any text is sent to a model. The report lists what was masked | Unit tests; masked values never reach the fake backend |
| 8 | Retention: runs deleted after a set number of days per organisation, and on request | Test with a clock |
| 9 | Metering: each run records findings, model calls, tokens and cost from real prices (PRD 0003 #8) | Telemetry test |

## Out of scope

Billing and payment, single sign-on, multiple regions, private networking to the customer's APIs, on-premise installer, approval workflows, Jira and Slack.

## Risks

- Customer API responses leave the customer for a third-party model host. Redaction (#7) and a clear data statement are required before any real customer data.
- The Bedrock route is stated, not verified: it must return token probabilities and its price may differ from Fireworks list price.
- Staging APIs may not be reachable from AWS.

## Success

A new team signs in, points nParity at two staging APIs, and reads a sign-off page, without installing anything. Cost per run is on the run page.

## Hosting and pricing note (26 Nov 2026)
- Run serverless, not always-on containers: idle cost about US$3 a month (assumed). Queue and worker become functions plus a queue.
- Priced as a **Migration Pass, US$149 per migration** (60 days, about 50 runs fair use), with an optional US$99 a month Team plan. Metering (#4) must count runs per pass and stop at the cap. See `docs/business-case.md`.
