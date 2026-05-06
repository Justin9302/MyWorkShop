#!/usr/bin/env python3
"""
Oxley Solar Farm — 光储混合项目 IRR 测算 (V4)
基于 data/market_reference_au.yaml V0.3 (2026-05-06 更新)
修正: LFP电池增容30% (非NMC更换65%), FCAS混合差异化 $20/kW
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))

from solar_financial_engine import (
    ProjectInput, TimelineInput, TechnologyInput, CapexInput,
    OpexInput, RevenueInput, FinancingInput, TaxInput,
    MidLifeInput, GenerationProfile, ScenarioManager
)

# ═══════════════════════════════════════════════════════════════════════
# 项目参数
# ═══════════════════════════════════════════════════════════════════════

project = ProjectInput(
    name="Oxley Solar Farm (Hybrid)",
    location="NSW, Australia (Armidale SE)",
    currency="AUD",
    scenario_name="Base Case V4 - 215MW PV + 215MW/6hr BESS (V0.3 LFP+混合FCAS)",

    # ── 时间线 ──
    timeline=TimelineInput(
        construction_start="2026-07-01",
        construction_months=24,
        operation_years=30          # 网站声明 30 年设计寿命
    ),

    # ── 技术参数 ──
    technology=TechnologyInput(
        pv_capacity_mwp=215,        # 215 MWp
        bess_capacity_mw=215,       # 215 MW
        bess_duration_hrs=6,        # 6 小时
        pv_degradation_pa=0.005,    # 0.5%/年
        bess_degradation_pa=0.02,   # 2%/年
        bess_rte=0.90,              # 90% 往返效率
        aux_consumption_pct=0.01    # 1% 厂用电
    ),

    # ── CAPEX ──
    # 方式B：全包安装价（含设备+安装），bop_epc_pct=0 避免双重计费
    # V0.3: NSW solar $1,000-1,500/kW, BESS 6hr ~$1,100-1,300/kW
    # 接入费: $40M (132kV双回路, V0.3行业估算)
    capex=CapexInput(
        pv_capex_per_kwp=1250,      # $1,250/kWp 全包安装价 × 215MW → $268.75M
        bess_capex_per_kw=1200,     # $1,200/kW 全包安装价 × 215MW → $258.0M
        bop_epc_pct=0.0,            # 全包价，BOP/EPC 已含在单价中
        development_cost=45000,     # $5M 开发费 + $40M 接入费 = $45M (kAUD)
        contingency_pct=0.05        # 不可预见费 5%
    ),

    # ── OPEX ──
    opex=OpexInput(
        pv_fixed_per_kwp_year=15,       # $15/kWp/年
        pv_variable_per_mwh=3,          # $3/MWh
        bess_fixed_per_kw_year=20,      # $20/kW/年
        bess_variable_per_mwh=5,        # $5/MWh
        escalation_rate=0.02            # 年通胀 2%
    ),

    # ── 收入 ──
    # 混合调度模式：光伏优先充储能，多余才上网
    # V0.3: NSW solar PPA $45-65/MWh, LGC $32-42, FCAS hybrid $15-25/kW
    revenue=RevenueInput(
        ppa_price_aud_mwh=0,            # 无 PPA
        ppa_percentage=0.0,
        merchant_price_aud_mwh=75,      # 光伏直上网现货价（均价参考）
        solar_capture_price_aud_mwh=50, # 光伏午间捕获价（鸭曲线效应，低于均价）
        lgc_price_aud=37,               # LGC $37/证书
        lgc_rate_per_mwh=1.0,           # 1 证书/MWh
        fcas_revenue_aud_kw_year=20,    # FCAS $20/kW/年 (混合储能, V0.3: hybrid $15-25)
        revenue_escalation=0.0,
        bess_charge_price_aud_mwh=30,   # 储能从电网充电 $30/MWh（夜间低谷）
        bess_discharge_price_aud_mwh=110  # 储能放电压 $110/MWh（黄昏高峰）
    ),

    # ── 融资（全投资口径）──
    financing=FinancingInput(
        gearing_pct=0.0,                # 0% 杠杆 = 全投资 IRR
        interest_rate_pa=0.0,
        debt_tenor_years=0,
        dsra_months=0,
        financing_fees_pct=0.0,
        arrangement_fee_pct=0.0
    ),

    # ── 税务 ──
    tax=TaxInput(
        corporate_tax_rate=0.30,        # 30%
        depreciation_method="SL",       # 直线法
        pv_effective_life_years=20,     # ATO 光伏 20 年
        bess_effective_life_years=15,   # ATO 储能 15 年
        inverter_effective_life_years=10,
        civil_works_life_years=40
    ),

    # ── 中期大修 ──
    mid_life=MidLifeInput(
        battery_replace_year=12,        # 第 12 年电池增容
        battery_replace_cost_pct=0.30,  # LFP增容 30% (V0.3: LFP 20-35%, typical 30%)
        inverter_replace_year=15,       # 第 15 年逆变器更换
        inverter_replace_cost_pct=0.12  # 初始光伏 CAPEX 的 12%
    ),

    # ── 发电量 profile ──
    generation=GenerationProfile(
        pv_cf_monthly=[0.20, 0.19, 0.20, 0.21, 0.22, 0.23,
                       0.22, 0.21, 0.20, 0.19, 0.18, 0.17],  # NSW New England
        bess_cycles_per_day=1.0
    )
)

# ═══════════════════════════════════════════════════════════════════════
# 运行
# ═══════════════════════════════════════════════════════════════════════

manager = ScenarioManager()
manager.add_scenario("Oxley Solar + BESS", project)
results = manager.run_all()

result = results["Oxley Solar + BESS"]
km = result["key_metrics"]
annual = result.get("annual_data", {})
funding = result.get("funding_structure", {})

print("=" * 65)
print("  Oxley Solar Farm — 光储混合项目 全投资 IRR 测算")
print("=" * 65)

print(f"\n📋 项目概览")
print(f"  光伏:              215 MWp")
print(f"  储能:              215 MW / 6hr (1,290 MWh)")
print(f"  建设总成本:        ${funding.get('total_sources_k', 0):,.0f}k AUD")
print(f"  运营年限:          30 年")
print(f"\n⚡ 混合调度模式")
print(f"  光伏午间捕获价:    $50/MWh  (鸭曲线效应)")
print(f"  储能放电压:        $110/MWh (黄昏高峰)")
print(f"  电网充电价:        $30/MWh  (夜间低谷)")
print(f"  调度决策:          光伏优先充储能 ($110×0.90=$99 > $50+$37=$87)")
print(f"                     不足部分从电网$30充电 (价差$110-$33=$77)")

print(f"\n📊 核心指标")
print(f"  项目 IRR（税后）:   {km.get('project_irr_post_tax', 0)*100:.2f}%")
print(f"  股权 IRR（税后）:   {km.get('equity_irr', 0)*100:.2f}%  (gearing={funding.get('gearing_pct',0)*100:.0f}%)")
print(f"  项目 NPV@6%:       ${km.get('project_npv_post_tax_6pct', 0):,.0f}k")
print(f"  股权 NPV@8%:       ${km.get('equity_npv_8pct', 0):,.0f}k")
print(f"\n📊 度电成本（LCOE/LCOS）")
print(f"  光伏 LCOE（无贴现）:         ${km.get('lcoe_aud_mwh', 0):.0f}/MWh")
print(f"  光伏 LCOE（贴现@6%）:        ${km.get('lcoe_discounted_aud_mwh', 0):.0f}/MWh  ← AEMO/CSIRO 标准")
print(f"  储能 LCOS（无贴现）:         ${km.get('lcos_aud_mwh', 0):.0f}/MWh")
print(f"  储能 LCOS（贴现@6%）:        ${km.get('lcos_discounted_aud_mwh', 0):.0f}/MWh  ← AEMO/CSIRO 标准")
print(f"  混合 LCOE（贴现@6%）:        ${km.get('blended_discounted_aud_mwh', 0):.0f}/MWh")

# LCOE/LCOS 成本拆分明细
breakdown = result.get("lcoe_lcos_breakdown", {})
if breakdown:
    pv_cb = breakdown.get("pv_cost_breakdown", {})
    bess_cb = breakdown.get("bess_cost_breakdown", {})
    print(f"\n📊 LCOE/LCOS 成本构成")
    print(f"  ┌─ 光伏 ─────────────────────────────")
    print(f"  │  CAPEX:       ${pv_cb.get('capex_k', 0):,.0f}k")
    print(f"  │  OPEX:        ${pv_cb.get('opex_k', 0):,.0f}k")
    print(f"  │  维护CAPEX:   ${pv_cb.get('maint_k', 0):,.0f}k")
    print(f"  │  总成本:      ${pv_cb.get('total_k', 0):,.0f}k")
    print(f"  │  ÷ 光伏发电:  {pv_cb.get('pv_gen_mwh', 0):,.0f} MWh")
    print(f"  │  = LCOE:      ${km.get('lcoe_aud_mwh', 0):.0f}/MWh")
    print(f"  └────────────────────────────────────")
    print(f"  ┌─ 储能 ─────────────────────────────")
    print(f"  │  CAPEX:       ${bess_cb.get('capex_k', 0):,.0f}k")
    print(f"  │  OPEX:        ${bess_cb.get('opex_k', 0):,.0f}k")
    print(f"  │  维护CAPEX:   ${bess_cb.get('maint_k', 0):,.0f}k")
    print(f"  │  充电成本:    ${bess_cb.get('charge_cost_k', 0):,.0f}k  ← BESS 独有")
    print(f"  │  总成本:      ${bess_cb.get('total_k', 0):,.0f}k")
    print(f"  │  ÷ 放电量:    {bess_cb.get('throughput_mwh', 0):,.0f} MWh")
    print(f"  │  = LCOS:      ${km.get('lcos_aud_mwh', 0):.0f}/MWh")
    print(f"  └────────────────────────────────────")

# 年度营收摘要
rev_list = annual.get("revenue", [])
opex_list = annual.get("opex", [])
ebitda_list = annual.get("ebitda", [])
tax_list = annual.get("tax", [])
years = annual.get("financial_years", [])

# 找到第一个运营年份
op_start_idx = 0
for i, r in enumerate(rev_list):
    if r > 0:
        op_start_idx = i
        break

print(f"\n📈 财务摘要（运营首年 FY{years[op_start_idx] if op_start_idx < len(years) else '?'})")
if op_start_idx < len(rev_list):
    print(f"  年收入:            ${rev_list[op_start_idx]:,.0f}k")
    print(f"  年 OPEX:           ${opex_list[op_start_idx]:,.0f}k")
    print(f"  年 EBITDA:         ${ebitda_list[op_start_idx]:,.0f}k")
    if ebitda_list[op_start_idx] > 0 and rev_list[op_start_idx] > 0:
        print(f"  EBITDA 利润率:     {ebitda_list[op_start_idx]/rev_list[op_start_idx]*100:.1f}%")
    print(f"  年所得税:          ${tax_list[op_start_idx]:,.0f}k" if tax_list and op_start_idx < len(tax_list) else "")

# 全周期年均值
op_revs = [r for r in rev_list if r > 0]
op_ebitdas = [e for e, r in zip(ebitda_list, rev_list) if r > 0]
if op_revs:
    print(f"\n  年均收入（运营期）: ${sum(op_revs)/len(op_revs):,.0f}k")
    print(f"  年均 EBITDA:       ${sum(op_ebitdas)/len(op_ebitdas):,.0f}k")
    print(f"  EBITDA/总投资:     {sum(op_ebitdas)/len(op_ebitdas)/funding.get('total_sources_k',1)*100:.1f}%")

# 保存 JSON 结果
output_path = os.path.join(os.path.dirname(__file__), "..", "OUTPUT", "oxley_analysis.json")
import json
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)

print(f"\n{'='*65}")
print(f"  结果已保存至: {output_path}")
print(f"{'='*65}")
