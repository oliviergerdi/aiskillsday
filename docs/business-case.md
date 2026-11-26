# nParity: business case (stage 3, 26 Nov 2026)

**BLUF.** Frame nParity as an internal tool and make the case on engineer time. One migration's parity passes cost about 100 senior hours by hand (5 passes x 20 h, illustrative) and about 5 h with nParity (ASSUMED): **95 h, about US$3,800** at US$40/h loaded. Running it costs about **US$4.40** a migration (model US$3.30, compute and storage US$1.10), 0.1% of the saving. Repaying a lean build (US$19k) takes 18 / 6 / 2 migrations (cautious / base / optimistic). The number to firm up is the manual baseline, which is untimed. The external sale below (Migration Pass, US$149) does not hold up: payback needs volume we cannot show, so it is kept only as a reference. All figures USD. Reproduce with `python3 docs/costing/business_case.py`. Everything marked ASSUMED is a guess to challenge.

## Internal case (current framing)
| Case | Manual pass | Passes | Saved per migration | Migrations to repay lean build |
|---|---|---|---|---|
| Cautious | 10 h | 3 | US$1,080 | 18 |
| Base | 20 h | 5 | US$3,800 | 6 |
| Optimistic | 40 h | 8 | US$12,480 | 2 |

- Saved = (manual hours - 1 h) x passes x US$40. Labour only: incidents, customer impact and a regression caught early (4 / 12 / 24 h, US$160 / 480 / 960) are not counted.
- The prototype and CLI work without the build. The lean build (PRDs 0005 to 0007) is an upper bound for internal use; PRD 0007 (hosted service) is needed only if the tool is offered outside the company.
- Cost to run: no licences or per-seat fee (MIT); model US$3.30 and compute and storage US$1.10 a migration; about US$3 a month idle if hosted internally. At one migration a month that is about US$8 a month.
- Time to repay (ASSUMED one migration a quarter, not measured): base case 6 migrations is about 18 months.
- Risks: low adoption (no sign-up, start with one migration team, manual checks remain the fallback); model price 10x = US$33 a migration; vote sampling about US$11; client data reaching a model host (use an approved model, redaction specified not built); manual baseline untimed.

# Reference: external sale (not recommended)

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
