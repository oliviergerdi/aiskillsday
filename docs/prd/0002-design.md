# PRD 0002 design: real-API readiness, round 1

Nov 26, 2026 · Gerdi + Claude · brainstorm output, **approved 15:59**

Implements part of `docs/prd/0002-real-api-readiness.md`. Where this doc and the PRD disagree, this doc wins.

## Intent

Make a real public API run (Petstore v2 → v3) **readable and scorable**, and make authenticated APIs possible. Proving ground: Petstore and Mastodon (no auth). Auth is built and unit-tested, not demonstrated live.

## Scope

| PRD req | This round | Decision |
|---|---|---|
| 1 Auth headers | **in** | `Name: env:VAR` per side, values read at run time, only names stored |
| 2 Default noise rules | **in** | Format-preserving: mask the value, keep the format |
| 3 List order | **in, extended** | Match list items by key, not by position |
| 7 Answer key | **in, replaced** | Score against PRD 0001 reviewer decisions at view time; no new file or command |
| 8 Safe mode | **kept** | GET only on servers you don't own, as today |
| 4 Noise probing, 5 bodies from schema, 6 pagination | **out** | Next round |

## Goals

1. Per-call timestamp and UUID differences stop showing up as findings, while a change of timestamp format, timezone, precision or type still does.
2. Lists of keyed objects compare item by item, with paths that stay stable across runs.
3. Every run shows how well the model agrees with the human decisions already made in its scope.
4. An authenticated service can be compared without a secret ever being written to a file.

## Non-goals

OAuth flows, literal header values in config, scoring noise on real runs, an answer-key export, request bodies, pagination, probing.

## Anti-goals

- Never mask blindly: a masked value keeps its format so contract changes still surface.
- Never hide membership changes: items present on only one side are findings, not noise.
- Never call agreement "accuracy": reviewers saw the model's label first.

## 1. Default noise rules: format-preserving

Applied to both sides in `normalise`, after the explicit `mask` rules and before diffing, to every string or number in the body:

| Value | Replaced with |
|---|---|
| ISO 8601 datetime | `<datetime tz=Z\|+02:00\|naive precision=s\|ms\|us>` |
| ISO 8601 date | `<date>` |
| UUID (8-4-4-4-12 hex) | `<uuid v4>` (version digit) |
| Integer 10⁹–10¹³ in a field named `*At`, `*_at`, `*Date`, `*_date`, `timestamp`, `created`, `updated` | `<epoch s\|ms>` |

- Equal raw values are left alone (no noise, nothing to explain).
- When raw values differ but the format tokens are equal, both sides get the token and a `Noise` record is added: `rule: "datetime (format kept)"` etc., path generic (`$.items[*].shipDate`).
- When the formats differ (UTC → +02:00, seconds → ms, timestamp → epoch, timestamp → null), only the matching side is tokenised, so the diff reports `changed` or `type_changed` with the format visible: `"<datetime tz=Z precision=s>" → "<datetime tz=+02:00 precision=s>"`. A real contract change, shown, triaged.
- Masking is per value, so a field that is a timestamp in some samples and not in others surfaces naturally; no special guard is needed.
- `config/noise.yaml` gains `defaults: {datetime: true, date: true, uuid: true, epoch: true}`; any can be set to `false`. Existing `mask` and `unordered` rules keep working and run first.

## 2. Lists: match items by key

**Stable key**: every item is an object, all have the same field from `id`, `uuid`, `key`, `code` (first that qualifies), and its values are unique within each side. `config/noise.yaml` `lists:` can name the key per endpoint and path, or set `key: null` to force positional compare. The toy `unordered` rule becomes a `lists` entry.

For a keyed list on both sides:

- Items with the same key are diffed field by field. Path segment `[id=10]`: `$.items[id=10].name`, `$[id=10].status`.
- Items only in old → **one** finding `items_removed` at the list path; items only in new → **one** finding `items_added`. The finding carries the keys (shown capped at 20). Grouped across samples like any finding.
- Same membership, different order → a `Noise` record `rule: "order (matched by id)"`, no finding.

Lists without a stable key: unchanged behaviour (positional; `list_length_changed` when lengths differ).

Code impact: new finding kinds `items_removed`, `items_added` (models, `diff`, triage `WHAT`, web `KIND_TEXT`). `jsonpath.value_at` and `generic` understand `[key=value]`. The toy answer key still matches: item 7 is now `items_removed` at `$.items` (keys 4, 5); it is still `GET /orders` + `$.items`, so scoring by `(endpoint, path)` is unaffected. Tests that assert `list_length_changed` for item 7 change to `items_removed`.

Ledger effect: list-item paths change from `[3]` to `[id=10]`, which is what makes PRD 0001 decisions survive reruns on real data. No list-item ledger entries are committed today, so nothing goes stale.

## 3. Reviewer agreement (replaces the answer-key template)

`nparity/review.py: agreement(run, ledger) -> Agreement`, computed at view time over findings that have a ledger decision in the run's scope:

| Human | Model | Counts as |
|---|---|---|
| accept | intended | agree |
| reject | regression | agree |
| accept | regression | **false regression** |
| reject | intended | **missed regression** (its own count, never folded into a percentage) |
| either | unsure | model unsure |

`Agreement`: `decided`, `agree`, `false_regressions`, `missed_regressions`, `model_unsure`, `undecided` (findings with no decision, not scored). Noise is not scored on real runs.

Shown on the run page score line and the sign-off page as **"Agreement with reviewers: 7/8 decided · 0 false regressions · 0 missed · 1 model unsure · 13 not yet reviewed"**, with the note "reviewers saw the model's label". When a run also has an answer key (toy), both lines show. The toy `fixtures/answer_key.yaml` stays as the fixed benchmark.

## 4. Auth headers

- `SourceInput.headers: list[str]`, each `Name: env:VAR` (regex-validated: header token name, `env:` prefix, upper-case variable). Literal values are rejected, so a secret cannot be saved in a configuration.
- Resolved at run start from the server environment. A missing or empty variable fails the run before any request, naming the variable (never the value).
- Applied to every request for that side: spec fetch, replay, retries.
- `Run.config` records `old_headers`/`new_headers` as header **names** only.
- Web form: a "Headers" textarea per side (one per line). CLI: repeatable `--old-header`/`--new-header`.
- README: run with the variable inline, as with the Fireworks key: `OLD_TOKEN="$(…)" uv run uvicorn …`.

## Testing

All key-free.

- Noise: datetime/date/uuid/epoch tokenising; equal values untouched; differing same-format values → noise record; UTC → +02:00 and timestamp → epoch → finding with formats visible; `defaults.datetime: false` disables.
- Lists: key detection (id, uuid; not when duplicated or missing on one item); matched-item diff path `$[id=10].name`; removed/added findings with keys; order-only → noise; non-keyed list unchanged; `lists` override and `key: null`.
- Toy pipeline still scores 10/10 (item 7 now `items_removed`); `value_at("$.items[id=4].status")`.
- Agreement table row by row; undecided not scored; page shows the agreement line.
- Headers: transport asserts the header on spec and replay requests; saved run and configuration contain no value; literal value rejected; missing variable error names the variable.
- Petstore: a captured-response test (no network) from `samples/api-versions/` shows `findByStatus` as one removed and one added finding plus key-matched differences, not positional field noise.

## Success

Rerun `petstore`: no index-based paths, no per-call timestamp noise, membership differences as two findings, and after a few decisions in the UI the page shows reviewer agreement. Compare the finding count with the 15:03 run (21 findings).

## Risks

- A token can collide with a real value that only looks like a timestamp. Every tokenised path is listed in noise; defaults can be switched off per kind.
- Key detection can pick a key that isn't the identity (e.g. `code` meaning a status code). First qualifying field in a fixed order, override in `lists:`.
- Agreement is anchored on the model's label. Labelled as agreement, not accuracy.
