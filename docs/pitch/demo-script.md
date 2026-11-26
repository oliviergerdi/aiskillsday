# nParity: demo script (Fri 27 Nov 2026)

Slot: 5 to 10 min plus about 2 min questions. Target **8:45**, which leaves a 75 s buffer. Main path is slides 1 to 12. Appendix (13 to 18) is for questions only.

| Time | Slides | Who | Beat |
|---|---|---|---|
| 0:00 | 1 to 2 | Stephen | Hook and value |
| 1:00 | 3 to 4 | Stephen | User, buyer, evidence |
| 2:15 | 5 | Gerdi | How it works |
| 3:00 | 6 | Stephen + Gerdi | **Live demo** (3:00) |
| 6:00 | 7 | Gerdi | Why trust it |
| 6:45 | 8 to 11 | Temba | Commercial case |
| 8:15 | 12 | Stephen | Close and ask |
| 8:45 | | | Questions |

## Script

**Slide 1 (Stephen, 0:15).** "Every engineer on an API migration asks one question: will we break anything? We are Team Chai-GPT, and nParity answers it."

**Slide 2 (Stephen, 0:45).** "From the first prototype to sign-off, nParity tells the engineer which differences between the old and new API are regressions, with a probability and a one-line reason. Today the check happens once, by hand, near the end, when a regression costs the most. Replay tools show what differs, not whether it was intended." *Pause after "not whether it was intended".*

**Slide 3 (Stephen, 0:30).** "Two people matter. The backend engineer who has to prove parity, and the manager who signs off the cutover and needs a short list with a probability on each item. What we are not: we do not do the migration. We find and rank the differences."

**Slide 4 (Stephen, 0:45).** "This pain is documented. GitHub's rewrite with Scientist was mostly noise, and took about five days even with a purpose-built tool. Twitter built Diffy because separating noise from regressions by hand is very hard. We also interviewed an engineer who moved from one version of a vendor API to its successor: same vendor, new process, endpoints that cannot be paired one to one. His trust came from references to the actual documentation."

**Slide 5 (Gerdi, 0:45).** "Five steps. Replay the same requests against both. Strain out noise with fixed rules, no model. Match endpoints and fields, rules first, the model only for leftovers. Compare every JSON path. Then taste: intended, regression or unsure, against your intent note. The model does only the two jobs that need judgement. Flow grouping is in progress and not in today's demo."

**Slide 6 (Stephen drives, Gerdi narrates, 3:00).**
1. (0:15) "Ten differences in, four for a human." Point at the 2 noise, 4 intended, 3 regressions, 1 unsure split.
2. (0:45) Run the **toy APIs**. Show the output.
3. (0:45) Open one regression: the rounding one, "10.005 now rounds to 10.00". "It never asks the model about rounding. The differ catches it, the model judges intent."
4. (0:30) Point at the rename found without being told: `/customers/{id}` to `/clients/{clientId}`.
5. (0:45) Run **Petstore v2 against v3**. "Two real public APIs. About 20 endpoints, 39 findings, roughly 20 seconds."

*Fallback if a live run fails:* say "this is the saved output from this morning", show the toy output already on screen, and move on. Do not debug live.

**Slide 7 (Gerdi, 0:45).** "Why trust it? Each verdict is read from the model's token probabilities, not a score it makes up. The costlier the mistake, the higher the bar: 0.95 to accept a match, 0.98 to accept a difference as intended. Regressions are never dismissed automatically. On our test APIs every run is scored against an answer key, and the score is on screen."

**Slide 8 (Temba, 0:30).** "The engineering manager pays. Self-host is free under MIT. Hosted is a Migration Pass, US$149 for 60 days. One migration's parity passes cost about US$3,800 of senior time, so that is about 4%. We charge once because a migration happens once. The true cost of a regression is unknown, so we price it as developer time: one caught early pays for the pass about three times."

**Slide 9 (Temba, 0:30).** "94% gross margin per pass. Model fees are 2% of the price. Support is the real cost. Hosting is serverless, about US$3 a month idle. Even if the model costs ten times more, margin is 74%."

**Slide 10 (Temba, 0:30).** "Honest view: one pass covers hosting, but the build only pays back with volume. At four passes a month a lean build pays back in month 52. At US$299 a pass, month 23. The free core is the funnel. No hockey stick."

**Slide 11 (Temba, 0:30).** "What if we are wrong? Accuracy: the unsure bucket and no automatic dismissal. No probabilities on the model route: run the CLI on any model that has them. Model price: cache or switch engine. Data: redact before any model call, self-host is free. One-off demand: test a higher price and use the CLI as the funnel."

**Slide 12 (Stephen, 0:30).** "Will we break anything? Know before it ships. The same engine runs before, during and after the migration, on whichever model your company has approved. Our ask: a pilot on one real migration, with two engineers, next quarter."

## If you run long (cut in this order)
1. Slide 4: drop the Twitter line (save 10 s).
2. Slide 9: say only "94% margin, model fees are 2%" (save 20 s).
3. Slide 11: name two risks, not five (save 15 s).
4. Slide 6: skip the Petstore run and say it is in the repo (save 45 s).

## Likely questions (use appendix slides)
- **Why trust the AI?** Slide 7. Probabilities, thresholds, no regression auto-dismissed.
- **How big is the market?** Not sized yet. Say so. Appendix 16 is a placeholder.
- **How do you know the 20 hours?** Illustrative (200 endpoints x 3 samples x 2 min). Timed baseline still to do (appendix 14).
- **Alternatives?** Appendix 15: Diffy archived, oasdiff spec-only, Speedscale and Keploy replay but do not judge intent.
- **What if there is no OpenAPI spec?** Optional by design: static mode from docs or samples, never labels "regression" (PRD 0006, in progress).
- **Authenticated APIs?** Not built for the demo, public APIs only. A token option is a release requirement, kept run-time only when hosted.
- **Data leaving the company?** Hosted tier redacts before any model call. Self-host keeps everything local.
- **Why not just use a model API directly?** Fixed rules do the numbers. The model only matches leftovers and judges intent, with a probability.

## Checks before you go on
- Toy APIs and Petstore both run once this morning. Save the output.
- Slides open at 1280x768 or larger, on the file in `docs/pitch/nparity-pitch.html` from `main`.
- Chips marked "in progress" and "TO FILL" on slides 5, 6 and 14: say "in progress" out loud, do not hide them.
- Slide 14 still has X hours and N differences placeholders. Keep it in the appendix.
