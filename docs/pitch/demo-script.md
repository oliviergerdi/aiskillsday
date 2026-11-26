# nParity: demo script (Fri 27 Nov 2026)

Slot: 5 to 10 min plus about 2 min questions. Target **9:40**, which leaves only about 20 s spare. Rehearse the cuts below. Main path is slides 1 to 15. Appendix (16 to 19) is for questions only.

Judges score nine things (see the scoring sheet). The slide that carries each one: problem clarity 2 to 4; opportunity and why now 5; success definition 7; problem-solution fit and working product 8; cost 12; risk 13 to 14; value proposition 2 and 5; pitch 1 to 15; AI use 10.

| Time | Slides | Who | Beat |
|---|---|---|---|
| 0:00 | 1 to 2 | Stephen | Hook and value |
| 0:50 | 3 to 4 | Stephen | User, buyer, evidence |
| 1:55 | 5 | Stephen | Alternatives and why now |
| 2:30 | 6 | Gerdi | How it works |
| 3:10 | 7 | Gerdi | Success and scope |
| 3:35 | 8 | Stephen + Gerdi | **Live demo** (2:45) |
| 6:20 | 9 | Gerdi | Why trust it |
| 6:45 | 10 | Gerdi | AI agents |
| 7:05 | 11 to 14 | Temba | Commercial case |
| 9:10 | 15 | Stephen | Close and ask |
| 9:40 | | | Questions |

## Script

**Slide 1 (Stephen, 0:15).** "Every engineer on an API migration asks one question: will we break anything? We are Team Chai-GPT, and nParity's answer is: know what changed, know what broke."

**Slide 2 (Stephen, 0:35).** "From the first prototype to sign-off, nParity tells the engineer which differences between the old and new API are regressions, with a probability and a one-line reason. Today the check happens once, by hand, near the end. Replay tools show what differs, not whether it was intended." *Pause after "not whether it was intended".*

**Slide 3 (Stephen, 0:25).** "Two people matter: the engineer who has to prove parity, and the manager who signs off the cutover and needs a short list with a probability on each item. We do not do the migration. We find and rank the differences."

**Slide 4 (Stephen, 0:40).** "The pain is documented. GitHub's rewrite with Scientist was mostly noise and took about five days even with a purpose-built tool. We also interviewed an engineer who moved from one version of a vendor API to its successor: new process, endpoints that cannot be paired one to one. His trust came from references to the actual documentation. We have one interview so far, and we say so."

**Slide 5 (Stephen, 0:35).** "Alternatives: hand-built harnesses, Diffy, Scientist, replay tools like Speedscale and Keploy. Some remove noise, some replay. None matches renames, and none judges whether a difference was intended. Diffy now sits in Twitter's archive. Why now: a small model can return a probability per verdict for a fraction of a cent. We have not sized the market, so we count the labour: about US$3,800 of senior time per migration."

**Slide 6 (Gerdi, 0:40).** "Five steps. Replay the same requests against both. Strain out noise with fixed rules, no model. Match endpoints and fields, rules first, the model only for leftovers. Compare every JSON path. Then taste: intended, regression or unsure, against your intent note. Flow grouping is in progress and not in today's demo."

**Slide 7 (Gerdi, 0:25).** "What success means: 10 of 10 differences correct against the answer key, no regression dismissed automatically, no false regressions, four or fewer items for a human, under a minute, under a cent in model fees. Targets are configurable per run, the safety rules are not. Out of scope: doing the migration itself."

**Slide 8 (Stephen drives, Gerdi narrates, 2:45).**
1. (0:15) "Ten differences in, four for a human." Point at the noise, intended, regression and unsure split.
2. (0:40) Run the **toy APIs**. Show the output.
3. (0:40) Open one regression: the rounding one, "10.005 now rounds to 10.00". "The differ catches the number, the model judges intent."
4. (0:20) Point at the rename found without being told: `/customers/{id}` to `/clients/{clientId}`.
5. (0:50) Run **Petstore v2 against v3**. "Two real public APIs, 20 endpoints, 39 differences, about 20 seconds. By hand we estimate about two hours."

*Fallback if a live run fails:* say "this is the saved output from this morning", show the toy output already on screen, and move on. Do not debug live. Do not run the Wikipedia pair live unless the User-Agent fix is in.

**Slide 9 (Gerdi, 0:25).** "Why trust it? Each verdict comes from the model's token probabilities. The costlier the mistake, the higher the bar: 0.95 to accept a match, 0.98 to accept a difference as intended. Regressions are never dismissed automatically."

**Slide 10 (Gerdi, 0:20).** "It is a developer tool, and it is built so an AI agent can use it too: JSON output, small answers, long runs you can poll, and a dry run. The agent does the fixing; nParity says where to look. This part is in progress and not in today's demo."

**Slide 11 (Temba, 0:40).** "The engineering manager pays. Self-host is free under MIT: a developer tool you run yourself, with your own model. Hosted is a Migration Pass, US$149 for 60 days, about 4% of the US$3,800 of labour a migration's parity passes cost. We charge once because a migration happens once. The true cost of a regression is unknown, so we price it as developer time: one caught early pays for the pass about three times."

**Slide 12 (Temba, 0:30).** "94% gross margin per pass. Model fees are 2% of the price. Support is the real cost. Serverless hosting is about US$3 a month idle. Model price ten times higher still leaves 74%."

**Slide 13 (Temba, 0:30).** "Honest view: one pass covers hosting, but the build only pays back with volume. Four passes a month: a lean build pays back in month 52. At US$299 a pass, month 23. The free core is the funnel."

**Slide 14 (Temba, 0:25).** "What if we are wrong? Accuracy: the unsure bucket and no automatic dismissal. No probabilities on the model route: run the CLI on any model that has them. Model price: cache or switch engine. Data: redact before any model call. One-off demand: test a higher price."

**Slide 15 (Stephen, 0:30).** "Know what changed. Know what broke. Know before you build. The same engine runs before, during and after the migration, on whichever model your company has approved. Our ask: a pilot on one real migration, with two engineers, next quarter."

## If you run long (cut in this order)
0. Slide 10: drop it to one sentence, or skip it (20 s).
1. Slide 5: drop the Diffy archive line (10 s).
2. Slide 11: say only "94% margin, model fees are 2%" (15 s).
3. Slide 13: name two risks, not five (15 s).
4. Slide 8: skip the Petstore run and say it is in the repo (50 s).

## Likely questions (appendix slides 16 to 19)
- **Why trust the AI?** Slide 9. Probabilities, thresholds, no regression auto-dismissed.
- **How big is the market?** Not sized yet. Slide 18 is a placeholder with the wrong slice. Say so.
- **How do you know the two hours?** An estimate (20 endpoints x 3 samples x 2 min), not yet timed. Slide 17.
- **What if there is no OpenAPI spec?** Optional by design: basic checks only, with a banner saying so (PRD 0006, PRD 0008, in progress).
- **Authenticated APIs?** Not built for the demo, public APIs only. A token option is a release requirement, run-time only when hosted.
- **Seeds, and POST or DELETE endpoints?** The spec gives contract differences for every method with no calls. Behaviour is replayed for GET by default, other methods opt-in (PRD 0008).
- **Can an AI agent use it?** Yes, it is a developer CLI and run output is YAML, so a coding agent can run it and read the result. The agent options (`--format json`, `--compact`, `--detach`, `--dry-run`) are in progress and not in the demo. It is not meant for CI builds.
- **Data leaving the company?** Hosted tier redacts before any model call. Self-host keeps everything local.
- **CSOM to Mesh?** Our worked example. The key is our draft from vendor docs, how our integration calls each API, and one engineer's answer. It has not been reviewed.

## Checks before you go on
- Toy APIs and Petstore both run once this morning. Save the output.
- Deck: `docs/pitch/nparity-pitch.html` from `main`, 1280x768 or larger.
- Chips ("in progress", "verify price", "to test", "not yet timed"): say "in progress" out loud, do not hide them.
