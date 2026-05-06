#!/usr/bin/env python3
"""
Gullen Range BESS — 纯储能多策略对比 (V0.3 + V2.1工作流)
严格按 workflows/energy/solar_financial_model.yaml V2.1 执行:
  - 纯储能项目必须设置负电价策略 (block_condition)
  - Step 7: ≥2种调度策略对比
  - FCAS: 纯储能 $35/kW/年 (非混合 $20)
  - 策略来源: data/market_reference_au.yaml V0.3 bess_dispatch_strategies
"""
import sys, os, json, copy
sys.path.insert(0, os.path.dirname(__file__))

from solar_financial_engine import (
    ProjectInput, TimelineInput, TechnologyInput, CapexInput,
    OpexInput, RevenueInput, FinancingInput, TaxInput,
    MidLifeInput, GenerationProfile, ScenarioManager
)

# ═══════════════════════════════════════════════════════════════
# 基础参数 — V0.3 推荐值
# ═══════════════════════════════════════════════════════════════

def base_project(strategy_name):
    return ProjectInput(
        name="Gullen Range BESS",
        location="NSW, Australia (Goulburn, Southern Tablelands)",
        currency="AUD",
        scenario_name=strategy_name,

        timeline=TimelineInput(
            construction_start="2026-07-01",
            construction_months=18,          # 纯储能建设快于光储混合
            operation_years=25               # BESS 标准运营期
        ),

        technology=TechnologyInput(
            pv_capacity_mwp=0,              # 纯储能，无光伏
            bess_capacity_mw=300,            # 300 MW
            bess_duration_hrs=4,             # 4 小时
            pv_degradation_pa=0.0,
            bess_degradation_pa=0.02,        # 2%/年
            bess_rte=0.90,                   # 90% RTE
            aux_consumption_pct=0.02         # 2% 厂用电（纯储能偏高）
        ),

        # CAPEX: V0.3 NSW 4hr BESS $800-1,100/kW → 取 $900/kW (全包价)
        # 接入费: 300MW → 275kV, V0.3 估算 $60-80M → 取 $70M
        capex=CapexInput(
            pv_capex_per_kwp=0,
            bess_capex_per_kw=900,           # V0.3 NSW 4hr 中值
            bop_epc_pct=0.0,                 # 全包价模式
            development_cost=75000,           # $5M dev + $70M connection = $75M (kAUD)
            contingency_pct=0.05
        ),

        opex=OpexInput(
            pv_fixed_per_kwp_year=0,
            pv_variable_per_mwh=0,
            bess_fixed_per_kw_year=20,       # V0.3: $15-25/kW/年
            bess_variable_per_mwh=5,
            escalation_rate=0.02
        ),

        # 融资: 全投资口径
        financing=FinancingInput(
            gearing_pct=0.0,
            interest_rate_pa=0.0,
            debt_tenor_years=0,
            dsra_months=0,
            financing_fees_pct=0.0,
            arrangement_fee_pct=0.0
        ),

        tax=TaxInput(
            corporate_tax_rate=0.30,
            depreciation_method="SL",
            pv_effective_life_years=20,
            bess_effective_life_years=15,
            inverter_effective_life_years=10,
            civil_works_life_years=40
        ),

        # V0.3: LFP 增容30%
        mid_life=MidLifeInput(
            battery_replace_year=12,
            battery_replace_cost_pct=0.30,
            inverter_replace_year=15,
            inverter_replace_cost_pct=0.0     # 纯储能无光伏逆变器
        ),

        generation=GenerationProfile(
            pv_cf_monthly=[],
            bess_cycles_per_day=1.0
        )
    )

# ═══════════════════════════════════════════════════════════════
# 策略定义 — V0.3 bess_dispatch_strategies + 纯储能FCAS
# ═══════════════════════════════════════════════════════════════

scenarios = {}

# ── 策略A: 简单日循环（保守基准）──
p = base_project("A-简单日循环 (保守)")
p.revenue = RevenueInput(
    ppa_price_aud_mwh=0, ppa_percentage=0.0,
    merchant_price_aud_mwh=0,
    solar_capture_price_aud_mwh=0,
    lgc_price_aud=0, lgc_rate_per_mwh=0,    # 纯储能无LGC
    fcas_revenue_aud_kw_year=35,             # ⚡ 纯储能 FCAS $35/kW
    revenue_escalation=0.0,
    bess_charge_price_aud_mwh=25,            # V0.3: simple daily charge
    bess_discharge_price_aud_mwh=120         # V0.3: simple daily discharge
)
scenarios["A-简单日循环"] = p

# ── 策略B: 60%负价捕获（V0.3推荐基准）──
p = base_project("B-60%负价捕获 (推荐)")
p.revenue = RevenueInput(
    ppa_price_aud_mwh=0, ppa_percentage=0.0,
    merchant_price_aud_mwh=0,
    solar_capture_price_aud_mwh=0,
    lgc_price_aud=0, lgc_rate_per_mwh=0,
    fcas_revenue_aud_kw_year=35,
    revenue_escalation=0.0,
    bess_charge_price_aud_mwh=-12.5,         # V0.3: 60%负价捕获 — 被倒贴充电！
    bess_discharge_price_aud_mwh=170
)
scenarios["B-60%负价捕获"] = p

# ── 策略C: 双重优化（乐观）──
p = base_project("C-双重优化 (乐观)")
p.revenue = RevenueInput(
    ppa_price_aud_mwh=0, ppa_percentage=0.0,
    merchant_price_aud_mwh=0,
    solar_capture_price_aud_mwh=0,
    lgc_price_aud=0, lgc_rate_per_mwh=0,
    fcas_revenue_aud_kw_year=40,             # V0.3: 纯储能 FCAS boost
    revenue_escalation=0.0,
    bess_charge_price_aud_mwh=-15,           # V0.3: 80%负价捕获
    bess_discharge_price_aud_mwh=175
)
scenarios["C-双重优化"] = p

# ═══════════════════════════════════════════════════════════════
# 运行所有策略
# ═══════════════════════════════════════════════════════════════

manager = ScenarioManager()
for name, proj in scenarios.items():
    manager.add_scenario(name, proj)

results = manager.run_all()

# ═══════════════════════════════════════════════════════════════
# 输出对比
# ═══════════════════════════════════════════════════════════════

print("=" * 80)
print("  Gullen Range BESS — 纯储能多调度策略对比")
print("  300 MW / 4hr (1,200 MWh) | LFP增容30% | 纯储能FCAS $35-40/kW")
print("  V0.3 CAPEX $900/kW | 275kV接入 $70M | NSW Goulburn")
print("=" * 80)

print(f"\n{'策略':<24} {'IRR%':>7} {'NPV@6% k$':>12} {'LCOS':>7} {'价差$/MWh':>9} {'年收入k$':>9} {'年OPEXk$':>8}")
print("-" * 85)

for name, r in results.items():
    km = r["key_metrics"]
    annual = r.get("annual_data", {})
    
    rev = scenarios[name].revenue
    spread = rev.bess_discharge_price_aud_mwh - rev.bess_charge_price_aud_mwh
    
    rev_list = annual.get("revenue", [])
    opex_list = annual.get("opex", [])
    first_yr_rev = 0
    first_yr_opex = 0
    for v in rev_list:
        if v > 0:
            first_yr_rev = v
            break
    for v in opex_list:
        if v > 0:
            first_yr_opex = v
            break
    
    print(f"{name:<24} {km.get('project_irr_post_tax',0)*100:>6.2f}% "
          f"{km.get('project_npv_post_tax_6pct',0):>11,.0f} "
          f"${km.get('lcos_discounted_aud_mwh',0):>6.0f} "
          f"${spread:>8.1f} "
          f"${first_yr_rev:>8,.0f} "
          f"${first_yr_opex:>7,.0f}")

print("-" * 85)

best = max(results.items(), key=lambda x: x[1]["key_metrics"]["project_irr_post_tax"])
print(f"\n✅ 最优策略: {best[0]} (IRR: {best[1]['key_metrics']['project_irr_post_tax']*100:.2f}%)")

# ═══════════════════════════════════════════════════════════════
# 旧 vs 新对比
# ═══════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print(f"  新旧参数对比")
print(f"{'='*80}")
print(f"{'':<24} {'旧版(单策略)':>16} {'新版(最优策略)':>16}")
print(f"{'BESS CAPEX':<24} {'$700/kW':>16} {'$900/kW':>16}")
print(f"{'接入费':<24} {'$15M':>16} {'$70M':>16}")
print(f"{'FCAS':<24} {'未明确':>16} {'$35-40/kW':>16}")
print(f"{'调度策略':<24} {'1种(简单)':>16} {'3种对比':>16}")
print(f"{'负电价':<24} {'❌ 未设置':>16} {'✅ 60-80%捕获':>16}")

# ═══════════════════════════════════════════════════════════════
# 收入拆解 (最优策略首年)
# ═══════════════════════════════════════════════════════════════
best_r = best[1]
best_annual = best_r.get("annual_data", {})
best_rev = best_annual.get("revenue", [])
first_op_year_rev = 0
for v in best_rev:
    if v > 0:
        first_op_year_rev = v
        break

print(f"\n{'='*80}")
print(f"  收入结构 (最优策略: {best[0]}, 首运营年)")
print(f"{'='*80}")

# 用引擎算月均拆解
import numpy as np
best_p = scenarios[best[0]]
charge_p = best_p.revenue.bess_charge_price_aud_mwh
discharge_p = best_p.revenue.bess_discharge_price_aud_mwh
fcas_p = best_p.revenue.fcas_revenue_aud_kw_year

# 月度理论值
days = 30.44
bess_mw = 300
bess_hrs = 4
rte = 0.90
monthly_charge = bess_mw * bess_hrs * days / rte  # MWh input
monthly_discharge = bess_mw * bess_hrs * days        # MWh output

charge_cost = monthly_charge * charge_p / 1000       # kAUD
discharge_rev = monthly_discharge * discharge_p / 1000
fcas_rev = bess_mw * 1000 * fcas_p / 12 / 1000

print(f"  月度放电量:      {monthly_discharge:,.0f} MWh")
print(f"  月度充电量:      {monthly_charge:,.0f} MWh (含RTE损耗)")
print(f"  放电收入:        ${discharge_rev*12:,.0f}k/年 (@ ${discharge_p}/MWh)")
print(f"  充电成本:        ${charge_cost*12:,.0f}k/年 (@ ${charge_p}/MWh)")
print(f"  FCAS收入:        ${fcas_rev*12:,.0f}k/年 (@ ${fcas_p}/kW/年)")
print(f"  净收入(理论):    ${(discharge_rev + charge_cost + fcas_rev)*12:,.0f}k/年")
print(f"  引擎实际收入:    ${first_op_year_rev:,.0f}k/年")

# ═══════════════════════════════════════════════════════════════
# 敏感性分析 (Step 12)
# ═══════════════════════════════════════════════════════════════

print(f"\n{'='*80}")
print(f"  敏感性分析 — 基于最优策略: {best[0]}")
print(f"{'='*80}")

base_proj = copy.deepcopy(scenarios[best[0]])
base_proj.scenario_name = "BASE"

sensitivities = {}

# BESS CAPEX ±20%
for delta_pct, label in [(-0.20, "BESS CAPEX -20%"), (0.20, "BESS CAPEX +20%")]:
    p = copy.deepcopy(base_proj)
    p.capex.bess_capex_per_kw *= (1 + delta_pct)
    p.scenario_name = label
    sensitivities[label] = p

# 放电价 ±$15
for delta, label in [(-15, "放电价 -$15"), (15, "放电价 +$15")]:
    p = copy.deepcopy(base_proj)
    p.revenue.bess_discharge_price_aud_mwh += delta
    p.scenario_name = label
    sensitivities[label] = p

# 充电价 ±$15
for delta, label in [(15, "充电价 +$15 (恶化)"), (-15, "充电价 -$15 (改善)")]:
    p = copy.deepcopy(base_proj)
    p.revenue.bess_charge_price_aud_mwh += delta
    p.scenario_name = label
    sensitivities[label] = p

# FCAS ±$10
for delta, label in [(-10, "FCAS -$10"), (10, "FCAS +$10")]:
    p = copy.deepcopy(base_proj)
    p.revenue.fcas_revenue_aud_kw_year += delta
    p.scenario_name = label
    sensitivities[label] = p

# 组合
p = copy.deepcopy(base_proj)
p.capex.bess_capex_per_kw *= 0.80
p.revenue.bess_discharge_price_aud_mwh += 15
p.scenario_name = "组合乐观 (CAPEX↓+放电↑)"
sensitivities["组合乐观"] = p

p = copy.deepcopy(base_proj)
p.capex.bess_capex_per_kw *= 1.20
p.revenue.bess_discharge_price_aud_mwh -= 15
p.scenario_name = "组合悲观 (CAPEX↑+放电↓)"
sensitivities["组合悲观"] = p

sens_manager = ScenarioManager()
for name, proj in sensitivities.items():
    sens_manager.add_scenario(name, proj)
sens_results = sens_manager.run_all()

base_irr = results[best[0]]["key_metrics"]["project_irr_post_tax"]

print(f"\n{'敏感性变量':<30} {'IRR%':>7} {'ΔIRR bp':>9} {'NPV@6% k$':>12}")
print("-" * 65)
print(f"{'BASE (最优策略)':<30} {base_irr*100:>6.2f}% {'—':>9} {results[best[0]]['key_metrics']['project_npv_post_tax_6pct']:>11,.0f}")
print("-" * 65)

sensitivity_list = []
for name, r in sens_results.items():
    irr = r["key_metrics"]["project_irr_post_tax"]
    delta_bp = (irr - base_irr) * 10000
    npv = r["key_metrics"]["project_npv_post_tax_6pct"]
    sensitivity_list.append((name, irr, delta_bp, npv))
sensitivity_list.sort(key=lambda x: abs(x[2]), reverse=True)

for name, irr, delta_bp, npv in sensitivity_list:
    sign = "+" if delta_bp >= 0 else ""
    print(f"{name:<30} {irr*100:>6.2f}% {sign}{delta_bp:>8.0f} {npv:>11,.0f}")

print("-" * 65)

# ═══════════════════════════════════════════════════════════════
outpath = os.path.join(os.path.dirname(__file__), "..", "OUTPUT", "gullen_bess_v03_multi_strategy.json")
with open(outpath, "w") as f:
    json.dump({"strategies": {n: r for n, r in results.items()},
               "sensitivities": {n: r for n, r in sens_results.items()},
               "best_strategy": best[0]}, f, indent=2, default=str)
print(f"\n结果已保存至: {outpath}")
