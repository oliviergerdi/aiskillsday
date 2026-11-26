# nParity evaluator: adapter spec

Language-neutral spec for the LLM layer. It replaces the Ruby code in `nparity-llm-layer-sketch.md` as the source of truth; once the language is picked, the code gets written from this.

This is design, not build. Code waits for 09:15 Thursday, or for the organisers to say otherwise.

## 1. Layers

```
mapper, triage
      │  evaluate(state, questions) -> answers          (Jev-shaped, never changes)
      ▼
Cached ──► Backend
             ├── JevBackend              native, one call for all questions
             ├── LogprobChatBackend      generic: any OpenAI-compatible chat API with top_logprobs
             │      └── profile: fireworks/deepseek-v4p1-flash-1017-us   (the one we demo on)
             ├── SampleVoteBackend       generic fallback for providers without logprobs
             └── FakeBackend             answers from the answer key
```

- **Backend** is the family: how answers are obtained.
- **Profile** is one model on one provider: endpoint, quirks, limits, price. It is data, not code.
- Adding a model on an OpenAI-compatible provider means adding a profile and passing the conformance probe (section 7). It needs no new code unless its response shape is new.

## 2. The contract

### Questions (input)

| type | fields | notes |
|---|---|---|
| `noul` | `id`, `instructions`, `criteria?` {`true`, `false`} | yes/no; phrase it so yes means yes |
| `choice` | `id`, `instructions`, `criteria` {key: description} | unordered options; include `none` when the list may not cover the input |
| `score` | `id`, `instructions`, `criteria` [level0, level1, ...] | ordered, 2 to 10 levels, describe situations not degrees |

`state` is a string or a JSON object. Questions refer to parts of it with backticked paths, such as `` `old.response` ``.

### Answers (output)

| field | meaning |
|---|---|
| `value` | choice: the winning key; score: probability-weighted mean level; noul: P(yes) |
| `probabilities` | {key or level: p}, sums to 1 |
| `confidence` | 0..1, 1 minus normalised entropy of `probabilities` |
| `unseen_mass` | upper bound on probability held by options not in `top_logprobs`: 1 minus the sum of raw p over every visible token |
| `censored` | true when `unseen_mass` > 0.05, so the top answers can't be trusted as a ranking |
| `off_list` | true when the model answered with something that isn't one of our codes |
| `reason` | one sentence or null; only when requested and the backend `gives_reasons` |
| `meta` | backend id, profile id and version, latency, tokens, cached tokens, cost |

### Capabilities (per backend and profile)

| field | Jev | Flash profile |
|---|---|---|
| `calibrated` | true | false |
| `calibrated_options` | 255 | 5 |
| `max_options` | 255 | 30 |
| `batches_questions` | true | false |
| `gives_reasons` | false | true (extra call) |
| `deterministic` | n/a | false (jitter; the cache provides determinism) |

Callers read capabilities. The mapper shortlists to `max_options`; the report treats `censored` answers as rankings, not probabilities.

## 3. Profile schema

```yaml
id: fireworks/deepseek-v4p1-flash-1017-us
version: 1                      # bump on any change; part of the cache key
backend: logprob_chat
provider:
  base_url: https://us.api.fireworks.ai/inference/v1
  path: /chat/completions
  api_key_env: FIREWORKS_API_KEY
  model: accounts/fireworks/routers/deepseek-v4p1-flash-1017-us
request:
  temperature: 0
  max_tokens: 1
  logprobs: true
  top_logprobs: 5
  extra:                        # merged into the body as-is
    reasoning_effort: none      # mandatory; "minimal" and "low" still reason
limits:
  top_logprobs_max: 5
  calibrated_options: 5
  max_options: 30
  concurrency: 8                # no rate-limit headers exposed, so limit client-side
  timeout_s: 30
codes:
  scheme: auto                  # letters A..Z up to 26 options, else 01..30
  normalise: [strip_whitespace, strip_trailing_punct]
response:
  shape: openai_chat            # choices[0].logprobs.content[0].top_logprobs[{token, logprob}]
  answer_token_index: 0
  ignore_finish_reason: true    # it is "length" at max_tokens 1, which is fine
retry:
  on_status: [429, 500, 502, 503, 529]
  max_attempts: 3
  backoff: exponential_jitter
price:
  input_per_mtok_usd: null      # fill from the Fireworks pricing page; report measured ~$0.00007 per call
  cached_input_per_mtok_usd: null
tests:
  conformance_passed_at: null   # filled in by the probe
```

Other providers reuse the schema. For example, a local model behind an OpenAI-compatible server (Ollama, LiteLLM, vLLM) would change `provider`, `extra` (its own way of turning reasoning off) and `limits`, and could use `shape: openai_completions` if that is all it offers.

## 4. LogprobChatBackend algorithm

For each question, in parallel up to `limits.concurrency`:

1. **Options.** choice: criteria in the given order; score: levels 0..n-1; noul: [yes, no] from criteria or defaults.
2. **Guard.** If k > `max_options`, raise. The caller must shortlist first.
3. **Codes.** Assign codes per `codes.scheme`.
4. **Prompt.** Use the versioned template in section 5. State goes first so the prefix cache hits across questions on the same state.
5. **Call** with `request` + `extra`.
6. **Parse.** Take the top_logprobs of token `answer_token_index`. Normalise each token, and keep the best logprob per code. Drop tokens that aren't codes.
7. **Keep raw probabilities.** Each logprob is the model's real probability over the whole vocabulary, so the visible top codes need no renormalising. Compute `unseen_mass` from all visible tokens, including non-code ones such as `Let`. Codes not seen share at most `unseen_mass`, and each is at most the 5th-ranked probability. Set `censored` from `unseen_mass`.
8. **Off-list.** If no code was seen at all, return a uniform distribution with `off_list: true`.
9. **Normalise for display only.** Divide the visible codes' raw p by their sum to get `probabilities`, and map codes back to option keys. Keep the top 3 for the mapper.
10. **Derive** `value` and `confidence` (section 2).
11. **Reason** (optional, separate call): same state and question, `reasoning_effort: none`, `max_tokens: 60`, "In one sentence, why is <winner> the best answer?" Only for items the report will show.

Rules taken from the report, and enforced by the backend or the mapper:

- **Ask once with the full list.** Never re-ask a trimmed shortlist: the same candidate went from 0.998 to 0.44 (E15).
- **Dedupe near-identical options** before asking. Near-duplicates tie exactly (E12).
- **No permutation averaging.** There was no position bias (E6). Keep it as a profile option, off by default.
- **Don't map with yes/no.** "Is X the same as Y?" reads as strict identity (E5). Mapping uses choice; yes/no is fine for genuinely binary triage questions.
- **Stay on chat completions** for this profile. `/completions` tokenises differently and gives different numbers (E10).

## 5. Prompt template (v1)

```
system:
  You answer one multiple-choice question about the state below.
  Reply with only the code of the best option. No other text.

user:
  <state as pretty JSON, or the string>

  Question: <instructions>
  <code>: <option description>
  <code>: <option description>
  ...
```

The template has an id and version, and both go into the cache key. Changing wording means bumping the version and rerunning the answer key.

## 6. Cache, thresholds, telemetry

- **Cache key:** hash of (backend id, profile id, profile version, template version, state, question). Store per question, so changing one question re-asks only that one. Warm the cache before the demo and freeze it.
- **Thresholds** live per profile id and version, and per decision type. They apply to **p(winner)**, the winning option's raw probability, not to `confidence`. Entropy-based confidence falls as the option list grows even when the winner is clear; p(winner) means the same at 3 options or 30.

  ```yaml
  # config/thresholds.yml
  "fireworks/deepseek-v4p1-flash-1017-us@1":
    mapping:              # wrong accept = misleading diff, usually noticed
      auto_accept: 0.95
      needs_review: 0.50
    triage_intended:      # wrong accept = hidden regression, the worst failure
      auto_accept: 0.98
      needs_review: 0.50
    triage_regression:    # never auto-dismissed; always shown in the report
      auto_accept: null
  "jev:jev-1.13.0":       # tuned separately; don't copy Flash numbers
    mapping:           { auto_accept: null, needs_review: null }
    triage_intended:   { auto_accept: null, needs_review: null }
    triage_regression: { auto_accept: null }
  ```

  - `accepted` if p(winner) ≥ `auto_accept` and not censored
  - `review` if p(winner) ≥ `needs_review`, or censored
  - `unmapped` (mapping) or `unsure` (triage) otherwise
  - A regression label is always reported, whatever its probability; low p only adds an "unsure" marker.
- **Tuning.** Flash isn't calibrated: correct answers measured 0.995–0.999 on clean lists, 0.80–0.89 at 30 options, 0.53 on a near-duplicate. Ten answer-key items can't tune thresholds statistically, so start conservative and check that nothing wrong lands above `auto_accept` on the key run. Over time, thresholds are tuned on a team's own confirmed decisions (the ledger).
- **Score questions** stay at 5 levels or fewer on Flash, so every level is visible.
- **Telemetry** per call: latency, prompt tokens, cached tokens, completion tokens, cost. The report footer totals them: "47 decisions, 31 s, $0.004" is a good demo line.

## 7. Conformance probe (per profile)

A small script any new profile must pass before use. It records results into the profile's `tests` block. It is a cut-down `logprobs_test.py`:

| check | pass when |
|---|---|
| reachable | the call returns 200 (catches region 403s) |
| reasoning off | `reasoning_tokens` is 0, or absent, with the profile's `extra` |
| shape | logprobs found at the profile's `response.shape` path |
| codes | `A` and `01` come back as single tokens after normalisation |
| top_logprobs_max | the configured value is accepted, and one above it is rejected or capped |
| E4 answer | the brief's 5-option question gives p(A) > 0.95 |
| triage smoke | one seeded regression and one intended change, labelled correctly |

## 8. Other backends, briefly

- **JevBackend:** maps questions straight into `{state, questions}`, one call, and copies answers across. `censored` and `off_list` are always false. Use the versioned model id from the response as the profile version.
- **SampleVoteBackend:** same prompt, n = 8 to 16 calls at temperature 0.7, max_tokens 1, then count votes. For providers without logprobs, or when a full distribution over more than 5 options is needed. Marked `calibrated: false`.
- **FakeBackend:** looks up the answer key and returns one-hot answers. Used for tests and as the offline demo fallback.

## 9. Language decision

The layer is small in every language: one HTTP POST, a softmax and a cache. The choice is really about the whole app, which includes two toy services, an OpenAPI spec, a replayer, a differ and a report page.

| | Python (FastAPI) | Ruby (Sinatra/Roda or Rails) | TypeScript (Hono) |
|---|---|---|---|
| Working Fireworks code today | **yes**, `logprobs_test.py` | no, rewrite (small) | no, rewrite (small) |
| OpenAPI spec for the toy services | **generated by FastAPI**, per sub-app for /v1 and /v2 | hand-written, or rswag | hand-written, or zod-openapi |
| Typed contract | pydantic | Data / dry-types | zod or TS types |
| Jev at home | official SDK, plus `system-one-adapter` as a reference | raw HTTP (one POST) | official SDK, Vercel AI SDK `evaluate` |
| Free hosting | Render, Fly, Railway | Render, Fly | Vercel, Cloudflare Workers |
| Who can write it fast | ? | Gerdi | ? |

Recommendation: **Python with FastAPI**, unless Stevo or Temba would be much slower in it than in Ruby. The generated OpenAPI spec feeds pipeline step 1 directly, the Fireworks client is already proven, and TypeSafe's own Python tooling covers the Jev side at home. Ruby is the pick if speed in your own hands matters more, since you'd own most of the backend anyway.

Still to decide:

1. App language, which settles the adapter language too.
2. Framework, if not FastAPI.
3. Report page: server-rendered templates (simplest) or a small JS front end.
