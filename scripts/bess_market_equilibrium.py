#!/usr/bin/env python3
"""
NEM BESS 市场均衡模块
=====================
基于 AEMO ISP 2024 Step Change + 政策钟摆模型。
为太阳能财务引擎提供时间维度的市场参数调整。

核心理念:
  政府不会允许电力市场崩溃。BESS 回报率在政策区间(8-18% IRR)内摆动。
  新建项目应根据其 COD 年份自动调整收入参数，反映届时市场均衡状态。

数据来源:
  - AEMO 2024 Integrated System Plan (ISP) Step Change scenario
  - AEMO Connections Scorecard Q1 2026
  - data/market_reference_au.yaml V0.3

用法:
  from bess_market_equilibrium import MarketEquilibrium
  
  eq = MarketEquilibrium()
  adjusted = eq.adjust_revenue(cod_year=2029, charge_price=-15, discharge_price=175, fcas=40)
  # adjusted = {"charge": -5, "discharge": 160, "fcas": 40, "spread_equilibrium": 165, ...}
"""

import math
from dataclasses import dataclass, field
from typing import Optional, Dict, Tuple

# ═══════════════════════════════════════════════════════════════
# ISP 2024 Step Change 基准数据
# ═══════════════════════════════════════════════════════════════

# 煤电容量路径 (GW)
COAL_TIMELINE = {
    2026: 21, 2027: 19, 2028: 17, 2029: 15, 2030: 13,
    2031: 11, 2032: 9,  2033: 7,  2034: 5,  2035: 3,
    2036: 2,  2037: 1,  2038: 0.5, 2039: 0,  2040: 0,
}

# ISP Step Change: 储能目标 (ODP)
STORAGE_TARGET_GW_2050 = 49
STORAGE_TARGET_GWH_2050 = 646
CURRENT_STORAGE_GW = 5.0

# ISP: 年新建容量 (所有类型)
ANNUAL_BUILD_ALL_GW = {
    (2026, 2030): 6.0,
    (2031, 2040): 3.0,
    (2041, 2050): 2.0,
}

# 储能占新建容量的比例 (ISP隐含 ~30-40%)
STORAGE_SHARE_OF_NEW_BUILD = 0.35

# ═══════════════════════════════════════════════════════════════
# 政策钟摆参数
# ═══════════════════════════════════════════════════════════════

POLICY_MIN_IRR = 0.08        # 政府保障的最低BESS回报
POLICY_MAX_IRR = 0.18        # 政治容忍上限
POLICY_SPREAD_FLOOR = 60     # $/MWh 绝对价差底线 (运维+效率损耗)
POLICY_SPREAD_CEILING = 250  # $/MWh 绝对价差上限 (政治压力)

# 需求增长年率 (ISP隐含: NEM需求+28% by 2035 → ~2.5%/年)
DEMAND_GROWTH_RATE = 0.025

# ═══════════════════════════════════════════════════════════════
# 价差→IRR 映射 (基于Gullen BESS基准模型预计算)
# ═══════════════════════════════════════════════════════════════

# 预计算: 给定BESS价差×FCAS组合 → 近似IRR
# 基于 Gullen Range 300MW/4hr BESS @ $900/kW CAPEX
SPREAD_TO_IRR_TABLE = {
    60:  0.025,
    80:  0.050,
    100: 0.069,
    120: 0.088,
    140: 0.106,
    160: 0.123,
    180: 0.140,
    200: 0.156,
    220: 0.171,
    240: 0.186,
}

def spread_to_approx_irr(spread: float) -> float:
    """价差→近似IRR (线性插值)"""
    spreads = sorted(SPREAD_TO_IRR_TABLE.keys())
    if spread <= spreads[0]:
        return SPREAD_TO_IRR_TABLE[spreads[0]]
    if spread >= spreads[-1]:
        return SPREAD_TO_IRR_TABLE[spreads[-1]]
    
    for i in range(len(spreads)-1):
        if spreads[i] <= spread <= spreads[i+1]:
            frac = (spread - spreads[i]) / (spreads[i+1] - spreads[i])
            return SPREAD_TO_IRR_TABLE[spreads[i]] + frac * (SPREAD_TO_IRR_TABLE[spreads[i+1]] - SPREAD_TO_IRR_TABLE[spreads[i]])
    return 0.08

def irr_to_required_spread(target_irr: float) -> float:
    """目标IRR→所需最低价差 (二分查找)"""
    lo, hi = 50, 300
    for _ in range(20):
        mid = (lo + hi) / 2
        if spread_to_approx_irr(mid) < target_irr:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2

# ═══════════════════════════════════════════════════════════════

@dataclass
class EquilibriumResult:
    """市场均衡分析结果"""
    cod_year: int
    projected_bess_gw: float
    projected_coal_gw: float
    equilibrium_spread: float
    equilibrium_charge: float
    equilibrium_discharge: float
    equilibrium_irr: float
    market_phase: str          # "early_adopter" | "transition" | "mature"
    policy_assessment: str     # 政策评估
    source: str = "AEMO ISP 2024 Step Change + Policy Pendulum V3"


class MarketEquilibrium:
    """
    NEM BESS 市场均衡分析器
    
    根据项目COD年份，预测届时BESS市场渗透率，
    计算政策钟摆下的均衡充放电价格。
    """
    
    def __init__(self, 
                 policy_floor_irr: float = POLICY_MIN_IRR,
                 policy_ceiling_irr: float = POLICY_MAX_IRR,
                 storage_share_new_build: float = STORAGE_SHARE_OF_NEW_BUILD):
        self.policy_floor_irr = policy_floor_irr
        self.policy_ceiling_irr = policy_ceiling_irr
        self.storage_share = storage_share_new_build
    
    def project_bess_capacity(self, year: int) -> float:
        """
        基于ISP路径投影给定年份的BESS总装机
        
        ISP路径: 5GW (2026) → 49GW (2050)
        线性内插 + 建设加速因子
        """
        if year <= 2026:
            return CURRENT_STORAGE_GW
        
        # ISP隐含的储能年增速
        years_to_2050 = max(1, 2050 - 2026)
        annual_growth = (STORAGE_TARGET_GW_2050 - CURRENT_STORAGE_GW) / years_to_2050
        
        # 前几年建设加速 (管道已就绪)
        if year <= 2030:
            acceleration = 1.3  # 近期加速因子
        elif year <= 2035:
            acceleration = 1.0
        else:
            acceleration = 0.9  # 远期减速 (接近饱和)
        
        bess = CURRENT_STORAGE_GW + annual_growth * (year - 2026) * acceleration
        return min(bess, STORAGE_TARGET_GW_2050)
    
    def project_coal_capacity(self, year: int) -> float:
        """投影煤电容量"""
        if year in COAL_TIMELINE:
            return COAL_TIMELINE[year]
        # 线性插值
        years = sorted(COAL_TIMELINE.keys())
        if year <= years[0]:
            return COAL_TIMELINE[years[0]]
        if year >= years[-1]:
            return 0.0
        
        for i in range(len(years)-1):
            if years[i] <= year <= years[i+1]:
                frac = (year - years[i]) / (years[i+1] - years[i])
                return COAL_TIMELINE[years[i]] + frac * (COAL_TIMELINE[years[i+1]] - COAL_TIMELINE[years[i]])
        return 0.0
    
    def calc_equilibrium_spread(self, year: int) -> float:
        """
        计算给定年份的政策均衡价差
        
        逻辑:
        1. ISP路径决定BESS"应有"水平
        2. 如果当前价差产生的IRR > 政策地板 → 价差可以压缩
        3. 如果当前价差产生的IRR < 政策地板 → 必须扩大价差
        4. 均衡点: 价差 = 产生policy_floor_irr所需的最低spread
        
        时间演进:
        - 早期(2026-2029): 价差高于均衡 → 吸引建设 → 逐渐压缩
        - 过渡期(2030-2034): 接近均衡
        - 成熟期(2035+): 稳定在政策地板
        """
        required_spread = irr_to_required_spread(self.policy_floor_irr)
        
        # 当前市场价差 (基于V0.3 dual_optimized)
        current_spread = 190
        
        # 时间衰减: 价差从当前水平向均衡水平收敛
        # 收敛速度: 每年约15-20% (取决于建设速度)
        if year <= 2026:
            return current_spread
        
        years_from_now = year - 2026
        convergence_rate = 0.18  # 年收敛率
        
        # 指数衰减向均衡
        gap = current_spread - required_spread
        equilibrium = current_spread - gap * (1 - math.exp(-convergence_rate * years_from_now))
        
        # 不低于政策地板
        return max(equilibrium, required_spread)
    
    def calc_equilibrium_prices(self, year: int) -> Tuple[float, float, float]:
        """
        计算均衡充放电价格和价差
        
        Returns: (charge_price, discharge_price, spread)
        """
        eq_spread = self.calc_equilibrium_spread(year)
        
        # 当前基准
        base_charge = -15
        base_discharge = 175
        base_spread = base_discharge - base_charge
        
        # 价差压缩：对称分配
        spread_loss = base_spread - eq_spread
        eq_charge = base_charge + spread_loss / 2
        eq_discharge = base_discharge - spread_loss / 2
        
        return eq_charge, eq_discharge, eq_spread
    
    def adjust_revenue(self, cod_year: int, 
                       charge_price: float, discharge_price: float,
                       fcas: float = 40,
                       base_year: int = 2026) -> Dict:
        """
        根据COD年份调整收入参数
        
        Args:
            cod_year: 商业运营年份
            charge_price: 用户输入的充电价 (基准年)
            discharge_price: 用户输入的放电压 (基准年)
            fcas: FCAS ($/kW/年)
            base_year: 基准年份 (默认2026)
        
        Returns:
            调整后的参数字典
        """
        # 投影BESS和煤电
        bess_gw = self.project_bess_capacity(cod_year)
        coal_gw = self.project_coal_capacity(cod_year)
        
        # 均衡价格
        eq_charge, eq_discharge, eq_spread = self.calc_equilibrium_prices(cod_year)
        
        # 用户输入价差
        user_spread = discharge_price - charge_price
        
        # 缩放因子: 如果用户输入与基准不同，按比例调整
        if base_year == 2026:
            base_spread = 190  # V0.3 dual optimized baseline
        else:
            base_spread = self.calc_equilibrium_spread(base_year)
        
        scale = user_spread / base_spread if base_spread > 0 else 1.0
        
        adjusted_charge = eq_charge * scale
        adjusted_discharge = eq_discharge * scale
        adjusted_spread = adjusted_discharge - adjusted_charge
        
        # IRR估算
        approx_irr = spread_to_approx_irr(adjusted_spread)
        
        # 市场阶段
        if cod_year <= 2029:
            phase = "early_adopter"
        elif cod_year <= 2034:
            phase = "transition"
        else:
            phase = "mature"
        
        # 政策评估
        if approx_irr < self.policy_floor_irr:
            assessment = f"⚠️ IRR {approx_irr*100:.1f}% 低于政策地板 {self.policy_floor_irr*100:.0f}% — 政府需提供额外收益保障"
        elif approx_irr > self.policy_ceiling_irr:
            assessment = f"⚠️ IRR {approx_irr*100:.1f}% 高于政治容忍上限 {self.policy_ceiling_irr*100:.0f}% — 可能面临政策压制"
        else:
            assessment = f"✅ IRR {approx_irr*100:.1f}% 在政策区间 [{self.policy_floor_irr*100:.0f}%-{self.policy_ceiling_irr*100:.0f}%] 内"
        
        return {
            "cod_year": cod_year,
            "base_year": base_year,
            "projected_bess_gw": round(bess_gw, 1),
            "projected_coal_gw": round(coal_gw, 1),
            "original_charge": charge_price,
            "original_discharge": discharge_price,
            "original_spread": user_spread,
            "equilibrium_charge": round(adjusted_charge, 1),
            "equilibrium_discharge": round(adjusted_discharge, 1),
            "equilibrium_spread": round(adjusted_spread, 1),
            "equilibrium_irr": round(approx_irr, 4),
            "fcas": fcas,
            "market_phase": phase,
            "policy_assessment": assessment,
            "source": "AEMO ISP 2024 Step Change + Policy Pendulum V3"
        }
    
    def print_report(self, cod_year: int, charge: float, discharge: float, fcas: float = 40):
        """打印市场均衡报告"""
        r = self.adjust_revenue(cod_year, charge, discharge, fcas)
        
        print(f"""
╔══════════════════════════════════════════════════════════════╗
║           NEM BESS 市场均衡分析 — COD {cod_year}                        ║
╠══════════════════════════════════════════════════════════════╣
║  数据来源: {r['source']}                   ║
╠══════════════════════════════════════════════════════════════╣
║  届时BESS装机:   {r['projected_bess_gw']:>6.1f} GW          煤电剩余: {r['projected_coal_gw']:>6.1f} GW  ║
║  市场阶段:       {r['market_phase']:<20}                          ║
╠══════════════════════════════════════════════════════════════╣
║                   基准年({r['base_year']})    均衡年({cod_year})      调整      ║
║  充电价 ($/MWh)   {r['original_charge']:>+8.1f}       {r['equilibrium_charge']:>+8.1f}       —        ║
║  放电压 ($/MWh)   {r['original_discharge']:>8.1f}       {r['equilibrium_discharge']:>8.1f}       —        ║
║  价差   ($/MWh)   {r['original_spread']:>8.0f}        {r['equilibrium_spread']:>8.0f}       —        ║
║  FCAS   ($/kW)   {r['fcas']:>8.0f}        {r['fcas']:>8.0f}       —        ║
╠══════════════════════════════════════════════════════════════╣
║  均衡IRR:        {r['equilibrium_irr']*100:>5.1f}%                                    ║
║  政策评估:       {r['policy_assessment']}                                    ║
╚══════════════════════════════════════════════════════════════╝
""")


# ═══════════════════════════════════════════════════════════════
# 命令行入口
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    eq = MarketEquilibrium()
    
    print("=" * 70)
    print("  NEM BESS 市场均衡 — ISP路径 + 政策钟摆")
    print("=" * 70)
    
    # 展示各COD年份的均衡参数
    print(f"\n{'COD年份':<10} {'BESS GW':<10} {'煤电GW':<8} {'均衡充电$':<12} {'均衡放电$':<12} {'均衡价差$':<10} {'≈IRR%':<8} {'阶段':<15}")
    print("-" * 80)
    
    for year in [2026, 2027, 2028, 2029, 2030, 2032, 2035, 2040]:
        r = eq.adjust_revenue(year, -15, 175, 40)
        print(f"{year:<10} {r['projected_bess_gw']:<10.1f} {r['projected_coal_gw']:<8.0f} "
              f"${r['equilibrium_charge']:>+10.0f} ${r['equilibrium_discharge']:>10.0f} "
              f"${r['equilibrium_spread']:>8.0f} {r['equilibrium_irr']*100:>6.1f}% {r['market_phase']:<15}")
    
    # 详细报告
    eq.print_report(2029, -15, 175, 40)
    eq.print_report(2035, -15, 175, 40)
