# nParity: demo script (Fri 27 Nov 2026)

Slot: 5 to 10 min plus about 2 min questions. Target **7:00** including transitions. The slides carry the facts. This script only adds what the slide does not say: the story, the emphasis and the hand-offs. Do not read a slide aloud.

Judges score nine things (see the scoring sheet). Slide that carries each: problem clarity 2 to 4; opportunity and why now 5; success definition 6; problem-solution fit and working product 7 (the live demo); cost and unit economics 8; risk 9; value proposition 2 and 8; pitch and demo 1 to 10. Technical detail (how it works, trust, AI agents, scenarios) is in the appendix, slides 11 to 19, for questions.

| Time | Slide | Who | Add this (not on the slide) |
|---|---|---|---|
| 0:00 | 1 | Stephen | The story, then the slogan (0:15) |
| 0:15 | 2 | Stephen | "Intended or not" is the gap (0:20) |
| 0:35 | 3 | Stephen | Two people, and what we are not (0:15) |
| 0:50 | 4 | Stephen | The CSOM to Mesh story (0:30) |
| 1:20 | 5 | Stephen | Why a copy does not stop us (0:25) |
| 1:45 | 6 | Gerdi | One line on targets (0:15) |
| 2:00 | 7 | Stephen + Gerdi | **Live demo** (3:00) |
| 5:00 | 8 | Temba | Engineer savings, not a sale (0:30) |
| 5:30 | 9 | Temba | Two risks, named (0:20) |
| 5:50 | 10 | Stephen | The close (0:15) |
| 6:05 | | | Questions (about 55 s of spare in the 7:00) |

## Talking points

**Slide 1 (Stephen).** One engineer, one migration: "An engineer we interviewed moved an integration from one version of a vendor API to its successor. The endpoints did not line up, so he compared them by hand, hunting for errors." Then the slogan. We are Team Chai-GPT.

**Slide 2 (Stephen).** "Other tools tell you what differs. Nothing tells you whether it was meant to." *Pause there.*

**Slide 3 (Stephen).** "We find and rank the differences. We do not do the migration."

**Slide 4 (Stephen).** Tell the interview in one breath: new process, same vendor, no one-to-one pairing, and trust came from seeing the source. Say plainly: "That is one interview. We are not claiming more."

**Slide 5 (Stephen).** Moat, honestly: "The code is open and a copy is possible. What is hard to copy is judging intent with a probability, and the answer keys and thresholds we calibrate it against." Market: "We have not sized it. We count the labour saved instead."

**Slide 6 (Gerdi).** "These are the promises we test live. The safety rules cannot be changed: no regression is dismissed automatically."

**Slide 7 (Stephen drives, Gerdi narrates, 3:00).** Say in one line where the model sits: "The model does two jobs only, leftover matches and the verdict. Everything else is fixed rules."
1. (0:45) Run the **toy APIs**. "Ten differences in, four for a human."
2. (0:40) Open the rounding regression (10.005 now rounds to 10.00). "The differ catches the number. The model judges whether it was intended." Say why a difference needs 0.98 and a match 0.95: the costlier the mistake, the higher the bar.
3. (0:15) Point at the rename found without being told.
4. (0:30) Run the **toy flow** (`toy-flow`, fake backend). "One old call, six new ones, in order: token, configuration, start, callback, result, paged read. Each has a role and the spec sentence behind it. It suggests, it never replays."
5. (0:50) Run **Petstore v2 against v3**. "Two real public APIs. About 5 seconds, three findings. By hand we estimate two hours, which we have not timed." Open the unsure finding (`GET /pet/findByStatus`, `tags` changed from object to string) and say it is the unsure bucket doing its job: the intent note does not cover a type change, so it asks a human.

*Fallback if a live run fails:* say "this is the saved output from this morning", show the toy output already on screen, and move on. Do not debug live. Do not run the Wikipedia pair live unless the User-Agent fix is in.

**Slide 8 (Temba).** "This is an internal case. We are not selling it. The saving is engineer time: about 95 hours a migration on our assumptions, for about four dollars to run. The number to firm up is the manual baseline, which we have not timed."

**Slide 9 (Temba).** Name two risks only: accuracy (the unsure bucket), and the model route not returning probabilities (run the CLI on a model that does).

**Slide 10 (Stephen).** "Know what changed. Know what broke. Know before you build." Stop. Questions.

## If you run long (cut in this order)
1. Slide 9: name one risk (10 s).
2. Slide 7: skip the Petstore run and say it is in the repo (0:50).
3. Slide 5: drop the market line (10 s).

## Likely questions (appendix slides 11 to 19)
- **What is not built?** Appendix slide 19: PRDs 0003, 0004, 0006, 0007 and authorization tokens. Built: ledger and sign-off, headers and list matching, flow mapping, seed generation and coverage.
- **Why trust the AI?** Appendix slide 12. Probabilities, thresholds, no regression auto-dismissed.
- **Who has committed or paid?** No one yet. We have one interview and a working prototype. Say so.
- **What stops a copy?** See slide 5: judging intent with a probability, plus the calibration.
- **Will you sell it?** No. It is framed as an internal tool, because the numbers do not support an external sale. The value is engineer time (slide 8, scenarios on appendix slide 14).
- **How big is the market?** Not sized yet. Appendix slide 17 is a placeholder with the wrong slice.
- **How do you know the two hours?** An estimate (20 endpoints x 3 samples x 2 min), not yet timed. Appendix slide 16.
- **What if there is no OpenAPI spec?** Optional by design. Without one we do basic checks only, and the report says so (PRD 0006, PRD 0008).
- **Authenticated APIs?** Not built for the demo, public APIs only. A token option is a release requirement.
- **POST or DELETE endpoints?** The spec gives contract differences for every method with no calls. Behaviour is replayed for GET by default, other methods opt-in (PRD 0008).
- **Can an AI agent use it?** Appendix slide 13. Yes, a developer CLI with YAML run output. The agent options (`--format json`, `--compact`, `--detach`, `--dry-run`, `--fail-on`) are built; not in the demo. It is not meant for CI builds.
- **Data leaving the company?** Redaction before any model call is specified, not built. Run it on an approved model or locally and nothing leaves.
- **One old call that becomes several new ones?** Slide 7 shows it on the toy flow. Flow mapping (PRD 0005) is built: it suggests the new calls, in order, each with a role, a probability and the quoted spec sentence. It works from the specs only and never replays a flow. Shown on the toy flow pair with the fake backend. Real specs need the Flash backend, and scoring needs an engineer-confirmed key.
- **Did you test flow mapping on a real API?** Twice, on Petstore v2 to v3 with the Flash model (180 calls, about US$0.04 at list price, not billed). Petstore has no multi-step flows, so it only tests one-to-one matching. First run: 13 wrong `direct` labels with probabilities up to 0.999, and cycle warnings on 8 flows. After we tightened the rule (one `direct` per flow, same HTTP method, only ids create dependencies): 19 of 20 old operations got the right `direct`, no wrong `direct`, no cycles. The 20th, `POST /pet`, matched itself as `start` and was marked unsure. Some prerequisite steps (read, start) are still noise, and their probabilities are still high, so flows stay suggestions an engineer reviews. No accuracy claim.
- **CSOM to Mesh?** Our worked example. The key is our draft from vendor docs, how our integration calls each API, and one engineer's answer. It has not been reviewed.

## Checks before you go on
- Toy APIs and Petstore both run once this morning. Save the output.
- Deck: `docs/pitch/nparity-pitch.html`, 1280x768 or larger.
- Chips ("estimate" (slide 4), "not yet timed" (appendix) and "verify" (appendix)): say "in progress" out loud, do not hide them.
