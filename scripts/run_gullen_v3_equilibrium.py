#!/usr/bin/env python3
"""
Gullen Range BESS — 多策略 + 市场均衡 V3
==========================================
集成 bess_market_equilibrium: 根据COD 2028 (18个月建设)自动调整
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))

from solar_financial_engine import *
from bess_market_equilibrium import MarketEquilibrium

eq = MarketEquilibrium()
COD = 2028  # 2026.07 + 18个月

def build_gullen(strategy_name, charge, discharge, fcas):
    p = ProjectInput(
        name="Gullen Range BESS", location="NSW, Australia (Goulburn)",
        currency="AUD", scenario_name=strategy_name,
        timeline=TimelineInput(construction_start="2026-07-01", construction_months=18, operation_years=25),
        technology=TechnologyInput(pv_capacity_mwp=0, bess_capacity_mw=300, bess_duration_hrs=4,
                                   bess_degradation_pa=0.02, bess_rte=0.90, aux_consumption_pct=0.02),
        capex=CapexInput(pv_capex_per_kwp=0, bess_capex_per_kw=900, bop_epc_pct=0.0,
                         development_cost=75000, contingency_pct=0.05),
        opex=OpexInput(pv_fixed_per_kwp_year=0, pv_variable_per_mwh=0,
                       bess_fixed_per_kw_year=20, bess_variable_per_mwh=5, escalation_rate=0.02),
        revenue=RevenueInput(ppa_price_aud_mwh=0, ppa_percentage=0.0, merchant_price_aud_mwh=0,
                             solar_capture_price_aud_mwh=0, lgc_price_aud=0, lgc_rate_per_mwh=0,
                             fcas_revenue_aud_kw_year=fcas, revenue_escalation=0.0,
                             bess_charge_price_aud_mwh=charge, bess_discharge_price_aud_mwh=discharge),
        financing=FinancingInput(gearing_pct=0.0),
        tax=TaxInput(corporate_tax_rate=0.30, depreciation_method="SL"),
        mid_life=MidLifeInput(battery_replace_year=12, battery_replace_cost_pct=0.30),
        generation=GenerationProfile(pv_cf_monthly=[], bess_cycles_per_day=1.0),
    )
    r = eq.adjust_revenue(COD, charge, discharge, fcas)
    p.revenue.bess_charge_price_aud_mwh = r["equilibrium_charge"]
    p.revenue.bess_discharge_price_aud_mwh = r["equilibrium_discharge"]
    p._equilibrium_meta = r
    return p

scenarios = {
    "A-简单日循环": build_gullen("A-简单日循环(均衡)", 25, 120, 35),
    "B-60%负价捕获": build_gullen("B-60%负价捕获(均衡)", -12.5, 170, 35),
    "C-双重优化": build_gullen("C-双重优化(均衡)", -15, 175, 40),
}

mgr = ScenarioManager()
for n, p in scenarios.items(): mgr.add_scenario(n, p)
results = mgr.run_all()

meta = scenarios["C-双重优化"]._equilibrium_meta

print("=" * 80)
print(f"  Gullen Range BESS — 多策略 + 市场均衡 V3 (COD {COD})")
print("=" * 80)
print(f"\n⚖️ 市场均衡 (COD {COD}): BESS {meta['projected_bess_gw']}GW  煤电 {meta['projected_coal_gw']}GW  阶段 {meta['market_phase']}")
print(f"   均衡价差 ${meta['equilibrium_spread']}/MWh → 约 {meta['equilibrium_irr']*100:.1f}% IRR")

print(f"\n{'策略':<22} {'原始价差':>8} {'均衡价差':>8} {'IRR%':>7} {'NPV@6%k$':>12} {'LCOS':>7}")
print("-" * 70)

for name, r in results.items():
    km = r["key_metrics"]
    p = scenarios[name]
    orig = p._equilibrium_meta["original_spread"]
    eqs = p._equilibrium_meta["equilibrium_spread"]
    print(f"{name:<22} ${orig:>6.0f} ${eqs:>7.0f} {km.get('project_irr_post_tax',0)*100:>6.2f}% {km.get('project_npv_post_tax_6pct',0):>11,.0f} ${km.get('lcos_discounted_aud_mwh',0):>6.0f}")

best = max(results.items(), key=lambda x: x[1]["key_metrics"]["project_irr_post_tax"])
static_irr = 0.1555
print(f"\n✅ 最优: {best[0]} (IRR {best[1]['key_metrics']['project_irr_post_tax']*100:.2f}%)")
print(f"📌 vs静态模型(15.55%): -{(static_irr-best[1]['key_metrics']['project_irr_post_tax'])*100:.1f}pp — COD 2028仍处先行者窗口")

outpath = os.path.join(os.path.dirname(__file__), "..", "OUTPUT", "gullen_v3_equilibrium.json")
json.dump({"equilibrium_meta": meta, "results": {n:r for n,r in results.items()}},
          open(outpath, "w"), indent=2, default=str)
print(f"结果已保存: {outpath}")
