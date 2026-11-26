# nParity: Problem Definition

**Team:** Chai-GPT · **Event:** SA PDE AI Skills Day, The (AI)mazing Race · **Stage:** 1, find the problem
**Status:** DRAFT. Items marked **[TO FILL]** need real data from the team before submission. Nothing in this page is invented evidence.

## BLUF

When a team rewrites an HTTP service, the only way to learn "will we break anything?" is to compare old and new responses by hand or by reading a wall of raw diffs. nParity replays the same requests against old and new, removes noise, maps renamed endpoints and fields, and triages each remaining difference against the stated intent of the rewrite, with a confidence the reviewer can act on. The reviewer reads a handful of items, not hundreds.

## 1. Problem clarity and specificity

### Who has it

| Persona | Role in the problem |
|---|---|
| **Primary: backend engineer who owns the cutover of one rewritten HTTP/JSON service** | Must prove the new service behaves like the old one, apart from the changes the team chose to make. |
| **Secondary: engineering manager or tech lead who signs off the cutover** | Needs a defensible answer to "is it safe to switch?" without reading code or raw diffs. |

Context where it occurs today: our own rewrites and migrations (the V2 greenfield rebuild of nKYC Africa, and the CSOM to Mesh migration). These are motivation only, described in aggregate. No product code, data or credentials are used in the prototype.

### The pain point

1. **Raw diffs are mostly noise.** Generated IDs, timestamps and list ordering differ on every call, so a plain diff of old vs new is full of differences nobody cares about.
2. **Renames and moves look like breakage.** A renamed field (`fullName` to `name`) or a moved endpoint (`/customers/{id}` to `/clients/{clientId}`) shows up as "missing" plus "added", and a plain diff cannot pair them.
3. **Intended changes are mixed in with regressions.** The team decided some things would change (status 200 to 201, a dropped deprecated field). Someone has to check every difference against that intent by hand.
4. **Subtle regressions are easy to miss.** Examples seeded in our toy services: a total that rounds 10.005 to 10.0 instead of 10.01, an off-by-one that makes the last page empty, a field missing for one customer type.
5. **Sign-off has no confidence signal.** A reviewer cannot tell which "looks fine" calls are solid and which are guesses.

### Problem statement

> Backend engineers who cut over a rewritten HTTP service spend hours reading raw old-vs-new diffs to separate noise, intended changes and real regressions, and still cannot say how sure they are.

### Narrow scope

- **In:** JSON-over-HTTP APIs, old vs new, including a provider moving to a new API with a different flow. Described by an OpenAPI spec, documentation or sample responses (a spec gives the best result, PRD 0006). Replay when both sides are reachable.
- **Out:** UI testing, load or performance parity, database or data-migration parity, executing or implementing the migration, anything needing real customer data.

## 2. Evidence of real need

We keep this section honest: what we have, what we do not have yet, and how we get it today.

### What we have

| Evidence | Source | Type |
|---|---|---|
| The rewrite problem exists on our own roadmap: V2 greenfield rebuild, Mesh replacing CSOM. Parity gates and characterization tests are already part of the V2 planning docs (RFCs). | Team's own RFCs and planning docs (not copied here) | Observed practice, qualitative |
| Existing tools (Diffy, Scientist) replay and diff but do not map renames or triage against intent. This is the gap we target. | `docs/nparity-build-spec.md` | Team analysis |
| The triage step is technically feasible and cheap: about $0.00007 and 0.6 s per LLM call; correct choice among 10 options at p 0.995 to 1.000 and among 30 options at p 0.80 to 0.89. | `docs/logprobs_report.md` (66 calls, toy prompts only) | Measured |

The measured row supports feasibility, not need. It does not show that people want this.

### What we do not have yet [TO FILL]

- Interviews with engineers or leads who have done a service cutover: how they checked parity, how long it took, what slipped through.
- Any count or timing from a real cutover on our teams, shared in aggregate only.

### How we get evidence today

1. **Quick interviews, 15 minutes each, 3 to 5 people** (engineers and one lead who signed off a cutover). Questions:
   - How did you check the new service matched the old one?
   - How long did it take, for how many endpoints?
   - What did you find late, or after go-live?
   - What would make you trust an automated answer?
2. **Timed manual baseline on the toy services.** Give 2 to 3 teammates the old and new toy services and the intent note, and time how long they take to classify the 10 seeded differences, and how many they get right. Compare with nParity's run time and score on the same answer key.

| Participant | Time to classify | Correct of 10 | Missed regressions |
|---|---|---|---|
| **[TO FILL]** | | | |
| **[TO FILL]** | | | |
| **[TO FILL]** | | | |
| nParity (Flash backend) | **[TO FILL after tuned run]** | **[TO FILL]** | **[TO FILL]** |

### What we have learned so far [TO FILL after interviews]

Write the honest result, including anything that contradicts the idea.

## 3. Opportunity and "why now"

### Cost of the status quo

Manual parity checking scales with endpoints times samples times minutes per comparison. The figures below are an **illustrative model**, not a measurement. Replace the inputs with the interview numbers.

| Input | Illustrative value | Real value **[TO FILL]** |
|---|---|---|
| Endpoints in the rewritten service | 200 | |
| Samples compared per endpoint | 3 | |
| Minutes to compare and classify one sample by hand | 2 | |

Illustrative result: 200 × 3 × 2 = 1,200 minutes = **20 hours** for one full pass, repeated for every release candidate until cutover.

nParity's cost is measured, not modelled: about $0.00007 per LLM decision (measured), and the model only handles decisions the rules cannot (the mapper tries rules first).

### Existing alternatives

| Alternative | What it does | Gap nParity fills |
|---|---|---|
| Hand-written characterization or parity tests | Exact checks written per endpoint | Slow to write for hundreds of endpoints; do not discover renames |
| Replay and diff tools (Diffy, Scientist) | Send traffic to both versions, show differences | Do not map old to new when shapes differ, and do not triage against intent |
| Manual review of raw diffs | Human reads every difference | Time cost above; no confidence signal |

### Why now

- Rewrites and migrations are active work on our teams today.
- A calibrated-enough choice from one LLM token (read from logprobs) makes triage cheap and gives each decision a probability. This was measured with a small, cheap model in this repo.
- Rules do the deterministic work (noise, numbers, rounding, counts, pagination). The LLM never judges those. This keeps the risky part small and testable.

## 4. Success definition

### Measurable outcomes

| # | Outcome | Target | How we measure |
|---|---|---|---|
| 1 | Accuracy on the answer key (10 seeded differences) | 10 of 10 correct | `fixtures/answer_key.yaml`, scored on every run |
| 2 | False regressions (intended or noise labelled as regression) | 0 | Run score |
| 3 | Regressions auto-dismissed | 0, by design | Regressions are always shown to a human |
| 4 | Reviewer workload | Reviewer reads about 4 items (3 regressions, 1 unsure), not 10 raw differences | Run report counts |
| 5 | Run cost and time on the toy services | Cents per run; run time to be measured (target under 1 minute) | Telemetry footer on the run |
| 6 | Time saved vs manual baseline | **[TO FILL]** from the timed baseline | Section 2 table |
| 7 | Confidence thresholds | Mapping accepted at p ≥ 0.95; "intended" accepted at p ≥ 0.98; below that, "unsure" | `config/thresholds.yaml`, tuned against the answer key |

Targets 1 to 5 are what the Friday demo shows. Target 6 is the real-need proof and depends on the timed baseline.

### Scope boundary

| In scope (prototype) | Out of scope |
|---|---|
| Replay old vs new from OpenAPI plus seed values | Production traffic capture |
| Rule-first mapping of endpoints and fields, LLM for leftovers | Billing, SSO, on-premise installer (hosted service: PRD 0007) |
| Noise removal, deterministic diff, type checks | Running real docfox or customer data |
| Triage against a written intent note, with confidence | Judging numbers or pagination with the LLM (always deterministic) |
| CLI and read-only web report from the same saved run | Starting runs from the web UI |
| Fake backend for tests and offline fallback, Flash backend for the demo | Jev and SampleVote backends |

### Risks and honest limits

- Flash probabilities are not calibrated. Thresholds are conservative starting points, set against a 10-item key. This is a small test set, so 10 of 10 on toys does not prove accuracy on a real API.
- Over 5 options, the model gives a ranking, not a calibrated probability. Over 30 candidates needs the tournament step, which is not yet validated.
- Results jitter slightly between runs, so the demo uses a frozen cache.

## Links

- Repo: https://github.com/oliviergerdi/aiskillsday
- Build spec: `docs/nparity-build-spec.md` · Design: `docs/nparity-design.md` · Measurements: `docs/logprobs_report.md`

## Release requirements not in the demo
- **Authorization token for authenticated API calls.** The demo replays unauthenticated public APIs only. We would have liked to support a token option (for example a bearer or API key supplied per run) but did not build it. A release needs it, because real migrations call authenticated APIs. Hosted use must keep the token run-time only and never store it (PRD 0007).
