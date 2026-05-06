#!/usr/bin/env python3
"""
Oxley Solar Farm — 多策略 + 市场均衡 V3
=========================================
集成 bess_market_equilibrium 模块: 根据COD 2029自动调整收入参数
"""
import sys, os, json, copy
sys.path.insert(0, os.path.dirname(__file__))

from solar_financial_engine import *
from bess_market_equilibrium import MarketEquilibrium

eq = MarketEquilibrium()

def build_oxley(strategy_name, charge, discharge, fcas):
    """构建Oxley项目, V3启用市场均衡"""
    p = ProjectInput(
        name="Oxley Solar Farm (Hybrid)", location="NSW, Australia (Armidale SE)",
        currency="AUD", scenario_name=strategy_name,
        timeline=TimelineInput(construction_start="2026-07-01", construction_months=24, operation_years=30),
        technology=TechnologyInput(pv_capacity_mwp=215, bess_capacity_mw=215, bess_duration_hrs=6,
                                   pv_degradation_pa=0.005, bess_degradation_pa=0.02, bess_rte=0.90, aux_consumption_pct=0.01),
        capex=CapexInput(pv_capex_per_kwp=1250, bess_capex_per_kw=1200, bop_epc_pct=0.0,
                         development_cost=45000, contingency_pct=0.05),
        opex=OpexInput(pv_fixed_per_kwp_year=15, pv_variable_per_mwh=3,
                       bess_fixed_per_kw_year=20, bess_variable_per_mwh=5, escalation_rate=0.02),
        revenue=RevenueInput(ppa_price_aud_mwh=0, ppa_percentage=0.0, merchant_price_aud_mwh=75,
                             solar_capture_price_aud_mwh=65, lgc_price_aud=37, lgc_rate_per_mwh=1.0,
                             fcas_revenue_aud_kw_year=fcas, revenue_escalation=0.0,
                             bess_charge_price_aud_mwh=charge, bess_discharge_price_aud_mwh=discharge),
        financing=FinancingInput(gearing_pct=0.0),
        tax=TaxInput(corporate_tax_rate=0.30, depreciation_method="SL"),
        mid_life=MidLifeInput(battery_replace_year=12, battery_replace_cost_pct=0.30,
                             inverter_replace_year=15, inverter_replace_cost_pct=0.12),
        generation=GenerationProfile(pv_cf_monthly=[0.20,0.19,0.20,0.21,0.22,0.23,0.22,0.21,0.20,0.19,0.18,0.17], bess_cycles_per_day=1.0),
    )
    # V3: 应用市场均衡
    r = eq.adjust_revenue(2029, charge, discharge, fcas)
    p.revenue.bess_charge_price_aud_mwh = r["equilibrium_charge"]
    p.revenue.bess_discharge_price_aud_mwh = r["equilibrium_discharge"]
    p._equilibrium_meta = r
    return p

# 策略定义
scenarios = {
    "A-简单日循环": build_oxley("A-简单日循环(均衡)", 25, 120, 20),
    "B-60%负价捕获": build_oxley("B-60%负价捕获(均衡)", -12.5, 170, 20),
    "C-双重优化": build_oxley("C-双重优化(均衡)", -15, 175, 25),
}

# 运行
mgr = ScenarioManager()
for n, p in scenarios.items():
    mgr.add_scenario(n, p)
results = mgr.run_all()

print("=" * 80)
print("  Oxley Solar Farm — 多策略 + 市场均衡 V3 (COD 2029)")
print("=" * 80)

# 先展示均衡调整信息
meta = scenarios["C-双重优化"]._equilibrium_meta
print(f"\n⚖️ 市场均衡调整 (COD {meta['cod_year']}):")
print(f"  BESS装机: {meta['projected_bess_gw']}GW  煤电: {meta['projected_coal_gw']}GW")
print(f"  市场阶段: {meta['market_phase']}")
print(f"  均衡价差: ${meta['equilibrium_spread']}/MWh → 约IRR {meta['equilibrium_irr']*100:.1f}%")

print(f"\n{'策略':<24} {'原始价差':>10} {'均衡价差':>10} {'IRR%':>7} {'NPV@6%k$':>12} {'LCOS':>7}")
print("-" * 75)

for name, r in results.items():
    km = r["key_metrics"]
    p = scenarios[name]
    orig_spread = p.revenue.bess_discharge_price_aud_mwh - p.revenue.bess_charge_price_aud_mwh
    print(f"{name:<24} ${orig_spread:>8.0f} ${orig_spread:>9.0f} {km.get('project_irr_post_tax',0)*100:>6.2f}% {km.get('project_npv_post_tax_6pct',0):>11,.0f} ${km.get('lcos_discounted_aud_mwh',0):>6.0f}")

best = max(results.items(), key=lambda x: x[1]["key_metrics"]["project_irr_post_tax"])
print(f"\n✅ 最优: {best[0]} (IRR {best[1]['key_metrics']['project_irr_post_tax']*100:.2f}%)")
print(f"📌 均衡后IRR比静态模型低约 {(0.1555-best[1]['key_metrics']['project_irr_post_tax'])*100:.1f}pp — 反映2029年市场BESS容量增加后的价差压缩")

outpath = os.path.join(os.path.dirname(__file__), "..", "OUTPUT", "oxley_v3_equilibrium.json")
json.dump({"equilibrium_meta": meta, "results": {n: r for n,r in results.items()}},
          open(outpath, "w"), indent=2, default=str)
print(f"结果已保存: {outpath}")
