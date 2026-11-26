# PRD 0003: Trust evidence and model portability

**Status:** Draft · **Priority:** P1 · **Pitch promise:** "Every verdict shows how sure it is", "scored on every run", "on whichever model your company has approved", "references to the actual documentation would add confidence" (interview)

## Problem

1. **Verdicts cite no source.** `nparity/triage.py` asks for a one-line reason. The interview said trust comes from showing the source behind each verdict. Today the reader cannot see which sentence of the intent note, or which spec text, drove the label.
2. **One model, hard-wired.** `evaluator/base.py` `build()` accepts `fake` or `flash` only, and `config/profiles/` holds one profile. The pitch closes on "whichever model your company has approved". Providers without logprobs have no path: `SampleVoteBackend` is specified in `docs/nparity-evaluator-spec.md` but not built.
3. **Thresholds are uncalibrated.** `config/thresholds.yaml` values (0.95, 0.98, 0.999) were set against a 10-item key on one model. The pitch presents them as the answer to "why trust the AI?".
4. **Cost claim is an estimate.** `flash.yaml` prices are null and the run uses a measured per-call figure. The pitch states about US$0.00007 per verdict and under US$0.01 per toy run.

## Goals

1. Each verdict shows the intent-note sentence and the spec description it relied on.
2. A new provider is added with a profile file, no code, when it supports logprobs. Providers without logprobs work through vote sampling and are marked uncalibrated.
3. A calibration command reports, per model, how often each probability band was right.
4. Cost in the telemetry footer comes from real token counts and filled prices.

## Requirements

| # | Requirement | Acceptance |
|---|---|---|
| 1 | Triage returns the cited intent sentence (quoted from the note) with the reason. The UI shows it next to the p value. A citation not found verbatim in the note is dropped and flagged | Unit test with `FakeBackend`; test that a made-up quote is rejected |
| 2 | Spec evidence: when a finding is a declared-type or rename finding, show the old and new OpenAPI description or schema fragment in the finding body | Page test |
| 3 | `--backend` accepts any profile name found in `config/profiles/`. Unknown name lists the available ones | CLI test |
| 4 | Second profile for a different logprobs provider, as proof that the profile format is general | Live-marked test, skipped without key |
| 5 | `SampleVoteBackend`: n completions at temperature above 0, vote share as p, `calibrated: false` shown in the UI and report. Thresholds for uncalibrated backends are stricter and set in `thresholds.yaml` | Unit test with a fake transport; UI shows the flag |
| 6 | `nparity calibrate --backend X --key FILE`: runs triage on a labelled set and writes reliability per band (for example 0.9 to 0.95: n, correct). Output feeds threshold choice | Test on `FakeBackend` returns a deterministic table |
| 7 | Labelled set larger than 10. Add the Petstore findings and at least 30 toy-style variations (reworded intent, reordered fields) so thresholds are not tuned on the demo key | Set committed under `fixtures/calibration/` |
| 8 | Fill `price:` in profiles and compute `cost_usd` from tokens. Remove the estimate fallback once prices exist | Telemetry test |

## Out of scope

Fine-tuning, a hosted model, judging numbers or pagination with the model (stays deterministic).

## Risks

- A cited quote can still be a plausible-sounding wrong match. The quote check proves the text exists, not that it applies. State this in the UI copy.
- Calibration on a small set misleads. Report the sample size beside every band.
- Vote sampling costs n times a logprob call. Keep it the fallback.

## Success

Switching provider changes one flag and one profile file. Every non-noise verdict shows a quote and a probability. A calibration table exists for each supported model and the thresholds in `thresholds.yaml` cite it.
