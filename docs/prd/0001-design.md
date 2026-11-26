# PRD 0001 design: review ledger, saved configurations, rerun with baseline, sign-off

Nov 26, 2026 · Gerdi + Claude · brainstorm output, **approved 14:50**

Implements `docs/prd/0001-signoff-report-and-ledger.md`, extended with saved run configurations and a rerun menu (decided in brainstorm). Where this doc and the PRD disagree, this doc wins.

## Intent

Close the review loop. A human records a decision on each finding in the web UI, decisions carry over to later runs, a rerun shows what is new since last time, and the manager gets one sign-off page. Nothing in mapping, triage, prompts or thresholds changes, so the frozen 10/10 demo stays valid.

## Goals

1. Accept or reject any finding from the web UI, with name and note. Decisions persist across runs of the same configuration.
2. Save a run's settings as a named configuration; rerun it from a menu.
3. Every rerun is compared with a baseline run (latest of the same configuration by default, changeable before Start): new, unchanged, resolved.
4. A print-friendly sign-off page with a clear verdict.

## Non-goals

Auth or real identity (the name is typed), approval workflow, CI gating, Jira/Slack, wildcard ledger entries, the model ever accepting a regression on its own. CLI commands and Markdown export are stretch only.

## Anti-goals

- Never hide a finding: accepted items move to their own section, they do not disappear.
- No analysis in templates: ledger, baseline and verdict logic live in `nparity/`.

## Decisions (from brainstorm)

| Topic | Decision |
|---|---|
| Where decisions are made | Web UI primarily. CLI only if trivial |
| Unit of decision | One finding per ledger entry, plus "Accept all N on this endpoint" that writes one entry per finding |
| Decision values | **Accept** (difference is fine) and **Reject** (real bug, must be fixed). Click again to undo |
| Ledger scope | Per configuration. Runs without a configuration fall back to `old -> new` base URLs |
| Baseline | Chosen before Start: latest run of the same configuration by default, any earlier run of it, or none. Stored in the run. Can be changed again on the run page (view only) |
| Configurations | Saved from the run form as `comparisons/<name>.yaml`. The toy and Petstore presets become two committed configurations |
| Priority | 1 ledger + Accept/Reject, 2 configurations + rerun, 3 baseline, 4 sign-off are the demo line. 5 group action, 6 CLI/Markdown are stretch |

## Concepts

### Finding key

Run-local ids (`f-003`) shift between runs. Ledger and baseline use a stable key:

```
<endpoint> -> <new_endpoint or "-"> | <path> | <kind>
e.g.  GET /orders/{id} -> GET /orders/{id} | $.total | changed
```

`nparity/review.py: finding_key(f: Finding) -> str`. Exact match only. If key-relevant logic changes later (paths, kinds), old entries show as stale rather than silently matching.

### Scope

`scope_of(run) = run.config["config"]` when the run came from a configuration, else `"<old> -> <new>"`.

### Ledger: `accepted.yaml` (repo root, committed)

```yaml
entries:
  - scope: toy
    key: "GET /orders/{id} -> GET /orders/{id} | $.detail | changed"
    endpoint: GET /orders/{id}        # repeated for readability in diffs
    path: $.detail
    kind: changed
    decision: accept                  # accept | reject
    by: Temba
    at: 2026-11-26T15:02:11+02:00
    note: "Wording change agreed with support"
    run: 2026-11-26T150010-toy-1a2b3c4d5e6f
    model_label: unsure               # what the model said when the human decided
    model_p: 0.967
```

At most one entry per `(scope, key)`; recording again replaces it, undo deletes it. Writes go through one module-level lock (single process, prototype). Path is configurable (`app.state.ledger_path`) so tests use a tmp file.

### Review state (computed at view time, never stored in the run)

Decisions apply to any run in the same scope, including runs made before the decision.

| Model status | Ledger | Review state | Counts as open |
|---|---|---|---|
| shown (regression) | none | needs review | yes |
| unsure | none | needs review | yes |
| accepted (intended) | none | intended (model) | no |
| any | accept | accepted by reviewer | no |
| any | reject | confirmed regression | **yes** |

Plus run errors: each counts as open (rerun needed).

**Verdict:** "Ready to cut over" when open = 0, else "N open items: R confirmed regressions, U need review, E errors".

**Stale entries:** entries in the run's scope whose key matches no finding in the run. Listed on the sign-off page ("no longer seen").

### Configurations: `comparisons/<name>.yaml`

The existing `RunInput` minus nothing: `name`, `before`, `after`, `seeds`, `intent`, `backend`, `score`. No secrets (there are none in `RunInput`). Name pattern stays `[a-zA-Z0-9_-]+`, so it is a safe filename. Saving with an existing name overwrites (the folder is in git). Directory configurable (`app.state.comparisons_dir`).

Committed: `comparisons/toy.yaml` (`http://localhost:8000/v1` → `/v2`, fake, score on) and `comparisons/petstore.yaml` (as today's preset, flash, score off). The hard-coded presets in `new-run.js` are replaced by these.

A run started from a configuration records `config: <name>` and `baseline: <run id | null>` in `Run.config`.

### Baseline

`nparity/review.py: compare(run, baseline) -> Comparison` with `status: dict[key, "new" | "unchanged"]` and `resolved: list[Finding]` (in baseline, not in run). Auto choice: newest saved run with the same scope, excluding the new run. Computed at view time from the two saved run files.

## Web UI

### New run page (`/compare`)

- Top: **Rerun a configuration**: configuration dropdown (from `comparisons/`), a one-line settings summary, **Baseline** dropdown (default "Latest: <time>", then earlier runs of that configuration, then "None"), **Start**. Same console as today.
- "Edit in form" fills the full form from the configuration.
- Full form gains **Save as configuration** (checkbox, uses Name). Presets buttons now list configurations.
- New JSON endpoints, local-only like `/run-jobs`: `GET /comparisons`, `GET /comparisons/{name}` (settings + runs for the baseline dropdown). `POST /run-jobs` accepts `save_config: bool` and `baseline: "auto" | "" | <run id>`.

### Run page (`/runs/{id}`)

- Header line: "vs `<baseline time>` run: N new · M unchanged · K resolved" with a link, and a small dropdown to compare against another run of the same scope (`?baseline=<id>`, view only).
- Verdict line from review state (also satisfies part of UX-2).
- Sections: **Confirmed regressions** (rejected), **Regressions** and **Unsure** (needs review), **Intended (model)**, **Accepted by reviewer**, **Noise**, **Errors**, then **Resolved since baseline**.
- Each row: a `new` tag when new vs baseline. Expanded body: **Accept** / **Reject** buttons replace the dead Confirm/Override (UX-2 updated accordingly). Clicking opens an inline form: name (remembered in `localStorage`, try/catch), optional note, Save. HTMX posts and re-renders the page section. Decided rows show "Accepted by Temba, 15:02: note · model said unsure p=0.967" and an **Undo** button.
- Within Regressions and Unsure, findings are grouped by endpoint; each group with more than one finding has **Accept all N** (stretch, item 5). Minimal grouping only; UX-1 owns the rest of grouping.
- Write routes, local-only guard reused from `/run-jobs`:
  - `POST /runs/{id}/findings/{fid}/decision` form `decision, by, note`
  - `DELETE /runs/{id}/findings/{fid}/decision`
  - `POST /runs/{id}/groups/decision` form `endpoint, section, decision, by, note` (stretch)

### Sign-off page (`/runs/{id}/signoff`)

Print-friendly (`@media print`: no nav, no buttons). In order: verdict, configuration and old → new, run time, baseline summary; **Open items** (confirmed regressions first, then needs review) with endpoint, path, kind, model label, p, reason; **Accepted by reviewer** with who, when, note, model label and p at decision time; **Intended (model)** count and list; **Stale ledger entries**; **Errors**; score (if any); thresholds used; telemetry. Footer: "Names are typed, not authenticated (prototype)."

## Code layout

```
nparity/review.py        finding_key, scope_of, Ledger (load/save/record/remove/lookup/stale), review_state,
                         verdict, compare (baseline), latest_baseline
nparity/configs.py       save/load/list comparisons/*.yaml (RunInput moves here or is imported)
app/web/routes.py        new routes above; app.state.ledger_path, app.state.comparisons_dir
app/web/run_jobs.py      save_config + baseline; record config and baseline in Run.config
app/web/views.py         section building from review state (formatting only)
app/web/templates/       run.html, _row.html, _finding_body.html, new_run.html, signoff.html (new)
app/web/static/          new-run.js (configs instead of presets), review.js (name memory, forms)
comparisons/toy.yaml  comparisons/petstore.yaml
accepted.yaml            starts empty: `entries: []`
```

## Testing

All key-free, tmp ledger and comparisons dirs.

- `review.py`: key stability across two runs; scope with and without config; record replaces, undo removes; review-state table above row by row; verdict text; stale entries; compare new/unchanged/resolved; auto baseline picks newest same-scope run and never the run itself.
- Web: Accept on the toy `$.detail` unsure → ledger has one entry with model_label/p, run page shows it under Accepted and verdict drops by one; Reject on an intended → appears under Confirmed regressions; Undo; non-local request → 403; rerun of `toy` with auto baseline stores `baseline`, page shows "0 new"; `?baseline=` override; sign-off page contains verdict, open items, accepted-by line, thresholds; save configuration writes `comparisons/<name>.yaml`.
- E2E demo path: run toy (3 regressions + 1 unsure open) → accept the unsure, reject `$.total` → rerun with auto baseline → "0 new · 8 unchanged", verdict "3 open items: 1 confirmed regression, 2 need review".

## Demo flow (target)

1. Rerun `toy` from the menu (baseline: none) → 3 regressions, 1 unsure.
2. Accept the unsure error-wording change with a note; reject `$.total` as a real bug.
3. Rerun `toy` (baseline: auto) → "0 new · 8 unchanged", the accepted item under Accepted by reviewer, `$.total` under Confirmed regressions, verdict "3 open items: 1 confirmed regression, 2 need review".
4. Open the sign-off page: the one page for the manager.

## Risks

- **Demo run scope.** `runs/demo.yaml` predates configurations, so its scope is the URL pair, not `toy`. Re-freeze the demo from a `toy` configuration run once this lands.
- **Ledger hides too much.** Exact keys only, accepted items stay visible, rejects block the verdict.
- **Shared files with UX issues.** `run.html`/`_finding_body.html` are also targets of UX-1/UX-2. Note on both issues that PRD 0001 replaces the buttons and adds minimal grouping.
- **Time.** Items 1–4 are the demo line; 5–6 drop first.

## Left to the builder

Exact copy, CSS for new sections, dropdown labels.
