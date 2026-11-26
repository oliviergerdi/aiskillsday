# nParity: business case (stage 3, 26 Nov 2026)

**BLUF.** Open core. Self-hosting is free (MIT) with your own model. Hosted pricing is a **Migration Pass at US$149**: 60 days, about 50 runs, one migration. That is about 4% of the senior-developer time one migration's parity passes cost. Gross margin is 94% and contribution 67% after support. Serverless hosting costs about US$3 a month idle, so the first pass covers run costs. Paying back the build needs volume: at 4 passes a month a lean build (US$19k) pays back in month 52 and a full build (US$58k) not within 10 years. At US$299 a pass the base case pays back a lean build in month 23. We moved from US$99 a month because a migration happens once or twice, so a subscription is the wrong shape. All figures USD. Reproduce with `python3 docs/costing/business_case.py`. Everything marked ASSUMED is a guess to challenge.

## 1. Pricing and revenue model
- **Who pays:** the engineering manager who signs off the cutover, from the team's tooling budget. The engineer is the user.
- **How:** open core. CLI and engine free under MIT, bring your own model with token probabilities. Hosted: **Migration Pass, US$149 per migration**, 60 days, about 50 runs fair use. Optional **Team plan, US$99 a month** for teams with ongoing API work (not in the base numbers).
- **Why that price (linked to value):**
  - A manual parity pass is about 20 h (illustrative: 200 endpoints x 3 samples x 2 min). With nParity about 1 h (ASSUMED). Five passes per migration (ASSUMED) at US$40/h loaded senior cost (ASSUMED) saves **US$3,800**.
  - US$149 is **about 4%** of that saving.
  - Cost of one regression is **unknown**: the developer must find it, find the fix and apply it. Priced as developer time, 4 h / 12 h / 24 h (ASSUMED) = US$160 / US$480 / US$960. One regression caught early at 12 h pays for the pass about three times.
  - The saving counts labour only. Incident and customer impact are not counted.

## 2. Cost and unit economics (per Migration Pass)
| Line | US$ | Basis |
|---|---|---|
| Price | 149.00 | |
| Model fees | 3.30 | 10 runs x 1,000 findings x US$0.00033 (tokens measured, list price). 10 runs is ASSUMED |
| Infra and payment | 5.57 | compute US$0.01 a run, storage US$1 (ASSUMED), 3% fee (ASSUMED) |
| **Gross margin** | **140.13 (94%)** | |
| Support | 40.00 | 1 h at US$40/h (ASSUMED) |
| **Contribution** | **100.13 (67%)** | |

- **Fixed run cost:** about **US$3 a month idle** on serverless (object storage, key-value table, logs, DNS; Lambda and auth in free tier). ASSUMED, not checked against AWS pages. Always-on containers cost US$50 to US$83 a month, so we avoid them. Cape Town prices not checked.
- **Build:** US$19,200 (1 engineer, 3 months) to US$57,600 (3 engineers, 3 months), ASSUMED, to take PRDs 0005 to 0007 to a paid product.
- **Support** is the largest variable cost, not the model.

## 3. Business case and assumptions
Passes a month are constant (no ramp). Sales start in month 4. Each pass is a one-off sale. No renewals or Team-plan revenue counted.

| Case | Passes / month | Monthly revenue | Payback, lean build | Payback, full build |
|---|---|---|---|---|
| Pessimistic | 2 | US$298 | month 101 | not in 10 years |
| Base | 4 | US$596 | month 52 | not in 10 years |
| Optimistic | 8 | US$1,192 | month 28 | month 76 |

- Break-even on run costs (idle hosting plus support): the first pass (US$100 contribution against US$3 a month).
- At US$299 a pass: lean build pays back in month 43 / 23 / 13 (pessimistic / base / optimistic).
- Read: the hosted tier is a modest business by itself. The open-source core is the funnel and the product is the engine. Real usage tells us the volume.

## 4. Risk and sensitivity
| Risk | If it happens | Answer |
|---|---|---|
| Accuracy too low | Engineers stop trusting it | Unsure bucket, no regression dismissed automatically, source on every verdict, targets configurable per run |
| No token probabilities on the model route | Vote sampling, uncalibrated, model cost 3.4x, margin about 89%, contribution US$92 | CLI on any model with probabilities. Label votes uncalibrated |
| Model price 10x higher | Margin 74%, contribution US$70 | Cache repeat questions, switch engine (Jev or OpenAI Decisions about 2.5x cheaper per finding), raise price |
| Customer data leaves AWS for the model host | Hosted tier refused by regulated customers | Redaction before any model call (PRD 0007 #7). Self-host is free |
| Demand is one-off | Each pass is a single sale, payback slips | Test US$299, lean build, CLI as funnel, optional Team plan |
| Free alternatives | No willingness to pay | Diffy is archived, oasdiff is spec-only. None pairs flows or judges intent |

## Not yet known
- Real cost of a regression (needs interviews). Real model price on the Bedrock route. Passes a month. Runs used per pass. Serverless idle cost and Cape Town prices. Support load.
