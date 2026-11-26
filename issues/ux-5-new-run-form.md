---
id: UX-5
type: Story
title: Make the intent note a first-class input on the new-run form
---

## Description

The pitch input is "two base URLs, two OpenAPI specs, one paragraph of intent". On the form (`app/web/templates/new_run.html`) the intent is a file-path text box hidden inside the collapsed "Run settings" section. Seeds are the same. A user who is not working in this repo cannot supply a file path to the server. Other gaps: "Fake (offline)" and "Flash (Fireworks)" are unexplained, "JSON manifest" is a developer-only source type, and an invalid name only shows as "Check the comparison inputs." in the console.

Changes:
- Replace the intent path input with a visible textarea labelled "What was this change meant to do?" with a short example. Keep an optional "or use a file" path field inside Run settings for the toy and Petstore presets.
- `app/web/routes.py` `RunInput` and `app/web/run_jobs.py`: accept `intent_text`. When present, write it to the run's own directory and use it as the intent file. The saved run records that the intent came from the form.
- Explain the evaluator choice in one line each: Fake answers from the answer key and is for testing; Flash calls the Fireworks model and needs `FIREWORKS_API_KEY`.
- Show field-level errors next to the field, and keep the console for run progress only.
- Presets fill the textarea with the toy and Petstore intent text.

## Acceptance Criteria

- Intent textarea is visible without opening Run settings.
- Submitting with pasted intent text produces a run whose triage used that text. Test with `FakeBackend`.
- Empty intent is allowed only if PRD 0004 is built. Until then the form requires intent text and says why.
- Validation errors name the field and show beside it.
- Existing preset buttons still start the toy and Petstore runs.
- `tests/test_web_runs.py` covers `intent_text` and a validation error.

## Notes

`intent_text` is written to disk under the run directory. Check `local_run_request` in `routes.py` still guards the endpoint, and cap the text length.
