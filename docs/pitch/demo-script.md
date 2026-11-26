# nParity: demo script (Fri 27 Nov 2026)

Slot: 5 to 10 min plus about 2 min questions. Target **7:00** including transitions. The slides carry the facts. This script only adds what the slide does not say: the story, the emphasis and the hand-offs. Do not read a slide aloud.

Judges score nine things (see the scoring sheet). Slide that carries each: problem clarity 2 to 4; opportunity and why now 5; success definition 7; problem-solution fit and working product 8; cost 12; risk 13 to 14; value proposition 2 and 5; pitch 1 to 15; AI use 10.

| Time | Slide | Who | Add this (not on the slide) |
|---|---|---|---|
| 0:00 | 1 | Stephen | The story, then the slogan (0:15) |
| 0:15 | 2 | Stephen | "Intended or not" is the gap (0:20) |
| 0:35 | 3 | Stephen | Two people, and what we are not (0:15) |
| 0:50 | 4 | Stephen | The CSOM to Mesh story (0:30) |
| 1:20 | 5 | Stephen | Why a copy does not stop us (0:25) |
| 1:45 | 6 | Gerdi | Where the model sits (0:20) |
| 2:05 | 7 | Gerdi | One line on targets (0:15) |
| 2:20 | 8 | Stephen + Gerdi | **Live demo** (2:00) |
| 4:20 | 9 | Gerdi | Why the thresholds differ (0:15) |
| 4:35 | 10 | Gerdi | One sentence (0:10) |
| 4:45 | 11 | Temba | Why a hosted tier exists (0:25) |
| 5:10 | 12 | Temba | The one number to remember (0:15) |
| 5:25 | 13 | Temba | The honest read (0:20) |
| 5:45 | 14 | Temba | Two risks, named (0:15) |
| 6:00 | 15 | Stephen | The close (0:15) |
| 6:15 | | | Questions (about 45 s of spare in the 7:00) |

## Talking points

**Slide 1 (Stephen).** One engineer, one migration: "An engineer we interviewed moved an integration from one version of a vendor API to its successor. The endpoints did not line up, so he compared them by hand, hunting for errors." Then the slogan. We are Team Chai-GPT.

**Slide 2 (Stephen).** "Other tools tell you what differs. Nothing tells you whether it was meant to." *Pause there.*

**Slide 3 (Stephen).** "We find and rank the differences. We do not do the migration."

**Slide 4 (Stephen).** Tell the interview in one breath: new process, same vendor, no one-to-one pairing, and trust came from seeing the source. Say plainly: "That is one interview. We are not claiming more."

**Slide 5 (Stephen).** Moat, honestly: "The code is open and a copy is possible. What is hard to copy is judging intent with a probability, and the answer keys and thresholds we calibrate it against." Market: "We have not sized it. We count the labour saved instead."

**Slide 6 (Gerdi).** "The model does two jobs only: leftover matches and the verdict. Everything else is fixed rules." Flow grouping is in progress and not in the demo.

**Slide 7 (Gerdi).** "These are the promises we test live. The safety rules cannot be changed: no regression is dismissed automatically."

**Slide 8 (Stephen drives, Gerdi narrates, 2:00).**
1. (0:35) Run the **toy APIs**. "Ten differences in, four for a human."
2. (0:30) Open the rounding regression (10.005 now rounds to 10.00). "The differ catches the number. The model judges whether it was intended."
3. (0:15) Point at the rename found without being told.
4. (0:40) Run **Petstore v2 against v3**. "Two real public APIs. About 20 seconds. By hand we estimate two hours, which we have not timed."

*Fallback if a live run fails:* say "this is the saved output from this morning", show the toy output already on screen, and move on. Do not debug live. Do not run the Wikipedia pair live unless the User-Agent fix is in.

**Slide 9 (Gerdi).** "The costlier the mistake, the higher the bar. That is why a difference needs 0.98 and a match needs 0.95."

**Slide 10 (Gerdi).** "It is a developer tool, and an AI agent can drive it too. In progress, not in the demo."

**Slide 11 (Temba).** Why hosted exists: "Self-host is free for anyone who can run a model with token probabilities. The hosted pass is for teams who cannot, or would rather not. We charge once because a migration happens once."

**Slide 12 (Temba).** "Model fees are 2% of the price. Support is the real cost."

**Slide 13 (Temba).** "The honest read: the hosted tier is modest on its own. The free core builds the audience, and the pass pays for itself."

**Slide 14 (Temba).** Name two risks only: accuracy (the unsure bucket), and the model route not returning probabilities (run the CLI on a model that does).

**Slide 15 (Stephen).** "Know what changed. Know what broke. Know before you build." Stop. Questions.

## If you run long (cut in this order)
1. Slide 10: skip it (10 s).
2. Slide 14: name one risk (10 s).
3. Slide 8: skip the Petstore run and say it is in the repo (40 s).

## Likely questions (appendix slides 16 to 19)
- **Why trust the AI?** Slide 9. Probabilities, thresholds, no regression auto-dismissed.
- **Who has committed or paid?** No one yet. We have one interview and a working prototype. Say so.
- **What stops a copy?** See slide 5: judging intent with a probability, plus the calibration.
- **Why pay when the CLI is free?** The hosted tier is for people who cannot or will not run a model themselves.
- **How big is the market?** Not sized yet. Slide 18 is a placeholder with the wrong slice.
- **How do you know the two hours?** An estimate (20 endpoints x 3 samples x 2 min), not yet timed. Slide 17.
- **What if there is no OpenAPI spec?** Optional by design. Without one we do basic checks only, and the report says so (PRD 0006, PRD 0008).
- **Authenticated APIs?** Not built for the demo, public APIs only. A token option is a release requirement.
- **POST or DELETE endpoints?** The spec gives contract differences for every method with no calls. Behaviour is replayed for GET by default, other methods opt-in (PRD 0008).
- **Can an AI agent use it?** Yes, a developer CLI with YAML run output. The agent options (`--format json`, `--compact`, `--detach`, `--dry-run`, `--fail-on`) are in progress and not in the demo. It is not meant for CI builds.
- **Data leaving the company?** Hosted tier redacts before any model call (specified, not built). Self-host keeps everything local.
- **CSOM to Mesh?** Our worked example. The key is our draft from vendor docs, how our integration calls each API, and one engineer's answer. It has not been reviewed.

## Checks before you go on
- Toy APIs and Petstore both run once this morning. Save the output.
- Deck: `docs/pitch/nparity-pitch.html`, 1280x768 or larger.
- Chips ("in progress", "verify price", "to test", "not yet timed"): say "in progress" out loud, do not hide them.
