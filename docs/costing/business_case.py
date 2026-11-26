"""nParity business case (v2: Migration Pass on serverless hosting; the monthly team plan is the older model below). Run: python3 docs/costing/business_case.py
MEASURED: tokens per call (cache/*.yaml). LIST PRICE: model and AWS prices (see nparity-costing.md).
Everything marked ASSUMED is a guess to be challenged. USD.
"""
RATE = 40.0            # ASSUMED: loaded cost of an average senior developer, US$/hour
PASS_H = 20.0          # ILLUSTRATIVE: manual parity pass, 200 endpoints x 3 samples x 2 min (problem-definition.md)
PASS_H_TOOL = 1.0      # ASSUMED: reading ~4 items plus setup with nParity
PASSES = 5             # ASSUMED: parity passes per migration
REG_H = {"low": 4, "base": 12, "high": 24}   # ASSUMED: find + diagnose + fix + redeploy one regression, hours (unknown, see note)
PRICE = 99.0           # US$/team/month hosted
LIFE = 3               # ASSUMED: months a team keeps the subscription for one migration
RUNS, FINDINGS, PER_FINDING = 20, 1000, 0.00033   # ASSUMED runs/month, 1,000-finding runs (cold), Flash -us list price
INFRA_PER_TEAM = 2.0   # ASSUMED: storage, logs
PAY_FEE = 0.03         # ASSUMED payment fee
SUPPORT_H = 0.5        # ASSUMED support hours per team-month
FIXED = 83.0           # AWS stack with NAT, per month (nparity-costing.md)
BUILD = 3 * 3 * 160 * RATE   # ASSUMED: 3 engineers x 3 months to take PRDs 0005-0007 to a paid product

def value():
    saved = PASSES * (PASS_H - PASS_H_TOOL) * RATE
    return dict(saved_per_migration=saved, price_per_migration=PRICE * LIFE, price_share=PRICE * LIFE / saved,
                regression={k: h * RATE for k, h in REG_H.items()})

def unit():
    model = RUNS * FINDINGS * PER_FINDING
    cogs = model + INFRA_PER_TEAM + PRICE * PAY_FEE
    support = SUPPORT_H * RATE
    return dict(model=model, cogs=cogs, gm=(PRICE - cogs) / PRICE, support=support,
                contribution=PRICE - cogs - support, gm_after_support=(PRICE - cogs - support) / PRICE)

def project(adds, lifetime, months=36, start=4):
    """Linear new teams per month from `start`; each team stays `lifetime` months on average (churn = 1/lifetime)."""
    u = unit(); subs = 0.0; cum = -BUILD; first = None; peak = 0
    for m in range(1, months + 1):
        if m >= start:
            subs += adds
        subs -= subs / lifetime if m >= start else 0
        peak = max(peak, subs)
        cum += subs * u["contribution"] - (FIXED if m >= start else 0)
        if first is None and cum >= 0:
            first = m
    return dict(steady_subs=adds * lifetime, mrr_steady=adds * lifetime * PRICE, break_even_month=first, cum_36=cum)

if __name__ == "__main__":
    v, u = value(), unit()
    print("VALUE", {k: (round(x, 2) if not isinstance(x, dict) else x) for k, x in v.items()})
    print("UNIT ", {k: round(x, 3) for k, x in u.items()})
    print("BUILD", BUILD)
    for name, adds, life in (("pessimistic", 2, 3), ("base", 4, 4), ("optimistic", 8, 6)):
        print(name, adds, "new/month, stays", life, "months:", project(adds, life))
    print("\nSENSITIVITY on base (4 new/month, 4 months):")
    base = dict(PRICE=PRICE)
    import sys
    mod = sys.modules[__name__]
    for label, attr, val in (("price 49", "PRICE", 49.0), ("price 199", "PRICE", 199.0), ("model cost x10", "PER_FINDING", PER_FINDING * 10),
                             ("support 2h", "SUPPORT_H", 2.0), ("build x2", "BUILD", BUILD * 2)):
        old = getattr(mod, attr); setattr(mod, attr, val)
        print(f"  {label:16s}", {k: round(x, 2) if isinstance(x, float) else x for k, x in unit().items() if k in ("gm", "contribution")}, project(4, 4)["break_even_month"])
        setattr(mod, attr, old)


# ---- v2: Migration Pass, serverless hosting (26 Nov 2026) ----
PASS_PRICE = 149.0      # US$ per migration, 60 days, ~50 runs
PASS_RUNS = 10          # ASSUMED runs actually used per pass, 1,000 findings each, cold
PASS_SUPPORT_H = 1.0    # ASSUMED support hours per pass
IDLE = 3.0              # ASSUMED serverless idle US$/month (S3, DynamoDB, logs, Route 53; Lambda and Cognito in free tier). NOT checked against AWS pages
RUN_COMPUTE = 0.01      # ASSUMED on-demand compute per large run

def pass_unit(price=None, runs=None, support_h=None, model_mult=1.0):
    price = PASS_PRICE if price is None else price
    runs = PASS_RUNS if runs is None else runs
    support_h = PASS_SUPPORT_H if support_h is None else support_h
    model = runs * FINDINGS * PER_FINDING * model_mult
    infra = 1.0 + runs * RUN_COMPUTE
    fee = price * PAY_FEE
    gm = price - model - infra - fee
    sup = support_h * RATE
    return dict(price=price, model=model, infra=infra, fee=fee, gm=gm, gm_pct=gm / price, support=sup,
                contribution=gm - sup, contrib_pct=(gm - sup) / price)

def pass_payback(adds, build, price=None, start=4, months=120):
    c = pass_unit(price)["contribution"]; cum = -build
    for m in range(1, months + 1):
        if m >= start:
            cum += adds * c - IDLE
        if cum >= 0:
            return m
    return None

if __name__ == "__main__":
    print("\nV2 PASS", {k: round(x, 3) for k, x in pass_unit().items()})
    print("model x10", {k: round(x, 2) for k, x in pass_unit(model_mult=10).items() if k in ("gm", "gm_pct", "contribution")})
    print("vote sampling x3.43", {k: round(x, 3) for k, x in pass_unit(model_mult=3.43).items() if k in ("gm_pct", "contribution")})
    print("share of saving", PASS_PRICE / (PASSES * (PASS_H - PASS_H_TOOL) * RATE))
    for name, adds in (("pessimistic", 2), ("base", 4), ("optimistic", 8)):
        print(name, adds, "passes/month, revenue", adds * PASS_PRICE, "lean", pass_payback(adds, 3 * 160 * RATE), "full", pass_payback(adds, BUILD),
              "| at $299 lean", pass_payback(adds, 3 * 160 * RATE, 299.0))
