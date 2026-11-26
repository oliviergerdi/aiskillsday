"""nParity cost model. Run: python3 docs/costing/model.py
All token counts are MEASURED from cache/*.yaml (111 Flash calls, 26 Nov 2026).
All prices are LIST prices from public pages (see nparity-costing.md); anything marked ASSUMED is not verified.
"""
# --- measured (cache/*.yaml, Flash -us router) ---
CLS = dict(prompt=252, cached=37, completion=1)      # classify call, avg
RSN = dict(prompt=521, cached=163, completion=34.5)  # reason call, avg
FINDINGS_PER_ENDPOINT = 39 / 20                      # Petstore v2->v3, n=1 run
REASON_SHARE_HYBRID = 0.5                            # ASSUMED: reasons only for regression/unsure in hybrid designs

def llm_cost(c, p_in, p_cached, p_out):
    return ((c["prompt"] - c["cached"]) * p_in + c["cached"] * p_cached + c["completion"] * p_out) / 1e6

# --- engines: $/M tokens ---
FLASH_US   = dict(i=0.45, c=0.045, o=1.80)   # fireworks deepseek-v4p1-flash list. cached price ASSUMED = 10% of input
FLASH_1017 = dict(i=0.30, c=0.030, o=1.20)   # fireworks deepseek-v4p1-flash-1017 list. cached ASSUMED
NOVA2LITE  = dict(i=0.33, c=0.33,  o=2.75)   # ILLUSTRATIVE Bedrock model (aggregator page). Replace with the real Bedrock model
JEV        = dict(i=0.042)                   # output free
OPENAI_DEC = dict(i=0.10, c=0.01)            # output free
BEDROCK_VOTES = 10                           # ASSUMED n for SampleVoteBackend (spec: 8-16)

def per_finding():
    out = {}
    for name, p in (("Flash -us (today)", FLASH_US), ("Flash -1017", FLASH_1017)):
        out[name] = dict(verdict=llm_cost(CLS, p["i"], p["c"], p["o"]), reason=llm_cost(RSN, p["i"], p["c"], p["o"]), reason_share=1.0)
    n = NOVA2LITE
    out[f"Bedrock vote n={BEDROCK_VOTES} (illustrative model)"] = dict(
        verdict=BEDROCK_VOTES * llm_cost(CLS, n["i"], n["c"], n["o"]),
        reason=llm_cost(RSN, n["i"], n["c"], n["o"]), reason_share=1.0)
    flash_reason = llm_cost(RSN, **{"p_in": FLASH_US["i"], "p_cached": FLASH_US["c"], "p_out": FLASH_US["o"]})
    for name, p in (("Jev + Flash reasons", JEV), ("OpenAI Decisions + Flash reasons", OPENAI_DEC)):
        out[name] = dict(verdict=CLS["prompt"] * p["i"] / 1e6, reason=flash_reason, reason_share=REASON_SHARE_HYBRID)
    return out

# --- hosting: list prices us-east-1 (Fargate, ALB from AWS pages; NAT = Ohio price) ---
H = 730
def hosting(nat=False):
    fargate = (0.5 * 0.0405 + 1.0 * 0.0044) * H          # 0.5 vCPU / 1 GB x86, always on
    alb = 0.0225 * H + 0.008 * H                          # 1 ALB + ~1 LCU
    nat_gw = 0.045 * H if nat else 0.0
    other = 10.0                                          # ASSUMED: S3/DynamoDB, ECR, CloudWatch, Secrets Manager, Route53/ACM
    return dict(fargate=fargate, alb=alb, nat=nat_gw, other=other, total=fargate + alb + nat_gw + other)

if __name__ == "__main__":
    pf = per_finding()
    print("Per finding (verdict + reason), USD")
    for k, v in pf.items():
        tot = v["verdict"] + v["reason"] * v["reason_share"]
        print(f"  {k:46s} verdict {v['verdict']:.6f}  reason {v['reason']:.6f} x{v['reason_share']:.1f}  total {tot:.6f}")
    print("\nPer full run (cold, no cache), USD")
    for eps in (50, 200, 1000):
        for fpe in (FINDINGS_PER_ENDPOINT, 5):
            n = eps * fpe
            row = "  ".join(f"{k.split(' (')[0][:18]}={(v['verdict'] + v['reason'] * v['reason_share']) * n:.3f}" for k, v in pf.items())
            print(f"  {eps:5d} endpoints x {fpe:.1f} findings = {n:6.0f}:  {row}")
    print("\nHosting per month, USD (one always-on stack, us-east-1 list)")
    for nat in (False, True):
        print(" ", "with NAT" if nat else "no NAT  ", {k: round(v, 2) for k, v in hosting(nat).items()})
