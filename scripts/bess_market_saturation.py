#!/usr/bin/env python3
"""
NEM BESS 市场饱和与价差压缩模型
================================
分析当大量纯储能项目上线后，充放电价差如何被压缩，
以及何时达到市场均衡（新BESS IRR ≈ 资本成本）。

方法论:
  1. 从V0.3价格分布推导当前价差窗口
  2. 建模BESS渗透率对充电价/放电压的边际影响
  3. 在不同渗透率下重跑Gullen BESS IRR
  4. 找到IRR→8%的均衡点
  5. 基于AEMO管道增速估算时间线
"""
import sys, os, json, copy, math
sys.path.insert(0, os.path.dirname(__file__))

from solar_financial_engine import (
    ProjectInput, TimelineInput, TechnologyInput, CapexInput,
    OpexInput, RevenueInput, FinancingInput, TaxInput,
    MidLifeInput, GenerationProfile, ScenarioManager
)

# ═══════════════════════════════════════════════════════════════
# 1. 市场基础数据 (V0.3)
# ═══════════════════════════════════════════════════════════════

# NEM 基础参数
NEM_AVG_DEMAND_GW = 25          # NEM 平均负荷 ~25 GW
NEM_DAILY_ENERGY_GWH = 500      # ~25GW × 20h 有效时段

# 当前BESS (运营+在建, 估计)
BESS_OPERATIONAL_GW = 5.0       # 估计当前运营约5GW
BESS_PIPELINE_GW = 33.2         # AEMO管道 (不一定全建)
BESS_REALISTIC_BUILDOUT_GW = 20 # 实际可能建成 (考虑40%砍掉+其他障碍)

# 价差窗口 (V0.3 价格分布)
TOP_PRICE_PCT = 0.167           # 放电窗口: 最贵16.7% (4hr/24hr)
BOTTOM_PRICE_PCT = 0.167        # 充电窗口: 最便宜16.7%
TOP_WINDOW_ENERGY_GWH = NEM_DAILY_ENERGY_GWH * TOP_PRICE_PCT    # ~83 GWh/天
BOTTOM_WINDOW_ENERGY_GWH = NEM_DAILY_ENERGY_GWH * BOTTOM_PRICE_PCT

# 当前价差基准 (V0.3 dual_optimized)
BASE_CHARGE_PRICE = -15         # $/MWh
BASE_DISCHARGE_PRICE = 175      # $/MWh
BASE_SPREAD = BASE_DISCHARGE_PRICE - BASE_CHARGE_PRICE  # $190

# BESS参数
BESS_DURATION_HR = 4
BESS_RTE = 0.90
BESS_CYCLES_PER_DAY = 1.0

print("=" * 80)
print("  NEM BESS 市场饱和与价差压缩分析")
print("=" * 80)

print(f"""
📊 市场基础数据 (V0.3):
  NEM日均电量:       {NEM_DAILY_ENERGY_GWH} GWh
  放电窗口 (最贵{TOP_PRICE_PCT*100:.0f}%):   {TOP_WINDOW_ENERGY_GWH:.0f} GWh/天
  充电窗口 (最便宜{BOTTOM_PRICE_PCT*100:.0f}%): {BOTTOM_WINDOW_ENERGY_GWH:.0f} GWh/天
  当前运营BESS:      ~{BESS_OPERATIONAL_GW} GW
  AEMO管道BESS:      {BESS_PIPELINE_GW} GW (预计建成~{BESS_REALISTIC_BUILDOUT_GW} GW)
  当前基准价差:      ${BASE_SPREAD}/MWh
""")

# ═══════════════════════════════════════════════════════════════
# 2. 价差压缩模型
# ═══════════════════════════════════════════════════════════════

def bess_daily_throughput_gwh(bess_gw):
    """BESS日吞吐量 (GWh)"""
    return bess_gw * BESS_DURATION_HR * BESS_CYCLES_PER_DAY

def calc_spread_compression(bess_gw, method="logistic"):
    """
    计算给定BESS容量下的价差压缩

    method='logistic': spread = spread_min + (spread_max-spread_min)/(1 + (bess/bess_half)^steepness)
      经济直觉: 少量BESS影响小, 接近窗口容量时加速压缩, 超过窗口容量后趋于最低价差

    method='linear_window': 线性压缩, 到窗口容量时归零
    """
    daily_throughput = bess_daily_throughput_gwh(bess_gw)
    window_energy = BOTTOM_WINDOW_ENERGY_GWH  # 充电窗口容量即瓶颈

    # BESS渗透率 = BESS日吞吐 / 窗口容量
    penetration = daily_throughput / window_energy

    # 最低价差: 即使BESS完全饱和, 仍有一些价差 (效率损失+运维成本+风险溢价)
    SPREAD_MIN = 20  # $/MWh 最低价差

    if method == "logistic":
        # Sigmoid压缩: 在penetration=1.0时价差压缩约73%
        bess_half = 0.6  # 渗透率在60%时价差压到一半
        steepness = 3.0
        compression = 1.0 / (1.0 + (penetration / bess_half) ** steepness)
        spread = SPREAD_MIN + (BASE_SPREAD - SPREAD_MIN) * compression

    elif method == "linear":
        # 简单线性: penetration=0→spread max, penetration=1→spread min
        if penetration >= 1.0:
            spread = SPREAD_MIN
        else:
            spread = BASE_SPREAD - (BASE_SPREAD - SPREAD_MIN) * penetration

    return spread, penetration

# 将价差分解回充放电价格
def spread_to_prices(spread, strategy="dual"):
    """
    将压缩后的价差分解为充放电价格
    假设: 充放电价格的移动对称 (各承担一半价差压缩)
    充电价从基准上升, 放电压从基准下降
    """
    spread_loss = BASE_SPREAD - spread
    half_loss = spread_loss / 2

    if strategy == "dual":
        charge = BASE_CHARGE_PRICE + half_loss   # 变得更贵(负得少)
        discharge = BASE_DISCHARGE_PRICE - half_loss  # 变得更便宜
    elif strategy == "simple":
        charge = 25 + half_loss
        discharge = 120 - half_loss
    elif strategy == "neg60":
        charge = -12.5 + half_loss
        discharge = 170 - half_loss

    return charge, discharge

print("─" * 80)
print(f"{'BESS GW':<10} {'日吞吐GWh':<12} {'渗透率%':<10} {'价差$/MWh':<12} {'充电$/MWh':<12} {'放电$/MWh':<12}")
print("─" * 80)

for bess_gw in [0, 2.5, 5, 7.5, 10, 15, 20, 25, 30, 40]:
    spread, pen = calc_spread_compression(bess_gw, "logistic")
    charge, discharge = spread_to_prices(spread, "dual")
    throughput = bess_daily_throughput_gwh(bess_gw)
    print(f"{bess_gw:<10.1f} {throughput:<12.0f} {pen*100:<9.1f}% "
          f"${spread:<11.0f} ${charge:<11.0f} ${discharge:<11.0f}")

# ═══════════════════════════════════════════════════════════════
# 3. IRR 对各渗透率的敏感性 (跑 Gullen BESS 模型)
# ═══════════════════════════════════════════════════════════════

print(f"\n{'='*80}")
print(f"  在不同渗透率下重跑 Gullen BESS IRR")
print(f"{'='*80}")

def build_gullen_at_spread(spread, fcas=40):
    """构建给定价差下的Gullen BESS项目"""
    charge, discharge = spread_to_prices(spread, "dual")
    return ProjectInput(
        name="Gullen Range BESS",
        location="NSW, Australia (Goulburn)",
        currency="AUD",
        scenario_name=f"Spread ${spread:.0f}",
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
        tax=TaxInput(corporate_tax_rate=0.30, depreciation_method="SL",
                     pv_effective_life_years=20, bess_effective_life_years=15,
                     inverter_effective_life_years=10, civil_works_life_years=40),
        mid_life=MidLifeInput(battery_replace_year=12, battery_replace_cost_pct=0.30),
        generation=GenerationProfile(pv_cf_monthly=[], bess_cycles_per_day=1.0)
    )

# 在多个BESS容量点重跑
print(f"\n{'BESS GW':<10} {'渗透率%':<10} {'价差$/MWh':<12} {'IRR%':<8} {'NPV@6% k$':<14}")
print("─" * 70)

results = []
for bess_gw in [5, 7.5, 10, 12.5, 15, 17.5, 20, 25, 30]:
    spread, pen = calc_spread_compression(bess_gw, "logistic")
    proj = build_gullen_at_spread(spread, fcas=40)

    mgr = ScenarioManager()
    mgr.add_scenario("test", proj)
    r = mgr.run_all()["test"]
    irr = r["key_metrics"]["project_irr_post_tax"]
    npv = r["key_metrics"]["project_npv_post_tax_6pct"]

    results.append((bess_gw, pen, spread, irr, npv))
    print(f"{bess_gw:<10.1f} {pen*100:<9.1f}% ${spread:<11.0f} {irr*100:<7.2f}% ${npv:>12,.0f}")

# ═══════════════════════════════════════════════════════════════
# 4. 找均衡点 (IRR → 8%)
# ═══════════════════════════════════════════════════════════════

print(f"\n{'='*80}")
print(f"  市场均衡分析")
print(f"{'='*80}")

TARGET_IRR = 0.08  # 8% WACC

# 线性插值找IRR=8%的BESS容量
for i in range(len(results)-1):
    gw1, pen1, sp1, irr1, _ = results[i]
    gw2, pen2, sp2, irr2, _ = results[i+1]
    if irr1 >= TARGET_IRR >= irr2 or irr2 >= TARGET_IRR >= irr1:
        # 线性插值
        frac = (TARGET_IRR - irr1) / (irr2 - irr1) if irr2 != irr1 else 0
        eq_gw = gw1 + frac * (gw2 - gw1)
        eq_pen = pen1 + frac * (pen2 - pen1)
        eq_spread = sp1 + frac * (sp2 - sp1)
        break

print(f"""
🔑 市场均衡点 (新BESS IRR → 8%):
  ─────────────────────────────────────
  BESS 总装机:       {eq_gw:.1f} GW
  渗透率:            {eq_pen*100:.1f}% (vs 充电窗口容量)
  均衡价差:          ${eq_spread:.0f}/MWh
  均衡充电价:        ${spread_to_prices(eq_spread, 'dual')[0]:.0f}/MWh
  均衡放电压:        ${spread_to_prices(eq_spread, 'dual')[1]:.0f}/MWh
""")

# ═══════════════════════════════════════════════════════════════
# 5. 时间线估算
# ═══════════════════════════════════════════════════════════════

print(f"{'='*80}")
print(f"  达到均衡的时间线估算")
print(f"{'='*80}")

CURRENT_BESS_GW = 5.0
EQ_BESS_GW = eq_gw
GAP_GW = EQ_BESS_GW - CURRENT_BESS_GW

# AEMO管道增速: Q1 2025→Q1 2026 = 50.5→67.3 GW (+33%), 电池 20.5→33.2 GW (+62%)
# 但实际建成速度慢于管道增速。假设实际建成率:
ANNUAL_BUILD_RATE_GW = 3.0    # 保守: 3 GW/年
ANNUAL_BUILD_FAST_GW = 5.0    # 乐观: 5 GW/年

years_conservative = GAP_GW / ANNUAL_BUILD_RATE_GW
years_optimistic = GAP_GW / ANNUAL_BUILD_FAST_GW

# 注意: 需求也在增长 (28% by 2035), 窗口容量会扩大
# 但煤电退役(11GW)会减少低价时段供应 → 窗口容量缩小
# 净效应: 暂按需求增长与煤电退役对冲, 窗口容量基本不变

print(f"""
  当前BESS运营:      ~{CURRENT_BESS_GW} GW
  均衡BESS容量:      ~{EQ_BESS_GW:.1f} GW
  待建设容量:        ~{GAP_GW:.1f} GW
  ─────────────────────────────────────
  保守建速 (3 GW/年):   {2026 + years_conservative:.0f}年 ({years_conservative:.1f}年后)
  乐观建速 (5 GW/年):   {2026 + years_optimistic:.0f}年 ({years_optimistic:.1f}年后)
""")

# 也考虑需求增长缓冲
DEMAND_GROWTH_BUFFER_YEARS = 3  # 需求增长28%使窗口扩大~28%，延缓饱和
print(f"""
  ⚠️ 缓冲因素:
  - NEM需求增长28%至2035 → 充放电窗口扩大 → 均衡点推迟 ~{DEMAND_GROWTH_BUFFER_YEARS}年
  - 煤电退役11GW → 低价供应减少 → 充电窗口可能缩小 → 均衡提前
  - 6hr BESS增加 → 同等GW下日吞吐更大 → 加速饱和
  - AI数据中心需求 → 基荷增加 → 改变价差结构(全天紧张)
  
  📅 综合估计: 市场均衡在 2030-2035 年之间达到
""")

# ═══════════════════════════════════════════════════════════════
# 6. 对现有项目的影响
# ═══════════════════════════════════════════════════════════════

print(f"{'='*80}")
print(f"  对 Oxley 和 Gullen 项目的启示")
print(f"{'='*80}")

# 在均衡价差下重跑Oxley
eq_charge, eq_discharge = spread_to_prices(eq_spread, "dual")

# Gullen at equilibrium
proj_gullen_eq = build_gullen_at_spread(eq_spread, fcas=40)
mgr = ScenarioManager()
mgr.add_scenario("eq", proj_gullen_eq)
r = mgr.run_all()["eq"]
gullen_eq_irr = r["key_metrics"]["project_irr_post_tax"]

print(f"""
  Gullen Range (纯储能):
    当前IRR:     15.55% (价差 $190/MWh)
    均衡时IRR:   {gullen_eq_irr*100:.2f}% (价差 ${eq_spread:.0f}/MWh)
    ─────────────────────────────────────
    建议: 尽早投建以锁定早期高IRR。均衡后新项目IRR降至~{gullen_eq_irr*100:.1f}%。
  
  ⚡ 先行者优势: 前5年投建的项目IRR远超均衡水平。
  ⚠️ 5年后投建的项目面临显著价差压缩风险。
""")

# ═══════════════════════════════════════════════════════════════
outpath = os.path.join(os.path.dirname(__file__), "..", "OUTPUT", "bess_market_saturation.json")
json.dump({
    "equilibrium": {"bess_gw": eq_gw, "penetration_pct": eq_pen*100, "spread": eq_spread,
                    "charge_price": eq_charge, "discharge_price": eq_discharge,
                    "years_to_equilibrium_conservative": years_conservative,
                    "years_to_equilibrium_optimistic": years_optimistic},
    "results": [{"bess_gw": gw, "penetration": pen, "spread": sp, "irr": irr, "npv": npv}
                for gw, pen, sp, irr, npv in results]
}, open(outpath, "w"), indent=2)
print(f"详细结果已保存至: {outpath}")
