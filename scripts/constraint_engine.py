#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  constraint_engine.py — 外部条件约束求解引擎                               ║
║                                                                              ║
║  职责：                                                                      ║
║  1. 读取 constraints/australia_nem_trajectory.yaml 中的官方轨迹数据         ║
║  2. 根据评估年份自动插值推演NEM市场状态                                    ║
║  3. 基于市场状态和压缩模型，推演项目财务参数的"约束值"                     ║
║  4. 输出 config 覆盖值，供 run_with_constraints.py 注入财务引擎             ║
║                                                                              ║
║  核心逻辑：                                                                  ║
║    - 时间轴推演：根据ISP/AER轨迹数据，线性插值到指定年份                    ║
║    - 价差压缩：BESS渗透率 → 套利价差收窄 → 加权电价下降                    ║
║    - 学习曲线：累计装机翻倍 → CAPEX按学习率下降                            ║
║    - 接入成本：年化涨幅 + AI需求溢价                                        ║
║    - FCAS衰减：BESS竞争 → FCAS收益下降                                      ║
║    - 融资调整：宏观利率 + 项目风险溢价                                      ║
║                                                                              ║
║  用法：                                                                      ║
║      from scripts.constraint_engine import ConstraintEngine                  ║
║      engine = ConstraintEngine("constraints/australia_nem_trajectory.yaml")  ║
║      overrides = engine.solve(year=2030, region="NSW")                       ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os
import sys
import math
from pathlib import Path


class ConstraintEngine:
    """
    外部条件约束求解引擎。

    读取NEM发展轨迹数据，根据评估年份和区域，
    自动推演项目财务参数的约束值。
    """

    def __init__(self, constraint_file=None):
        """
        初始化约束引擎。

        参数：
            constraint_file (str): 约束数据文件路径。
                                   None 时自动查找默认路径。
        """
        self.constraint_file = constraint_file or self._find_default_file()
        self.data = self._load_data()

    def _find_default_file(self):
        """查找默认的约束数据文件"""
        # 从脚本所在目录向上查找
        script_dir = Path(__file__).resolve().parent.parent
        candidates = [
            script_dir / "constraints" / "australia_nem_trajectory.yaml",
            Path("constraints/australia_nem_trajectory.yaml"),
        ]
        for path in candidates:
            if path.exists():
                return str(path)
        return str(candidates[0])

    def _load_data(self):
        """加载约束数据文件"""
        import yaml
        path = Path(self.constraint_file)
        if not path.exists():
            print(f"⚠️ 约束数据文件不存在: {self.constraint_file}")
            print("   将使用默认参数（无约束调整）")
            return None
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def solve(self, year=None, region="NSW", manual_overrides=None):
        """
        求解指定年份和区域的约束参数。

        参数：
            year (int): 评估年份。None 表示使用基准年份（不推演）。
            region (str): NEM区域（NSW/VIC/QLD/SA）。
            manual_overrides (dict): 手动覆盖的约束变量。
                例如：{"bess_capacity_addition_gw": 10, "construction_cost_escalation_pct": 8}

        返回：
            dict: {
                "assessment_year": year,
                "region": region,
                "constraint_file": self.constraint_file,
                "market_state": {...},       # 推演的市场状态
                "overrides": {...},          # 需要注入 config 的参数覆盖值
                "constraint_details": {...}, # 各约束的详细推演过程
                "warnings": [...],           # 警告信息
            }
        """
        if self.data is None:
            return self._default_result(year, region)

        manual_overrides = manual_overrides or {}
        warnings = []

        # ── 步骤1: 推演市场状态 ──
        market_state = self._project_market_state(year, region, manual_overrides, warnings)

        # ── 步骤2: 计算价差压缩 → 加权电价 ──
        price_result = self._calculate_price(market_state, region, warnings)

        # ── 步骤3: 计算CAPEX学习曲线 ──
        capex_result = self._calculate_capex(market_state, region, warnings)

        # ── 步骤4: 计算接入成本 ──
        connection_result = self._calculate_connection_cost(market_state, warnings)

        # ── 步骤5: 计算FCAS衰减 ──
        fcas_result = self._calculate_fcas(market_state, warnings)

        # ── 步骤6: 计算融资条件调整 ──
        financing_result = self._calculate_financing(market_state, warnings)

        # ── 组装结果 ──
        overrides = {}
        overrides.update(price_result.get("overrides", {}))
        overrides.update(capex_result.get("overrides", {}))
        overrides.update(connection_result.get("overrides", {}))
        overrides.update(fcas_result.get("overrides", {}))
        overrides.update(financing_result.get("overrides", {}))

        return {
            "assessment_year": year,
            "region": region,
            "constraint_file": self.constraint_file,
            "market_state": market_state,
            "overrides": overrides,
            "constraint_details": {
                "price_constraint": price_result,
                "capex_constraint": capex_result,
                "connection_constraint": connection_result,
                "fcas_constraint": fcas_result,
                "financing_constraint": financing_result,
            },
            "warnings": warnings,
        }

    def _default_result(self, year, region):
        """当约束数据不可用时的默认结果"""
        return {
            "assessment_year": year,
            "region": region,
            "constraint_file": self.constraint_file,
            "market_state": None,
            "overrides": {},
            "constraint_details": {},
            "warnings": ["约束数据文件不可用，未应用任何约束调整"],
        }

    # ──────────────────────────────────────────────────────────
    # 步骤1: 市场状态推演
    # ──────────────────────────────────────────────────────────

    def _project_market_state(self, year, region, manual_overrides, warnings):
        """推演指定年份的NEM市场状态"""
        if year is None:
            return {"note": "未指定评估年份，使用基准参数"}

        trajectory = self.data.get("capacity_trajectory", {})
        milestones = trajectory.get("milestones", [])

        if not milestones:
            warnings.append("容量轨迹数据为空")
            return {}

        # 找到年份前后的里程碑
        sorted_milestones = sorted(milestones, key=lambda m: m["year"])
        before = None
        after = None
        for m in sorted_milestones:
            if m["year"] <= year:
                before = m
            if m["year"] >= year and after is None:
                after = m

        if before is None:
            before = sorted_milestones[0]
        if after is None:
            after = sorted_milestones[-1]

        # 线性插值
        if before["year"] == after["year"] or year <= before["year"]:
            interpolated = dict(before)
            interpolated["interpolation"] = "exact"
        elif year >= after["year"]:
            interpolated = dict(after)
            interpolated["interpolation"] = "exact"
        else:
            ratio = (year - before["year"]) / (after["year"] - before["year"])
            interpolated = {"year": year, "interpolation": "linear"}
            for key in before:
                if key in ("year", "label", "notes", "interpolation"):
                    continue
                if key in before and key in after:
                    b_val = before[key]
                    a_val = after[key]
                    if isinstance(b_val, (int, float)) and isinstance(a_val, (int, float)):
                        interpolated[key] = b_val + (a_val - b_val) * ratio
                    else:
                        interpolated[key] = b_val

        # 应用手动覆盖
        if "bess_capacity_addition_gw" in manual_overrides:
            # 用户手动指定BESS新增容量，覆盖推演值
            user_addition = manual_overrides["bess_capacity_addition_gw"]
            # 从基准年份（2025）的BESS容量开始
            base_bess = 3.5
            interpolated["bess_installed_gw"] = base_bess + user_addition
            warnings.append(f"手动覆盖: BESS新增容量 = {user_addition}GW (推演值被覆盖)")

        if "coal_retirement_gw" in manual_overrides:
            user_coal = manual_overrides["coal_retirement_gw"]
            base_coal = 20.5
            interpolated["coal_total_gw"] = base_coal - user_coal
            warnings.append(f"手动覆盖: 煤电退役 = {user_coal}GW (推演值被覆盖)")

        return interpolated

    # ──────────────────────────────────────────────────────────
    # 步骤2: 价差压缩 → 加权电价
    # ──────────────────────────────────────────────────────────

    def _calculate_price(self, market_state, region, warnings):
        """计算价差压缩后的加权电价"""
        spread_model = self.data.get("spread_compression_model", {})
        base = spread_model.get("base_spread", {})
        factors = spread_model.get("compression_factors", {})

        if not market_state or "year" not in market_state:
            return {
                "overrides": {},
                "note": "无市场状态数据，使用基准电价",
            }

        year = market_state.get("year", 2025)
        bess_gw = market_state.get("bess_installed_gw", 3.5)
        coal_gw = market_state.get("coal_total_gw", 20.5)

        # 计算BESS增量（相对2025基准）
        base_bess = 3.5
        bess_increment = max(0, bess_gw - base_bess)

        # 计算煤电退役量（相对2025基准）
        base_coal = 20.5
        coal_retired = max(0, base_coal - coal_gw)

        # 计算AI需求增量（简化：假设2030年达3GW，线性增长）
        ai_demand = max(0, (year - 2025) * 0.6) if year >= 2025 else 0

        # 价差压缩
        compression_per_gw = factors.get("compression_per_gw_bess", 8.0)
        coal_support_per_gw = factors.get("coal_retirement_support_per_gw", 5.0)
        ai_support_per_gw = factors.get("ai_demand_support_per_gw", 3.0)
        saturation_cap = factors.get("saturation_cap_pct", 0.55)

        # 总压缩量
        total_compression = (
            bess_increment * compression_per_gw
            - coal_retired * coal_support_per_gw
            - ai_demand * ai_support_per_gw
        )
        total_compression = max(0, total_compression)

        # 基准价差
        base_spread = base.get("gross_spread_aud_mwh", 195)
        base_price = base.get("weighted_avg_price_aud_kwh", 0.219)
        base_hours = base.get("effective_hours", 1028)

        # 压缩比例
        compression_ratio = total_compression / base_spread if base_spread > 0 else 0
        compression_ratio = min(compression_ratio, saturation_cap)

        # 压缩后的加权电价
        compressed_price = base_price * (1 - compression_ratio)

        # 等效小时数压缩
        hours_compression_per_gw = factors.get("hours_compression_per_gw_bess", 10.0)
        hours_reduction = bess_increment * hours_compression_per_gw
        compressed_hours = max(500, base_hours - hours_reduction)

        # 区域调整
        regional = self.data.get("regional_parameters", {}).get("regions", {}).get(region, {})
        if regional:
            # 根据区域基准充放电价调整
            regional_charge = regional.get("base_charge_price_aud_mwh", 25)
            regional_discharge = regional.get("base_discharge_price_aud_mwh", 170)
            base_charge = 25
            base_discharge = 170
            charge_ratio = regional_charge / base_charge if base_charge > 0 else 1.0
            discharge_ratio = regional_discharge / base_discharge if base_discharge > 0 else 1.0
            regional_factor = (charge_ratio + discharge_ratio) / 2
            compressed_price = compressed_price * regional_factor

        return {
            "overrides": {
                "revenue.ppa_price_per_kwh": round(compressed_price, 4),
                "revenue.equivalent_hours": round(compressed_hours, 0),
                "technical.equivalent_hours": round(compressed_hours, 0),
            },
            "details": {
                "assessment_year": year,
                "bess_installed_gw": bess_gw,
                "bess_increment_gw": bess_increment,
                "coal_retired_gw": coal_retired,
                "ai_demand_gw": ai_demand,
                "total_compression_aud_mwh": round(total_compression, 1),
                "compression_ratio_pct": round(compression_ratio * 100, 1),
                "base_price_aud_kwh": base_price,
                "compressed_price_aud_kwh": round(compressed_price, 4),
                "base_hours": base_hours,
                "compressed_hours": round(compressed_hours, 0),
            },
        }

    # ──────────────────────────────────────────────────────────
    # 步骤3: CAPEX学习曲线
    # ──────────────────────────────────────────────────────────

    def _calculate_capex(self, market_state, region, warnings):
        """计算学习曲线后的CAPEX"""
        capex_curve = self.data.get("capex_learning_curve", {})
        base = capex_curve.get("base_capex", {})
        params = capex_curve.get("learning_params", {})
        annual_install = capex_curve.get("annual_installations_gw", {})

        if not market_state or "year" not in market_state:
            return {"overrides": {}, "note": "无市场状态数据，使用基准CAPEX"}

        year = market_state.get("year", 2025)
        bess_gw = market_state.get("bess_installed_gw", 3.5)

        # 计算累计装机
        base_cumulative = params.get("base_cumulative_gw", 3.5)
        learning_rate = params.get("learning_rate", 0.12)
        progress_ratio = params.get("progress_ratio", 0.88)

        # 累计装机 = 基准累计 + 各年新增装机之和
        cumulative = base_cumulative
        for y in range(2026, year + 1):
            y_str = str(y)
            if y_str in annual_install:
                cumulative += annual_install[y_str]
            else:
                # 外推：假设与最近年份相同
                cumulative += annual_install.get(str(year), 7.0)

        # 计算翻倍次数
        if base_cumulative > 0:
            doublings = math.log2(cumulative / base_cumulative)
        else:
            doublings = 0

        # 学习曲线：成本 = 基准成本 × progress_ratio^doublings
        base_capex_kw = base.get("capex_aud_kw", 1183)
        base_capex_total = base.get("capex_total_aud", 355000000)
        base_capacity_mw = base.get("capacity_mw", 300)

        cost_multiplier = progress_ratio ** doublings
        capex_kw = base_capex_kw * cost_multiplier
        capex_total = base_capex_total * cost_multiplier

        # 确保不低于物理下限
        capex_kw = max(500, capex_kw)
        capex_total = max(capex_total, capex_kw * base_capacity_mw * 1000)

        return {
            "overrides": {
                "costs.capex_per_watt": round(capex_kw / 1000, 4),
                "costs.capex_total": round(capex_total, 0),
            },
            "details": {
                "assessment_year": year,
                "cumulative_bess_gw": round(cumulative, 1),
                "doublings_since_base": round(doublings, 2),
                "learning_rate": learning_rate,
                "cost_multiplier": round(cost_multiplier, 4),
                "base_capex_aud_kw": base_capex_kw,
                "projected_capex_aud_kw": round(capex_kw, 0),
                "base_capex_total_aud": base_capex_total,
                "projected_capex_total_aud": round(capex_total, 0),
            },
        }

    # ──────────────────────────────────────────────────────────
    # 步骤4: 接入成本
    # ──────────────────────────────────────────────────────────

    def _calculate_connection_cost(self, market_state, warnings):
        """计算接入成本趋势"""
        conn_trend = self.data.get("grid_connection_trend", {})
        base_cost = conn_trend.get("base_connection_cost_aud", 60000000)
        annual_esc = conn_trend.get("annual_escalation_pct", 5.0)
        ai_premium = conn_trend.get("ai_demand_premium_pct", 10.0)

        if not market_state or "year" not in market_state:
            return {"overrides": {}, "note": "无市场状态数据，使用基准接入成本"}

        year = market_state.get("year", 2025)
        years_from_base = max(0, year - 2025)

        # 年化涨幅
        escalation_factor = (1 + annual_esc / 100) ** years_from_base
        # AI溢价（假设2030年达到峰值，线性增长）
        ai_factor = 1 + (ai_premium / 100) * min(1, years_from_base / 5)

        projected_cost = base_cost * escalation_factor * ai_factor

        return {
            "overrides": {
                "costs.grid_connection_cost": round(projected_cost, 0),
            },
            "details": {
                "assessment_year": year,
                "base_cost_aud": base_cost,
                "escalation_factor": round(escalation_factor, 4),
                "ai_premium_factor": round(ai_factor, 4),
                "projected_connection_cost_aud": round(projected_cost, 0),
            },
        }

    # ──────────────────────────────────────────────────────────
    # 步骤5: FCAS衰减
    # ──────────────────────────────────────────────────────────

    def _calculate_fcas(self, market_state, warnings):
        """计算FCAS收益衰减"""
        spread_model = self.data.get("spread_compression_model", {})
        factors = spread_model.get("compression_factors", {})
        base = spread_model.get("base_spread", {})

        if not market_state or "year" not in market_state:
            return {"overrides": {}, "note": "无市场状态数据，使用基准FCAS"}

        bess_gw = market_state.get("bess_installed_gw", 3.5)
        base_bess = 3.5
        bess_increment = max(0, bess_gw - base_bess)

        base_fcas = base.get("fcas_aud_kw_year", 35)
        decay_per_gw = factors.get("fcas_decay_per_gw_bess", 1.5)
        fcas_floor = factors.get("fcas_floor_aud_kw_year", 15.0)

        projected_fcas = max(fcas_floor, base_fcas - bess_increment * decay_per_gw)

        return {
            "overrides": {
                "revenue.fcas_aud_kw_year": round(projected_fcas, 1),
            },
            "details": {
                "assessment_year": market_state.get("year"),
                "bess_increment_gw": bess_increment,
                "base_fcas_aud_kw_year": base_fcas,
                "projected_fcas_aud_kw_year": round(projected_fcas, 1),
                "fcas_floor_aud_kw_year": fcas_floor,
            },
        }

    # ──────────────────────────────────────────────────────────
    # 步骤6: 融资条件调整
    # ──────────────────────────────────────────────────────────

    def _calculate_financing(self, market_state, warnings):
        """计算融资条件调整"""
        fin_trend = self.data.get("financing_trend", {})
        base_rate = fin_trend.get("base_interest_rate", 0.06)
        base_tenor = fin_trend.get("base_loan_tenor_years", 15)
        base_discount = fin_trend.get("base_discount_rate", 0.09)
        adj = fin_trend.get("interest_rate_adjustment", {})

        if not market_state or "year" not in market_state:
            return {"overrides": {}, "note": "无市场状态数据，使用基准融资条件"}

        year = market_state.get("year", 2025)
        bess_gw = market_state.get("bess_installed_gw", 3.5)
        bess_increment = max(0, bess_gw - 3.5)

        # 风险溢价：每10GW BESS新增 +0.5%
        risk_premium = adj.get("risk_premium_per_10gw_bess", 0.005) * (bess_increment / 10)
        # 宏观利率下行
        macro_adjustment = adj.get("macro_rate_reduction_by_2030", -0.01)
        # 根据年份线性插值宏观调整
        if year <= 2025:
            macro_effect = 0
        elif year >= 2030:
            macro_effect = macro_adjustment
        else:
            macro_effect = macro_adjustment * (year - 2025) / 5

        projected_rate = base_rate + risk_premium + macro_effect
        projected_rate = max(0.03, min(0.12, projected_rate))

        # 折现率调整（跟随利率变化）
        discount_adjustment = projected_rate - base_rate
        projected_discount = base_discount + discount_adjustment
        projected_discount = max(0.05, min(0.15, projected_discount))

        return {
            "overrides": {
                "financing.interest_rate": round(projected_rate, 4),
                "financing.discount_rate": round(projected_discount, 4),
            },
            "details": {
                "assessment_year": year,
                "base_interest_rate": base_rate,
                "risk_premium": round(risk_premium, 4),
                "macro_adjustment": round(macro_effect, 4),
                "projected_interest_rate": round(projected_rate, 4),
                "base_discount_rate": base_discount,
                "projected_discount_rate": round(projected_discount, 4),
            },
        }

    # ──────────────────────────────────────────────────────────
    # 报告生成
    # ──────────────────────────────────────────────────────────

    def generate_report(self, result):
        """生成约束分析报告（Markdown）"""
        lines = []
        lines.append("# 外部条件约束分析报告")
        lines.append("")
        lines.append(f"**评估年份**: {result['assessment_year']}")
        lines.append(f"**评估区域**: {result['region']}")
        lines.append(f"**约束数据源**: {result['constraint_file']}")
        lines.append("")

        # 市场状态
        market = result.get("market_state", {})
        if market:
            lines.append("## 推演市场状态")
            lines.append("")
            lines.append(f"| 指标 | 值 |")
            lines.append(f"|------|-----|")
            lines.append(f"| NEM总装机 | {market.get('total_nem_gw', 'N/A')} GW |")
            lines.append(f"| BESS已投运 | {market.get('bess_installed_gw', 'N/A')} GW |")
            lines.append(f"| 煤电剩余 | {market.get('coal_total_gw', 'N/A')} GW |")
            lines.append(f"| 可再生能源占比 | {market.get('renewable_share_pct', 'N/A')}% |")
            lines.append(f"| 峰值需求 | {market.get('demand_peak_gw', 'N/A')} GW |")
            lines.append(f"| 插值方式 | {market.get('interpolation', 'N/A')} |")
            lines.append("")

        # 约束详情
        details = result.get("constraint_details", {})
        if details:
            lines.append("## 约束推演详情")
            lines.append("")

            # 电价约束
            price = details.get("price_constraint", {})
            if price.get("details"):
                d = price["details"]
                lines.append("### 电价约束（价差压缩）")
                lines.append("")
                lines.append(f"- BESS已投运: {d['bess_installed_gw']} GW (增量: +{d['bess_increment_gw']} GW)")
                lines.append(f"- 煤电退役: {d['coal_retired_gw']} GW")
                lines.append(f"- AI新增需求: {d['ai_demand_gw']} GW")
                lines.append(f"- 总价差压缩: ${d['total_compression_aud_mwh']}/MWh ({d['compression_ratio_pct']}%)")
                lines.append(f"- 基准电价: ${d['base_price_aud_kwh']:.4f}/kWh → 约束电价: **${d['compressed_price_aud_kwh']:.4f}/kWh**")
                lines.append(f"- 基准小时数: {d['base_hours']}h → 约束小时数: **{d['compressed_hours']}h**")
                lines.append("")

            # CAPEX约束
            capex = details.get("capex_constraint", {})
            if capex.get("details"):
                d = capex["details"]
                lines.append("### CAPEX约束（学习曲线）")
                lines.append("")
                lines.append(f"- 累计BESS装机: {d['cumulative_bess_gw']} GW (翻倍次数: {d['doublings_since_base']}x)")
                lines.append(f"- 学习率: {d['learning_rate']*100:.0f}% (成本乘数: {d['cost_multiplier']:.4f})")
                lines.append(f"- 基准CAPEX: ${d['base_capex_aud_kw']:,.0f}/kW → 约束CAPEX: **${d['projected_capex_aud_kw']:,.0f}/kW**")
                lines.append(f"- 基准总额: ${d['base_capex_total_aud']:,.0f} → 约束总额: **${d['projected_capex_total_aud']:,.0f}**")
                lines.append("")

            # 接入成本
            conn = details.get("connection_constraint", {})
            if conn.get("details"):
                d = conn["details"]
                lines.append("### 接入成本约束")
                lines.append("")
                lines.append(f"- 基准接入费: ${d['base_cost_aud']:,.0f}")
                lines.append(f"- 年化涨幅因子: {d['escalation_factor']:.4f}")
                lines.append(f"- AI溢价因子: {d['ai_premium_factor']:.4f}")
                lines.append(f"- 约束接入费: **${d['projected_connection_cost_aud']:,.0f}**")
                lines.append("")

            # FCAS约束
            fcas = details.get("fcas_constraint", {})
            if fcas.get("details"):
                d = fcas["details"]
                lines.append("### FCAS收益约束")
                lines.append("")
                lines.append(f"- BESS增量: +{d['bess_increment_gw']} GW")
                lines.append(f"- 基准FCAS: ${d['base_fcas_aud_kw_year']}/kW/年 → 约束FCAS: **${d['projected_fcas_aud_kw_year']}/kW/年**")
                lines.append(f"- FCAS下限: ${d['fcas_floor_aud_kw_year']}/kW/年")
                lines.append("")

            # 融资约束
            fin = details.get("financing_constraint", {})
            if fin.get("details"):
                d = fin["details"]
                lines.append("### 融资条件约束")
                lines.append("")
                lines.append(f"- 基准利率: {d['base_interest_rate']*100:.1f}%")
                lines.append(f"- 风险溢价: +{d['risk_premium']*100:.2f}%")
                lines.append(f"- 宏观调整: {d['macro_adjustment']*100:.2f}%")
                lines.append(f"- 约束利率: **{d['projected_interest_rate']*100:.1f}%**")
                lines.append(f"- 基准折现率: {d['base_discount_rate']*100:.1f}% → 约束折现率: **{d['projected_discount_rate']*100:.1f}%**")
                lines.append("")

        # 最终覆盖值
        overrides = result.get("overrides", {})
        if overrides:
            lines.append("## 最终参数覆盖")
            lines.append("")
            lines.append("| 参数路径 | 约束值 |")
            lines.append("|----------|--------|")
            for key, value in overrides.items():
                if isinstance(value, float):
                    lines.append(f"| {key} | {value:.4f} |")
                else:
                    lines.append(f"| {key} | {value} |")
            lines.append("")

        # 警告
        warnings = result.get("warnings", [])
        if warnings:
            lines.append("## 警告")
            lines.append("")
            for w in warnings:
                lines.append(f"- ⚠️ {w}")
            lines.append("")

        return "\n".join(lines)


# =============================================================================
# 独立运行测试
# =============================================================================

def main():
    """独立运行约束引擎，测试推演功能"""
    import argparse
    import json

    parser = argparse.ArgumentParser(description="外部条件约束求解引擎")
    parser.add_argument("--constraint-file", default=None, help="约束数据文件路径")
    parser.add_argument("--year", type=int, default=2030, help="评估年份")
    parser.add_argument("--region", default="NSW", help="NEM区域")
    parser.add_argument("--output", default=None, help="输出文件路径")
    parser.add_argument("--report", action="store_true", help="生成可读报告")
    args = parser.parse_args()

    engine = ConstraintEngine(args.constraint_file)
    result = engine.solve(year=args.year, region=args.region)

    if args.report:
        report = engine.generate_report(result)
        print(report)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(report)
            print(f"报告已保存: {args.output}")
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False, default=str)
            print(f"结果已保存: {args.output}")


if __name__ == "__main__":
    main()
