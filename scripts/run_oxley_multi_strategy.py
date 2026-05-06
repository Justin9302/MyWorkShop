#!/usr/bin/env python3
"""
Oxley Solar Farm — 多调度策略对比 (V4.1)
严格按 workflows/energy/solar_financial_model.yaml 执行:
  Step 7: ≥2种调度策略对比
  Step 12: 敏感性分析

策略来源: data/market_reference_au.yaml V0.3 (bess_dispatch_strategies)
"""
import sys, os, json, copy
sys.path.insert(0, os.path.dirname(__file__))

from solar_financial_engine import (
    ProjectInput, TimelineInput, TechnologyInput, CapexInput,
    OpexInput, RevenueInput, FinancingInput, TaxInput,
    MidLifeInput, GenerationProfile, ScenarioManager
)

# ═══════════════════════════════════════════════════════════════
# 基础参数（共享）
# ═══════════════════════════════════════════════════════════════

def base_project(strategy_name):
    """创建基础项目模板
    V3: enable_market_equilibrium=True → 自动根据COD年份(2029)调整收入参数
    """
    return ProjectInput(
        name="Oxley Solar Farm (Hybrid)",
        location="NSW, Australia (Armidale SE)",
        currency="AUD",
        scenario_name=strategy_name,

        # ═══ V3: 启用市场均衡 ═══
        enable_market_equilibrium=True,
        market_equilibrium_cod_year=2029,    # 建设24个月 → COD 2028末/2029初
        market_equilibrium_fcas=20.0,        # 混合FCAS (V0.3)

        timeline=TimelineInput(
            construction_start="2026-07-01",
            construction_months=24,
            operation_years=30
        ),

        technology=TechnologyInput(
            pv_capacity_mwp=215,
            bess_capacity_mw=215,
            bess_duration_hrs=6,
            pv_degradation_pa=0.005,
            bess_degradation_pa=0.02,
            bess_rte=0.90,
            aux_consumption_pct=0.01
        ),

        # CAPEX: 全包价模式，bop_epc_pct=0
        # V0.3: NSW solar $1,000-1,500/kW, BESS 6hr ~$1,100-1,300/kW
        # 接入费: $40M (132kV双回路, V0.3行业估算)
        capex=CapexInput(
            pv_capex_per_kwp=1250,
            bess_capex_per_kw=1200,
            bop_epc_pct=0.0,
            development_cost=45000,     # $5M dev + $40M connection
            contingency_pct=0.05
        ),

        opex=OpexInput(
            pv_fixed_per_kwp_year=15,
            pv_variable_per_mwh=3,
            bess_fixed_per_kw_year=20,
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

        # V0.3: LFP 增容30% (非NMC更换65%)
        mid_life=MidLifeInput(
            battery_replace_year=12,
            battery_replace_cost_pct=0.30,   # LFP augmentation
            inverter_replace_year=15,
            inverter_replace_cost_pct=0.12
        ),

        generation=GenerationProfile(
            pv_cf_monthly=[0.20, 0.19, 0.20, 0.21, 0.22, 0.23,
                           0.22, 0.21, 0.20, 0.19, 0.18, 0.17],
            bess_cycles_per_day=1.0
        )
    )

# ═══════════════════════════════════════════════════════════════
# 策略定义 (来源: V0.3 bess_dispatch_strategies)
# ═══════════════════════════════════════════════════════════════

scenarios = {}

# ── 策略A: 简单日循环（保守基准）──
p = base_project("A-简单日循环 (保守)")
p.revenue = RevenueInput(
    ppa_price_aud_mwh=0, ppa_percentage=0.0,
    merchant_price_aud_mwh=75,
    solar_capture_price_aud_mwh=65,      # PV excess → grid at slightly better
    lgc_price_aud=37, lgc_rate_per_mwh=1.0,
    fcas_revenue_aud_kw_year=20,         # V0.3: hybrid $15-25
    revenue_escalation=0.0,
    bess_charge_price_aud_mwh=25,        # V0.3: simple daily charge
    bess_discharge_price_aud_mwh=120     # V0.3: simple daily discharge
)
scenarios["A-简单日循环"] = p

# ── 策略B: 60%负价捕获优化（推荐基准）──
p = base_project("B-60%负价捕获 (V0.3推荐基准)")
p.revenue = RevenueInput(
    ppa_price_aud_mwh=0, ppa_percentage=0.0,
    merchant_price_aud_mwh=75,
    solar_capture_price_aud_mwh=65,
    lgc_price_aud=37, lgc_rate_per_mwh=1.0,
    fcas_revenue_aud_kw_year=20,
    revenue_escalation=0.0,
    bess_charge_price_aud_mwh=-12.5,     # V0.3: 60%负价捕获
    bess_discharge_price_aud_mwh=170     # V0.3: 优化放电
)
scenarios["B-60%负价捕获"] = p

# ── 策略C: 双重优化（乐观情景）──
p = base_project("C-双重优化 (乐观)")
p.revenue = RevenueInput(
    ppa_price_aud_mwh=0, ppa_percentage=0.0,
    merchant_price_aud_mwh=75,
    solar_capture_price_aud_mwh=65,
    lgc_price_aud=37, lgc_rate_per_mwh=1.0,
    fcas_revenue_aud_kw_year=25,         # 激进FCAS（部分解锁纯储能能力）
    revenue_escalation=0.0,
    bess_charge_price_aud_mwh=-15,       # V0.3: 80%负价捕获
    bess_discharge_price_aud_mwh=175     # V0.3: 最高放电
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
print("  Oxley Solar Farm — 多调度策略对比")
print("  215MW PV + 215MW/6hr BESS | LFP增容30% | 混合FCAS $20/kW")
print("=" * 80)

print(f"\n{'策略':<24} {'IRR%':>7} {'NPV@6% k$':>12} {'LCOE':>7} {'LCOS':>7} {'价差$/MWh':>10} {'年收入k$':>9}")
print("-" * 80)

for name, r in results.items():
    km = r["key_metrics"]
    annual = r.get("annual_data", {})
    
    # 计算有效价差
    rev = scenarios[name].revenue
    spread = rev.bess_discharge_price_aud_mwh - rev.bess_charge_price_aud_mwh
    
    # 首年运营收入
    rev_list = annual.get("revenue", [])
    first_yr_rev = 0
    for v in rev_list:
        if v > 0:
            first_yr_rev = v
            break
    
    print(f"{name:<24} {km.get('project_irr_post_tax',0)*100:>6.2f}% "
          f"{km.get('project_npv_post_tax_6pct',0):>11,.0f} "
          f"${km.get('lcoe_discounted_aud_mwh',0):>6.0f} "
          f"${km.get('lcos_discounted_aud_mwh',0):>6.0f} "
          f"${spread:>9.1f} "
          f"${first_yr_rev:>8,.0f}")

print("-" * 80)

# ── 找出最优 ──
best = max(results.items(), key=lambda x: x[1]["key_metrics"]["project_irr_post_tax"])
print(f"\n✅ 最优策略: {best[0]} (IRR: {best[1]['key_metrics']['project_irr_post_tax']*100:.2f}%)")

# ═══════════════════════════════════════════════════════════════
# 敏感性分析 (Step 12) — 基于最优策略
# ═══════════════════════════════════════════════════════════════

print(f"\n{'='*80}")
print(f"  敏感性分析 — 基于最优策略: {best[0]}")
print(f"{'='*80}")

base_proj = copy.deepcopy(scenarios[best[0]])
base_proj.scenario_name = "BASE"

sensitivities = {}

# 变量1: BESS CAPEX ±20%
for delta_pct, label in [(-0.20, "BESS CAPEX -20%"), (0.20, "BESS CAPEX +20%")]:
    p = copy.deepcopy(base_proj)
    p.capex.bess_capex_per_kw *= (1 + delta_pct)
    p.scenario_name = label
    sensitivities[label] = p

# 变量2: 放电价格 ±15%
for delta, label in [(-15, "放电价 -$15"), (15, "放电价 +$15")]:
    p = copy.deepcopy(base_proj)
    p.revenue.bess_discharge_price_aud_mwh += delta
    p.scenario_name = label
    sensitivities[label] = p

# 变量3: 充电价格 ±$15
for delta, label in [(15, "充电价 +$15 (恶化)"), (-15, "充电价 -$15 (改善)")]:
    p = copy.deepcopy(base_proj)
    p.revenue.bess_charge_price_aud_mwh += delta
    p.scenario_name = label
    sensitivities[label] = p

# 变量4: PV CAPEX ±20%
for delta_pct, label in [(-0.20, "PV CAPEX -20%"), (0.20, "PV CAPEX +20%")]:
    p = copy.deepcopy(base_proj)
    p.capex.pv_capex_per_kwp *= (1 + delta_pct)
    p.scenario_name = label
    sensitivities[label] = p

# 变量5: LGC价格 ±$10
for delta, label in [(-10, "LGC -$10"), (10, "LGC +$10")]:
    p = copy.deepcopy(base_proj)
    p.revenue.lgc_price_aud += delta
    p.scenario_name = label
    sensitivities[label] = p

# 组合情景: BESS CAPEX -20% + 放电价 +$15 (最乐观)
p = copy.deepcopy(base_proj)
p.capex.bess_capex_per_kw *= 0.80
p.revenue.bess_discharge_price_aud_mwh += 15
p.scenario_name = "组合乐观 (BESS↓+放电↑)"
sensitivities["组合乐观"] = p

# 组合情景: BESS CAPEX +20% + 放电价 -$15 (最悲观)
p = copy.deepcopy(base_proj)
p.capex.bess_capex_per_kw *= 1.20
p.revenue.bess_discharge_price_aud_mwh -= 15
p.scenario_name = "组合悲观 (BESS↑+放电↓)"
sensitivities["组合悲观"] = p

print(f"\n运行 {len(sensitivities)} 个敏感性情景...")
sens_manager = ScenarioManager()
for name, proj in sensitivities.items():
    sens_manager.add_scenario(name, proj)

sens_results = sens_manager.run_all()
base_irr = results[best[0]]["key_metrics"]["project_irr_post_tax"]

print(f"\n{'敏感性变量':<28} {'IRR%':>7} {'ΔIRR bp':>9} {'NPV@6% k$':>12}")
print("-" * 65)
print(f"{'BASE (最优策略)':<28} {base_irr*100:>6.2f}% {'—':>9} {results[best[0]]['key_metrics']['project_npv_post_tax_6pct']:>11,.0f}")
print("-" * 65)

# 按敏感度排序
sensitivity_list = []
for name, r in sens_results.items():
    irr = r["key_metrics"]["project_irr_post_tax"]
    delta_bp = (irr - base_irr) * 10000
    npv = r["key_metrics"]["project_npv_post_tax_6pct"]
    sensitivity_list.append((name, irr, delta_bp, npv))

sensitivity_list.sort(key=lambda x: abs(x[2]), reverse=True)

for name, irr, delta_bp, npv in sensitivity_list:
    sign = "+" if delta_bp >= 0 else ""
    print(f"{name:<28} {irr*100:>6.2f}% {sign}{delta_bp:>8.0f} {npv:>11,.0f}")

print("-" * 65)

# ═══════════════════════════════════════════════════════════════
# 保存结果
# ═══════════════════════════════════════════════════════════════
output = {
    "strategies": {name: r for name, r in results.items()},
    "sensitivities": {name: r for name, r in sens_results.items()},
    "best_strategy": best[0],
    "base_irr": base_irr
}
outpath = os.path.join(os.path.dirname(__file__), "..", "OUTPUT", "oxley_multi_strategy.json")
with open(outpath, "w") as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n结果已保存至: {outpath}")
