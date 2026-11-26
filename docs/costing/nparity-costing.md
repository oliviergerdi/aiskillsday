# nParity: cost to run (v1, 26 Nov 2026)

**BLUF.** Model fees are not the cost driver: a 1,000-finding run costs about US$0.33 on Flash and about US$0.13 on Jev or OpenAI Decisions plus Flash reasons. People and support dominate. Always-on hosting is US$50 to 85 a month per stack, so we choose serverless (about US$3 idle, assumed). The decision that matters is not price per token. It is whether the engine returns a real probability and a reason. Bedrock serverless models do not return logprobs.

Reproduce: `python3 docs/costing/model.py`. Assumptions are marked ASSUMED. Nothing here is a quote.

## 1. Measured (111 cached Flash calls, `cache/*.yaml`)

| Call | Prompt tokens | Cached | Completion | Latency |
|---|---|---|---|---|
| Classify (1 token, logprobs) | 252 | 37 | 1 | 0.90 s |
| Reason (one line) | 521 | 163 | 34.5 | 0.76 s |

Petstore v2 to v3: 20 endpoints, 39 findings, 78 LLM calls, 20 s. Roughly 2 findings per endpoint (n = 1 run).

## 2. Findings that change the deck

| # | Finding | Evidence |
|---|---|---|
| 1 | Telemetry cost is an estimate, not a bill. `flash.yaml` prices are null, so each uncached call is charged a flat US$0.0000734. | Petstore run: telemetry US$0.0033. At list price from the same tokens: US$0.0083 (at $0.30/$1.20) to US$0.0125 (at $0.45/$1.80). |
| 2 | The router we use (`deepseek-v4p1-flash-1017-us`) has no public price. Two neighbours are listed: `-1017` at US$0.30 in / US$1.20 out, and `v4p1-flash` (-us) at US$0.45 / US$1.80 per M tokens. | Third-party price pages. **Check the Fireworks dashboard.** |
| 3 | Deck claim "about US$0.00007 per verdict" matches a classify call only at the cheaper, non-US price. At US$0.45/1.80 it is US$0.0001. A finding with a reason is about US$0.0003. | model.py |
| 4 | "Under US$0.01 per run" holds for the toy run (US$0.0010 to 0.0015) and fails for the live Petstore run at the -us price (US$0.0125). | runs/*.yaml |

## 3. Engine options, per finding (verdict + reason)

| Engine | Verdict | Reason | Per finding | 1,000-finding run | Real probability | Reason text |
|---|---|---|---|---|---|---|
| Flash on Fireworks, `-us` list | $0.000100 | $0.000231 | **$0.00033** | $0.33 | Yes, logprobs | Yes, 2nd call |
| Flash `-1017` list | $0.000067 | $0.000154 | $0.00022 | $0.22 | Yes | Yes |
| Bedrock, vote sampling, n = 10 (illustrative model: Nova 2 Lite, $0.33 / $2.75) | $0.000859 | $0.000267 | $0.00113 | $1.13 | **No.** Vote share, uncalibrated | Yes |
| Jev ($0.042 / M in, output free) + Flash reasons on 50% of findings (ASSUMED) | $0.000011 | $0.000231 | $0.00013 | $0.13 | Yes, returned | **No.** Needs Flash |
| OpenAI Decisions ($0.10 / M in, $0.01 cached, output free) + Flash reasons | $0.000025 | $0.000231 | $0.00014 | $0.14 | Returned; calibration not documented | **Not documented.** Needs Flash |

Notes:
- Jev and OpenAI bill input tokens only. Jev bills the state once per call and about 300 tokens of overhead per call. Batching all questions in one call is 12x cheaper than one call per question (Jev's own test). The Flash path cannot batch.
- Jev and OpenAI Decisions use a different request shape (`state` + `questions`), not OpenAI chat with logprobs. PRD 0003 says a new provider is "a profile file, no code". That holds only for chat + logprobs providers.
- Bedrock: logprobs exist only for Custom Model Import models (Llama, Mistral, Qwen imported after 31 Jul 2025). No evidence found for serverless Converse models. Which Bedrock model is "ours" is still open.

## 4. Hosting on AWS (one always-on stack, list prices)

| Item | US$/month | Basis |
|---|---|---|
| ECS Fargate 0.5 vCPU / 1 GB x86 | 18 | us-east-1, $0.0405/vCPU-h, $0.0044/GB-h |
| ALB + 1 LCU | 22 | $0.0225/h + $0.008/LCU-h |
| S3, DynamoDB, ECR, CloudWatch, Secrets Manager, Route 53 | 10 | ASSUMED |
| **Total, public subnets** | **50** | |
| NAT gateway (private subnets) | +33 | $0.045/h, Ohio price. Avoidable. |
| **Total with NAT** | **83** | |

Not priced: Africa (Cape Town) region (not on AWS pages we could read), data transfer, Bedrock in af-south-1, support, people. The product today is file based (`runs/`, `cache/`, `accepted.yaml`), has no auth and no tenancy. A hosted product needs storage and accounts first. PRD 0001 lists both as out of scope.

## 5. Sources

- Fireworks list prices: getmaxim.ai Bifrost cost calculator pages for `deepseek-v4p1-flash` and `deepseek-v4p1-flash-1017`.
- Jev: flaviocopes.com/jev-pricing (updated 9 Oct 2026), docs.aimlapi.com Jev page.
- OpenAI Decisions API: fourweekmba.com (GA 22 Oct 2026, $0.10 / $0.01 cached, no output fee). A second source (thenewstack.io) says limited preview, price undisclosed. **Confirm on OpenAI's own pricing page.**
- Bedrock logprobs: AWS ML blog, Custom Model Import.
- AWS: aws.amazon.com Fargate, ELB and VPC pricing pages.

## 6. Decisions (26 Nov 2026) and what they change

- **Two ways to run.** CLI with your own logprobs model (no hosting cost to us, no model cost to us). Hosted service on AWS for everyone else (PRD 0007). Revenue model for the CLI is open: **Open core: free to self-host, paid hosted tier.** The hosted price must cover the cost per run (section 3) plus hosting (section 4) and support. Licence: MIT.
- **Primary engine:** DeepSeek Flash, reached through Bedrock and served by Fireworks. Stated by the team, **not verified**: does the Bedrock route return `top_logprobs`, and what does it charge? Until checked, the Fireworks list prices above stand in. Run the conformance probe through the Bedrock route.
- **Data leaves AWS anyway.** The model host is Fireworks, so redaction (PRD 0007 #7) applies even though the call starts in AWS.
- **Currency:** USD.
- **Hosted tier adds, not yet priced:** database or object storage, a queue and worker, Secrets Manager, logs, and Cape Town region uplift if customers need South African data residency.

## 7. Serverless hosting and Migration Pass (26 Nov 2026)
- **Why:** a migration is used once or twice, so US$99 a month was too high and always-on containers (US$50 to 83) cost more than a few teams pay.
- **Hosting:** serverless (functions, object storage, key-value table, queue, auth). About **US$3 a month idle** (ASSUMED, not checked against AWS pages) plus about US$0.01 compute per large run. The model call is the same Bedrock/Fireworks route.
- **Price:** Migration Pass US$149, 60 days, about 50 runs. Optional Team plan US$99 a month.
- **Result:** gross margin 94%, contribution US$100 after 1 h support. Model price 10x still leaves 74%. Full model: `docs/business-case.md`, `docs/costing/business_case.py`.
