#!/usr/bin/env python3
"""
澳洲光伏/储能项目财务模型引擎（纯 Python）
=============================================
完全重写了 QEA/Core 风格 Excel 财务模型的计算逻辑，不依赖 Excel 文件。

核心功能：
- 月度精度现金流建模
- 多收入来源（PPA/现货/LGC/FCAS）
- 固定杠杆率债务计算
- ATO 合规折旧与税务计算
- 中期大修成本（逆变器/电池更换）
- 多场景对比与敏感性分析
- IRR/NPV/回收期计算

用法：
    python3 solar_financial_engine.py --scenarios scenarios.json --output OUTPUT/results.json
    python3 solar_financial_engine.py --interactive   # 交互式输入模式
"""

import json
import math
import datetime
import copy
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Tuple
from pathlib import Path
import numpy as np

# ═══════════════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class TimelineInput:
    """项目时间轴参数"""
    construction_start: str = "2026-01-01"   # 建设开始日期
    construction_months: int = 24            # 建设期（月）
    operation_years: int = 25                # 运营期（年，光伏标准25年）


@dataclass
class TechnologyInput:
    """技术参数"""
    pv_capacity_mwp: float = 0.0        # 光伏装机 (MWp)
    bess_capacity_mw: float = 0.0       # 储能装机 (MW)
    bess_duration_hrs: float = 0.0      # 储能时长 (小时)
    pv_degradation_pa: float = 0.005    # 光伏衰减 (%/年, 默认0.5%)
    bess_degradation_pa: float = 0.02   # 储能衰减 (%/年, 默认2%)
    bess_rte: float = 0.90              # 储能往返效率 (round-trip, 默认90%)
    aux_consumption_pct: float = 0.01   # 厂用电率 (默认1%)


@dataclass
class CapexInput:
    """CAPEX 参数（单位：AUD）"""
    pv_capex_per_kwp: float = 0.0       # 光伏 ($/kWp)
    bess_capex_per_kw: float = 0.0      # 储能 ($/kW)
    bop_epc_pct: float = 0.0            # BOP/EPC 占设备费比例
    development_cost: float = 0.0       # 开发费用 (AUD k)
    contingency_pct: float = 0.05       # 不可预见费比例


@dataclass
class OpexInput:
    """OPEX 参数"""
    pv_fixed_per_kwp_year: float = 0.0       # 光伏固定 ($/kWp/年)
    pv_variable_per_mwh: float = 0.0         # 光伏可变 ($/MWh)
    bess_fixed_per_kw_year: float = 0.0      # 储能固定 ($/kW/年)
    bess_variable_per_mwh: float = 0.0       # 储能可变 ($/MWh)
    escalation_rate: float = 0.02            # OPEX 年通胀率


@dataclass
class RevenueInput:
    """收入参数"""
    ppa_price_aud_mwh: float = 0.0          # PPA 电价 ($/MWh)
    ppa_percentage: float = 1.0             # PPA 覆盖比例 (默认100%)
    merchant_price_aud_mwh: float = 0.0     # 光伏现货电价 ($/MWh，混合模式下=直上网价)
    solar_capture_price_aud_mwh: Optional[float] = None  # 光伏午间捕获价 ($/MWh)，None=同merchant
    lgc_price_aud: float = 0.0             # LGC 绿证价格 ($/证书)
    lgc_rate_per_mwh: float = 0.0           # LGC 创建率 (证书/MWh，通常~1.0)
    fcas_revenue_aud_kw_year: float = 0.0   # FCAS 辅助服务 ($/kW/年)
    revenue_escalation: float = 0.0         # 收入年增长率
    bess_charge_price_aud_mwh: Optional[float] = None   # 储能电网充电电价 ($/MWh)
    bess_discharge_price_aud_mwh: Optional[float] = None # 储能放电压 ($/MWh)


@dataclass
class FinancingInput:
    """融资参数"""
    gearing_pct: float = 0.60               # 杠杆率 (默认60%)
    interest_rate_pa: float = 0.06           # 年利率 (6%)
    debt_tenor_years: float = 15.0           # 债务期限 (年)
    dsra_months: float = 6.0                 # DSRA 月数
    financing_fees_pct: float = 0.025        # 融资费用比例
    arrangement_fee_pct: float = 0.01        # 安排费比例


@dataclass
class TaxInput:
    """税务参数"""
    corporate_tax_rate: float = 0.30         # 公司税率 (30% 大型, 25% 小型)
    depreciation_method: str = "SL"          # SL=直线法, DV=余额递减法
    pv_effective_life_years: int = 20        # 光伏ATO有效寿命 (20年)
    bess_effective_life_years: int = 15      # 储能ATO有效寿命 (15年)
    inverter_effective_life_years: int = 10  # 逆变器ATO有效寿命 (10年)
    civil_works_life_years: int = 40         # 土建Div 43 (40年)
    financing_fee_deduct_years: int = 5      # 融资费用摊销年数


@dataclass
class MidLifeInput:
    """中期大修参数"""
    battery_replace_year: Optional[int] = 12     # 电池更换年份
    battery_replace_cost_pct: float = 0.65       # 更换成本占初始CAPEX比例
    inverter_replace_year: Optional[int] = 15    # 逆变器更换年份
    inverter_replace_cost_pct: float = 0.12      # 更换成本占初始光伏CAPEX比例
    major_maintenance_year: Optional[int] = 12   # 大修年份
    major_maintenance_cost: float = 0.0          # 大修费用 (AUD k)


@dataclass
class GenerationProfile:
    """发电量 profile（可选，代替简化的容量因子）"""
    pv_cf_monthly: List[float] = field(default_factory=lambda: [])  # 12个月容量因子
    bess_cycles_per_day: float = 1.0                                 # 日循环次数
    bess_daily_hours: float = 0.0                                    # 日运行小时数

    def get_monthly_pv_cf(self, month: int) -> float:
        """获取月度光伏容量因子"""
        if self.pv_cf_monthly and 0 <= month < len(self.pv_cf_monthly):
            return self.pv_cf_monthly[month]
        return 0.0  # 无光伏

    def get_bess_monthly_throughput_mwh(self, month: int, bess_mw: float,
                                         bess_hrs: float, degradation: float) -> float:
        """计算月度储能吞吐量 (MWh)"""
        if bess_mw <= 0 or bess_hrs <= 0:
            return 0.0
        # 简化：每天完整循环一次 (放电 MWh)
        # degradation 是剩余容量系数 (如 1.0=100%, 0.98=98%)，直接乘吞吐量
        days_in_month = 30.44
        daily_discharge_mwh = bess_mw * bess_hrs * self.bess_cycles_per_day
        monthly_discharge_mwh = daily_discharge_mwh * days_in_month * degradation
        return monthly_discharge_mwh


@dataclass
class ProjectInput:
    """完整的项目输入参数"""
    # 元数据
    name: str = "New Solar/BESS Project"
    location: str = "VIC, Australia"
    currency: str = "AUD"
    scenario_name: str = "Base Case"

    # 各模块参数
    timeline: TimelineInput = field(default_factory=TimelineInput)
    technology: TechnologyInput = field(default_factory=TechnologyInput)
    capex: CapexInput = field(default_factory=CapexInput)
    opex: OpexInput = field(default_factory=OpexInput)
    revenue: RevenueInput = field(default_factory=RevenueInput)
    financing: FinancingInput = field(default_factory=FinancingInput)
    tax: TaxInput = field(default_factory=TaxInput)
    mid_life: MidLifeInput = field(default_factory=MidLifeInput)
    generation: GenerationProfile = field(default_factory=GenerationProfile)

    # 关联场景
    scenario_group: str = "default"

    # ═══════════════════════════════════════════════════════════
    # V3: 市场均衡模块集成
    # ═══════════════════════════════════════════════════════════
    enable_market_equilibrium: bool = False
    market_equilibrium_cod_year: int = 2029
    market_equilibrium_fcas: float = 40.0

    def __post_init__(self):
        """应用市场均衡调整 (若启用)"""
        if self.enable_market_equilibrium:
            self._apply_market_equilibrium()

    def _apply_market_equilibrium(self):
        """根据COD年份自动调整收入参数"""
        try:
            from bess_market_equilibrium import MarketEquilibrium
            eq = MarketEquilibrium()
            r = eq.adjust_revenue(
                cod_year=self.market_equilibrium_cod_year,
                charge_price=self.revenue.bess_charge_price_aud_mwh or 0,
                discharge_price=self.revenue.bess_discharge_price_aud_mwh or 0,
                fcas=self.market_equilibrium_fcas
            )
            # 应用调整
            self.revenue.bess_charge_price_aud_mwh = r["equilibrium_charge"]
            self.revenue.bess_discharge_price_aud_mwh = r["equilibrium_discharge"]
            # 存储均衡元数据
            self._equilibrium_meta = r
        except ImportError:
            pass  # 模块不可用时静默跳过


# ═══════════════════════════════════════════════════════════════════════
# 月度模型计算引擎
# ═══════════════════════════════════════════════════════════════════════


class MonthlyFinancialModel:
    """月度财务模型计算引擎"""

    def __init__(self, inputs: ProjectInput):
        self.inputs = inputs
        self.total_months = 0
        self.construction_months = 0
        self.operation_months = 0

        # 月度数组
        self.is_construction = []      # 建设期标记
        self.is_operation = []         # 运营期标记
        self.is_fy_end = []            # 财年末标记
        self.operational_year = []     # 运营年份编号
        self.financial_year = []       # 财年

        # 核心计算结果
        self.revenue_monthly = []      # 月度收入
        self.opex_monthly = []         # 月度 OPEX
        self.maint_capex_monthly = []  # 月度维护CAPEX (含大修)
        self.ebitda_monthly = []       # 月度 EBITDA
        self.depn_monthly = []         # 月度折旧
        self.interest_monthly = []     # 月度利息
        self.principal_monthly = []    # 月度本金偿还
        self.tax_monthly = []          # 月度所得税
        self.equity_injection = []     # 股权投入
        self.equity_return = []        # 股权回报
        self.net_cash_equity = []      # 股权净现金流
        self.cumulative_cash = []      # 累计现金流
        self.debt_outstanding = []     # 债务余额

        # 汇总指标
        self.project_irr_pre_tax = 0.0
        self.project_irr_post_tax = 0.0
        self.project_npv_pre_tax = 0.0
        self.project_npv_post_tax = 0.0
        self.equity_irr = 0.0
        self.equity_npv = 0.0
        self.equity_payback_month = 0
        self.min_dscr = 0.0
        self.avg_dscr = 0.0
        self.lcoe = 0.0
        self.lcos = 0.0

        # 年度汇总
        self.annual_summary = {}

    # ── 时间轴 ────────────────────────────────────────────────────

    def _build_timeline(self):
        """构建月度时间轴"""
        tl = self.inputs.timeline
        self.construction_months = tl.construction_months
        self.operation_months = tl.operation_years * 12
        self.total_months = self.construction_months + self.operation_months

        self.is_construction = [False] * self.total_months
        self.is_operation = [False] * self.total_months
        self.is_fy_end = [False] * self.total_months
        self.operational_year = [0] * self.total_months
        self.financial_year = [0] * self.total_months

        # 解析开始日期
        try:
            start_dt = datetime.datetime.strptime(tl.construction_start, "%Y-%m-%d")
        except ValueError:
            start_dt = datetime.datetime(2026, 1, 1)

        for m in range(self.total_months):
            current_dt = self._month_offset(start_dt, m)

            if m < self.construction_months:
                self.is_construction[m] = True
            else:
                self.is_operation[m] = True
                op_year = (m - self.construction_months) // 12 + 1
                self.operational_year[m] = op_year

            # 财年 (澳洲: 7月-6月)
            fy = current_dt.year
            if current_dt.month >= 7:
                fy += 1
            self.financial_year[m] = fy
            # 财年末标记 (6月)
            if current_dt.month == 6:
                self.is_fy_end[m] = True

    def _month_offset(self, dt: datetime.datetime, months: int) -> datetime.datetime:
        """日期偏移月数"""
        total_months = dt.month - 1 + months
        year = dt.year + total_months // 12
        month = total_months % 12 + 1
        day = min(dt.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                           31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
        return datetime.datetime(year, month, day)

    # ── CAPEX ──────────────────────────────────────────────────────

    def _calc_capex(self):
        """计算建设期 CAPEX 支出"""
        capex = self.inputs.capex
        tech = self.inputs.technology

        # 总 CAPEX
        pv_capex_total = tech.pv_capacity_mwp * 1000 * capex.pv_capex_per_kwp if capex.pv_capex_per_kwp > 0 else 0
        bess_capex_total = tech.bess_capacity_mw * 1000 * capex.bess_capex_per_kw if capex.bess_capex_per_kw > 0 else 0
        equipment_total = pv_capex_total + bess_capex_total

        bop_epc = equipment_total * capex.bop_epc_pct if capex.bop_epc_pct > 0 else 0
        contingency = equipment_total * capex.contingency_pct
        development = capex.development_cost * 1000  # 转为 AUD

        total_capex = equipment_total + bop_epc + contingency + development
        total_capex_k = total_capex / 1000  # 转为 kAUD

        # 建设期均匀分摊
        monthly_capex = [0.0] * self.total_months
        if self.construction_months > 0:
            per_month = total_capex_k / self.construction_months
            for m in range(self.construction_months):
                monthly_capex[m] = per_month

        # 融资结构
        fin = self.inputs.financing
        total_debt = total_capex_k * fin.gearing_pct
        total_equity = total_capex_k - total_debt

        # 建设期利息 (简化：按均匀放款计算)
        idc_k = 0.0
        monthly_rate = fin.interest_rate_pa / 12
        if total_debt > 0:
            cumulative_debt = 0.0
            for m in range(self.construction_months):
                debt_this_month = (total_debt / self.construction_months)
                idc_this_month = (cumulative_debt + debt_this_month / 2) * monthly_rate
                idc_k += idc_this_month
                cumulative_debt += debt_this_month

        total_sources_k = total_debt + total_equity

        # 融资费用
        financing_fees_k = total_debt * fin.financing_fees_pct
        arrangement_fee_k = total_debt * fin.arrangement_fee_pct

        # DSRA
        dsra_k = (total_debt * fin.interest_rate_pa * fin.dsra_months / 12) if total_debt > 0 else 0

        return {
            "pv_capex_k": round(pv_capex_total / 1000, 2),
            "bess_capex_k": round(bess_capex_total / 1000, 2),
            "bop_epc_k": round(bop_epc / 1000, 2),
            "contingency_k": round(contingency / 1000, 2),
            "development_k": round(development / 1000, 2),
            "total_capex_k": round(total_capex_k, 2),
            "idc_k": round(idc_k, 2),
            "financing_fees_k": round(financing_fees_k, 2),
            "arrangement_fee_k": round(arrangement_fee_k, 2),
            "dsra_k": round(dsra_k, 2),
            "total_debt_k": round(total_debt, 2),
            "total_equity_k": round(total_equity, 2),
            "total_sources_k": round(total_sources_k, 2),
            "monthly_capex": monthly_capex
        }

    # ── 收入 ──────────────────────────────────────────────────────

    def _calc_revenue(self, month: int, cap_struct: dict) -> float:
        """计算月度收入 — 光伏+储能混合调度模式

        运行逻辑:
          光伏出力 → 优先充入自有储能（避免午间低价贱卖）
          储能不足 → 从电网低价充电补充
          储能满后 → 多余光伏才直接上网
          黄昏高峰 → 全部储能集中放电

        能源流向:
          solar → BESS → discharge (无现金充电成本，但有RTE损耗)
          solar → grid (午间捕获价 + LGC)
          grid → BESS → discharge (付充电成本)

        LGC: 全部光伏出力均获LGC，无论是否经过储能
        """
        if not self.is_operation[month]:
            return 0.0

        tech = self.inputs.technology
        rev = self.inputs.revenue
        gen = self.inputs.generation
        op_year = self.operational_year[month]

        days_in_month = 30.44
        pv_degradation = (1 - tech.pv_degradation_pa) ** (op_year - 1)
        bess_degradation = (1 - tech.bess_degradation_pa) ** (op_year - 1)

        # ── 1. 月度发电量/容量 ──────────────────────────────
        pv_gen_net = 0.0  # 光伏净发电量 (MWh, 扣除厂用电)
        if tech.pv_capacity_mwp > 0:
            cf = gen.get_monthly_pv_cf((month - self.construction_months) % 12)
            pv_gen_gross = tech.pv_capacity_mwp * cf * days_in_month * 24 * pv_degradation
            pv_gen_net = pv_gen_gross * (1 - tech.aux_consumption_pct)

        bess_max_discharge = 0.0  # 储能月度最大放电量 (MWh)
        bess_max_charge_input = 0.0  # 储能月度最大充电需求 (MWh, 含RTE损耗)
        if tech.bess_capacity_mw > 0 and tech.bess_duration_hrs > 0:
            bess_max_discharge = tech.bess_capacity_mw * tech.bess_duration_hrs * days_in_month * bess_degradation
            bess_max_charge_input = bess_max_discharge / tech.bess_rte

        # ── 2. 混合调度决策 ─────────────────────────────────
        # 判定: 光伏走储能 vs 直接上网 哪个更值？
        # 储能路径: discharge_price × RTE + LGC
        # 直上网路径: capture_price + LGC
        capture_price = rev.solar_capture_price_aud_mwh if rev.solar_capture_price_aud_mwh is not None else rev.merchant_price_aud_mwh
        discharge_price = rev.bess_discharge_price_aud_mwh if rev.bess_discharge_price_aud_mwh else 0
        charge_price = rev.bess_charge_price_aud_mwh if rev.bess_charge_price_aud_mwh else 0
        lgc_price = rev.lgc_price_aud

        solar_to_bess_value = discharge_price * tech.bess_rte  # 光伏→储能→放电的价值（不含LGC，LGC两边都有）
        solar_export_value = capture_price  # 光伏直上网的价值（不含LGC）

        if tech.bess_capacity_mw > 0 and solar_to_bess_value > solar_export_value:
            # 光伏优先充储能
            solar_to_bess = min(pv_gen_net, bess_max_charge_input)
            solar_export = max(0.0, pv_gen_net - bess_max_charge_input)
        else:
            # 光伏优先上网（或没有储能）
            solar_to_bess = 0.0
            solar_export = pv_gen_net

        # 储能不足部分从电网充电
        bess_grid_charge = max(0.0, bess_max_charge_input - solar_to_bess)

        # ── 3. 收入计算 ─────────────────────────────────────
        # 光伏直上网收入
        solar_export_rev = solar_export * capture_price

        # LGC: 全部光伏出力均获绿证
        lgc_rev = pv_gen_net * rev.lgc_rate_per_mwh * lgc_price

        # 储能放电收入
        # 光伏充入的放电 = solar_to_bess × RTE (无现金充电成本)
        # 电网充入的放电 = bess_grid_charge × RTE
        bess_total_discharge = (solar_to_bess + bess_grid_charge) * tech.bess_rte
        bess_discharge_rev = bess_total_discharge * discharge_price

        # 储能电网充电成本（仅电网充电有现金成本）
        bess_grid_charge_cost = bess_grid_charge * charge_price

        # FCAS
        fcas_rev = tech.bess_capacity_mw * 1000 * rev.fcas_revenue_aud_kw_year / 12 if tech.bess_capacity_mw > 0 else 0.0

        total_rev = (solar_export_rev + lgc_rev + bess_discharge_rev
                     - bess_grid_charge_cost + fcas_rev) / 1000  # → kAUD

        # 收入年增长率（仅对电价部分，FCAS不增长）
        if rev.revenue_escalation > 0 and op_year > 1:
            total_rev *= (1 + rev.revenue_escalation) ** (op_year - 1)

        return total_rev

    # ── OPEX ──────────────────────────────────────────────────────

    def _calc_opex(self, month: int) -> float:
        """计算月度 OPEX"""
        if not self.is_operation[month]:
            return 0.0

        tech = self.inputs.technology
        opex = self.inputs.opex
        op_year = self.operational_year[month]

        # 通胀调整
        escalation = (1 + opex.escalation_rate) ** (op_year - 1)

        pv_fixed = tech.pv_capacity_mwp * 1000 * opex.pv_fixed_per_kwp_year / 12 * escalation
        pv_variable = 0  # 按发电量计算的可变OPEX (简化)
        bess_fixed = tech.bess_capacity_mw * 1000 * opex.bess_fixed_per_kw_year / 12 * escalation

        total = (pv_fixed + pv_variable + bess_fixed) / 1000  # 转为 kAUD
        return total

    # ── 中期大修 ─────────────────────────────────────────────────

    def _calc_midlife_capex(self, month: int) -> float:
        """计算中期大修/更换成本（按月分摊，除以 12 避免重复计数）"""
        if not self.is_operation[month]:
            return 0.0

        ml = self.inputs.mid_life
        tech = self.inputs.technology
        capex = self.inputs.capex
        op_year = self.operational_year[month]

        total = 0.0

        # 电池更换（仅在第 12 运营年，按月分摊）
        if ml.battery_replace_year and op_year == ml.battery_replace_year:
            bess_initial = tech.bess_capacity_mw * 1000 * capex.bess_capex_per_kw
            total += bess_initial * ml.battery_replace_cost_pct / 12

        # 逆变器更换（仅在第 15 运营年，按月分摊）
        if ml.inverter_replace_year and op_year == ml.inverter_replace_year:
            pv_initial = tech.pv_capacity_mwp * 1000 * capex.pv_capex_per_kwp
            total += pv_initial * ml.inverter_replace_cost_pct / 12

        # 大修（按月分摊）
        if ml.major_maintenance_year and op_year == ml.major_maintenance_year:
            total += ml.major_maintenance_cost * 1000 / 12  # 转为 AUD

        return total / 1000  # 转为 kAUD

    # ── 折旧 ──────────────────────────────────────────────────────

    def _calc_depreciation(self) -> List[float]:
        """计算月度折旧（按 ATO 有效寿命）"""
        tax = self.inputs.tax
        tech = self.inputs.technology
        capex = self.inputs.capex
        cap_struct = self._calc_capex()

        depn = [0.0] * self.total_months

        # 资产基数
        pv_base = tech.pv_capacity_mwp * 1000 * capex.pv_capex_per_kwp if capex.pv_capex_per_kwp > 0 else 0
        bess_base = tech.bess_capacity_mw * 1000 * capex.bess_capex_per_kw if capex.bess_capex_per_kw > 0 else 0

        # 含 IDC 资本化
        pv_base += cap_struct.get("idc_k", 0) * 1000 * (pv_base / (pv_base + bess_base + 1)) if (pv_base + bess_base) > 0 else 0
        bess_base += cap_struct.get("idc_k", 0) * 1000 * (bess_base / (pv_base + bess_base + 1)) if (pv_base + bess_base) > 0 else 0

        # 月度折旧率
        def calc_monthly_depn(base, life_years, method):
            if base <= 0 or life_years <= 0:
                return 0.0
            if method == "SL":
                return base / (life_years * 12)
            elif method == "DV":
                dv_rate = 2.0 / life_years / 12  # 200% 递减法
                return base * dv_rate
            return 0.0

        pv_monthly_depn = calc_monthly_depn(pv_base, tax.pv_effective_life_years, tax.depreciation_method)
        bess_monthly_depn = calc_monthly_depn(bess_base, tax.bess_effective_life_years, tax.depreciation_method)
        inv_monthly_depn = calc_monthly_depn(pv_base * 0.10,
                                              tax.inverter_effective_life_years, "SL") if pv_base > 0 else 0

        total_monthly_depn = pv_monthly_depn + bess_monthly_depn + inv_monthly_depn

        for m in range(self.total_months):
            if self.is_operation[m]:
                depn[m] = total_monthly_depn / 1000  # 转为 kAUD

        return depn

    # ── 债务服务 ─────────────────────────────────────────────────

    def _calc_debt_service(self, total_debt_k: float) -> Tuple[List[float], List[float], List[float]]:
        """计算月度债务服务（等额本息）"""
        fin = self.inputs.financing
        interest = [0.0] * self.total_months
        principal = [0.0] * self.total_months
        outstanding = [0.0] * self.total_months

        if total_debt_k <= 0:
            return interest, principal, outstanding

        monthly_rate = fin.interest_rate_pa / 12
        total_payments = int(fin.debt_tenor_years * 12)

        # 等额本息月供
        if monthly_rate > 0:
            payment = total_debt_k * monthly_rate * (1 + monthly_rate) ** total_payments / \
                      ((1 + monthly_rate) ** total_payments - 1)
        else:
            payment = total_debt_k / total_payments

        remaining = total_debt_k
        payment_count = 0

        for m in range(self.total_months):
            if self.is_construction[m]:
                outstanding[m] = total_debt_k * (m + 1) / self.construction_months
            elif self.is_operation[m] and payment_count < total_payments:
                int_part = remaining * monthly_rate
                prin_part = payment - int_part
                if prin_part > remaining:
                    prin_part = remaining
                interest[m] = int_part
                principal[m] = prin_part
                remaining -= prin_part
                outstanding[m] = remaining
                payment_count += 1
            else:
                outstanding[m] = remaining

        return interest, principal, outstanding

    # ── 税务 ──────────────────────────────────────────────────────

    def _calc_tax(self, ebitda: List[float], depn: List[float], interest: List[float]) -> List[float]:
        """计算月度所得税"""
        tax_rate = self.inputs.tax.corporate_tax_rate
        tax = [0.0] * self.total_months
        cum_loss = 0.0  # 累计税务亏损

        for m in range(self.total_months):
            taxable_income = ebitda[m] - depn[m] - interest[m]

            if taxable_income < 0:
                cum_loss += abs(taxable_income)
                tax[m] = 0.0
            else:
                # 先用亏损抵扣
                if cum_loss > 0:
                    offset = min(taxable_income, cum_loss)
                    taxable_income -= offset
                    cum_loss -= offset
                tax[m] = taxable_income * tax_rate if taxable_income > 0 else 0.0

        return tax

    # ── 股权现金流 ────────────────────────────────────────────────

    def _calc_equity_cf(self, cap_struct: dict, debt_principal: List[float],
                        tax: List[float]) -> Tuple[List[float], List[float], List[float]]:
        """计算股权现金流"""
        total_equity = cap_struct["total_equity_k"]
        equity_in = [0.0] * self.total_months
        equity_out = [0.0] * self.total_months
        net_cash = [0.0] * self.total_months

        # 建设期股权投入
        if self.construction_months > 0:
            per_month = total_equity / self.construction_months
            for m in range(self.construction_months):
                equity_in[m] = -per_month

# 运营期股权回报（可用现金流可正可负：正=分红，负=需额外注资）
        for m in range(self.total_months):
            if self.is_operation[m]:
                avail = (self.ebitda_monthly[m] - self.interest_monthly[m] -
                         debt_principal[m] - tax[m] - self.maint_capex_monthly[m])
                equity_out[m] = avail
                net_cash[m] = avail

        # 总净现金流（含建设期投入）
        for m in range(self.total_months):
            net_cash[m] = net_cash[m] + equity_in[m]

        return equity_in, equity_out, net_cash

    # ── IRR/NPV 计算 ─────────────────────────────────────────────

    def _calc_irr(self, cashflows: List[float]) -> float:
        """计算 IRR"""
        if not cashflows or all(c == 0 for c in cashflows):
            return 0.0

        try:
            import numpy_financial as npf
            return float(npf.irr(cashflows))
        except ImportError:
            pass

        # 手动牛顿法
        rate = 0.1
        for _ in range(1000):
            npv = sum(c / (1 + rate) ** i for i, c in enumerate(cashflows))
            derivative = sum(-i * c / (1 + rate) ** (i + 1) for i, c in enumerate(cashflows))
            if abs(derivative) < 1e-12:
                break
            rate_new = rate - npv / derivative
            if abs(rate_new - rate) < 1e-10:
                return rate_new
            rate = rate_new
        return rate

    def _calc_npv(self, cashflows: List[float], rate: float) -> float:
        """计算 NPV"""
        return sum(c / (1 + rate) ** i for i, c in enumerate(cashflows))

    def _calc_payback(self, cashflows: List[float]) -> int:
        """计算折现回收期（月）"""
        cum = 0.0
        for i, c in enumerate(cashflows):
            cum += c
            if cum >= 0 and i > 0:
                return i
        return self.total_months

    # ── DSCR ──────────────────────────────────────────────────────

    def _calc_dscr(self) -> Tuple[float, float]:
        """计算偿债覆盖率"""
        dscrs = []
        annual_ebitda = 0.0
        annual_debt = 0.0

        for m in range(self.total_months):
            if self.is_fy_end[m] or m == self.total_months - 1:
                if annual_debt > 0:
                    dscrs.append(annual_ebitda / annual_debt)
                annual_ebitda = 0.0
                annual_debt = 0.0
            if self.is_operation[m]:
                annual_ebitda += self.ebitda_monthly[m]
                annual_debt += self.interest_monthly[m] + self.principal_monthly[m]

        if dscrs:
            return min(dscrs), sum(dscrs) / len(dscrs)
        return 0.0, 0.0

    # ── LCOE/LCOS ─────────────────────────────────────────────────

    def _calc_lcoe_lcos(self, cap_struct: dict) -> Dict[str, float]:
        """计算 LCOE/LCOS/混合LCOE（成本已按资产拆分，储能含充电成本）

        返回 dict:
            lcoe_aud_mwh:      光伏 LCOE（仅光伏相关成本）
            lcos_aud_mwh:      储能 LCOS（仅储能成本 + 充电成本）
            blended_lcoe_aud_mwh: 混合 LCOE（总成本 / 总输出）
            pv/bess_cost_breakdown: 成本明细
        """
        tech = self.inputs.technology
        gen = self.inputs.generation
        opex_in = self.inputs.opex
        capex_in = self.inputs.capex
        ml_in = self.inputs.mid_life

        # 1. 全生命周期发电量/吞吐量/充电量
        total_pv_gen = 0.0
        total_bess_throughput = 0.0
        total_charge_volume = 0.0

        for m in range(self.total_months):
            if self.is_operation[m]:
                op_year = self.operational_year[m]
                if tech.pv_capacity_mwp > 0:
                    cf = gen.get_monthly_pv_cf((m - self.construction_months) % 12)
                    pv_gen = tech.pv_capacity_mwp * cf * 30.44 * 24
                    pv_gen *= (1 - tech.pv_degradation_pa) ** (op_year - 1)
                    total_pv_gen += pv_gen
                if tech.bess_capacity_mw > 0:
                    bess_degradation = (1 - tech.bess_degradation_pa) ** (op_year - 1)
                    bess_thru = gen.get_bess_monthly_throughput_mwh(
                        m, tech.bess_capacity_mw, tech.bess_duration_hrs, bess_degradation)
                    total_bess_throughput += bess_thru
                    total_charge_volume += bess_thru / tech.bess_rte

        # 2. CAPEX 按设备份额拆分
        pv_equip_k = tech.pv_capacity_mwp * 1000 * capex_in.pv_capex_per_kwp / 1000 if capex_in.pv_capex_per_kwp > 0 else 0
        bess_equip_k = tech.bess_capacity_mw * 1000 * capex_in.bess_capex_per_kw / 1000 if capex_in.bess_capex_per_kw > 0 else 0
        equip_total = pv_equip_k + bess_equip_k
        if equip_total > 0:
            pv_share = pv_equip_k / equip_total
            bess_share = bess_equip_k / equip_total
        else:
            pv_share = 0.5 if tech.pv_capacity_mwp > 0 else 0.0
            bess_share = 0.5 if tech.bess_capacity_mw > 0 else 0.0

        shared_capex_k = cap_struct["total_capex_k"] - pv_equip_k - bess_equip_k
        pv_capex_k = pv_equip_k + shared_capex_k * pv_share
        bess_capex_k = bess_equip_k + shared_capex_k * bess_share

        # 3. OPEX 按资产拆分
        pv_opex_k = 0.0
        bess_opex_k = 0.0
        for m in range(self.total_months):
            if self.is_operation[m]:
                op_year = self.operational_year[m]
                escalation = (1 + opex_in.escalation_rate) ** (op_year - 1)
                if tech.pv_capacity_mwp > 0:
                    pv_opex_k += (tech.pv_capacity_mwp * 1000 * opex_in.pv_fixed_per_kwp_year / 12 * escalation) / 1000
                if tech.bess_capacity_mw > 0:
                    bess_opex_k += (tech.bess_capacity_mw * 1000 * opex_in.bess_fixed_per_kw_year / 12 * escalation) / 1000

        # 4. 维护 CAPEX 按资产拆分
        pv_maint_k = 0.0
        bess_maint_k = 0.0
        for m in range(self.total_months):
            if self.is_operation[m]:
                op_year = self.operational_year[m]
                if ml_in.battery_replace_year and op_year == ml_in.battery_replace_year:
                    bess_maint_k += (tech.bess_capacity_mw * 1000 * capex_in.bess_capex_per_kw * ml_in.battery_replace_cost_pct / 12) / 1000
                if ml_in.inverter_replace_year and op_year == ml_in.inverter_replace_year:
                    pv_maint_k += (tech.pv_capacity_mwp * 1000 * capex_in.pv_capex_per_kwp * ml_in.inverter_replace_cost_pct / 12) / 1000

        # 5. 储能充电成本（BESS 独有：买电来充）
        bess_charge_cost_k = 0.0
        charge_price = self.inputs.revenue.bess_charge_price_aud_mwh
        if charge_price and charge_price > 0:
            bess_charge_cost_k = total_charge_volume * charge_price / 1000

        # 6. 无贴现 LCOE/LCOS（简化）
        pv_total_k = pv_capex_k + pv_opex_k + pv_maint_k
        bess_total_k = bess_capex_k + bess_opex_k + bess_maint_k + bess_charge_cost_k

        lcoe = (pv_total_k * 1000 / total_pv_gen) if total_pv_gen > 0 else 0.0
        lcos = (bess_total_k * 1000 / total_bess_throughput) if total_bess_throughput > 0 else 0.0

        total_all_k = pv_total_k + bess_total_k
        total_all_out = total_pv_gen + total_bess_throughput
        blended = (total_all_k * 1000 / total_all_out) if total_all_out > 0 else 0.0

        # 7. 贴现 LCOE/LCOS（行业标准：AEMO/CSIRO 均使用贴现公式）
        discount_rate = 0.06  # 项目 WACC 典型值 6%
        monthly_r = discount_rate / 12

        pv_cost_discounted = 0.0
        bess_cost_discounted = 0.0
        pv_gen_discounted = 0.0
        bess_thru_discounted = 0.0
        combined_out_discounted = 0.0

        for m in range(self.total_months):
            df = 1.0 / (1 + monthly_r) ** m
            if self.is_operation[m]:
                op_year = self.operational_year[m]
                month_idx = (m - self.construction_months) % 12
                escalation = (1 + opex_in.escalation_rate) ** (op_year - 1)

                # 贴现发电量（net = 扣除厂用电）
                if tech.pv_capacity_mwp > 0:
                    cf = gen.get_monthly_pv_cf(month_idx)
                    pv_gen_m = tech.pv_capacity_mwp * cf * 30.44 * 24
                    pv_gen_m *= (1 - tech.pv_degradation_pa) ** (op_year - 1)
                    pv_gen_net = pv_gen_m * (1 - tech.aux_consumption_pct)
                    pv_gen_discounted += pv_gen_net * df

                if tech.bess_capacity_mw > 0:
                    bess_deg = (1 - tech.bess_degradation_pa) ** (op_year - 1)
                    bess_thru_m = gen.get_bess_monthly_throughput_mwh(
                        m, tech.bess_capacity_mw, tech.bess_duration_hrs, bess_deg)
                    bess_thru_discounted += bess_thru_m * df
                    combined_out_discounted += bess_thru_m * df

                combined_out_discounted += (pv_gen_net if tech.pv_capacity_mwp > 0 else 0) * df

                # 贴现成本：OPEX（按月）
                if tech.pv_capacity_mwp > 0:
                    pv_opex_m = (tech.pv_capacity_mwp * 1000 * opex_in.pv_fixed_per_kwp_year / 12 * escalation) / 1000
                    pv_cost_discounted += pv_opex_m * df
                if tech.bess_capacity_mw > 0:
                    bess_opex_m = (tech.bess_capacity_mw * 1000 * opex_in.bess_fixed_per_kw_year / 12 * escalation) / 1000
                    bess_cost_discounted += bess_opex_m * df

            # 贴现 CAPEX（建设期按月分摊）
            if self.is_construction[m]:
                df_capex = 1.0 / (1 + monthly_r) ** m
                pv_cost_discounted += (cap_struct["monthly_capex"][m] * pv_share) * df_capex
                bess_cost_discounted += (cap_struct["monthly_capex"][m] * bess_share) * df_capex

        # 贴现中期大修
        for m in range(self.total_months):
            if self.is_operation[m]:
                op_year = self.operational_year[m]
                df = 1.0 / (1 + monthly_r) ** m
                if ml_in.battery_replace_year and op_year == ml_in.battery_replace_year:
                    maint_m = (tech.bess_capacity_mw * 1000 * capex_in.bess_capex_per_kw * ml_in.battery_replace_cost_pct / 12) / 1000
                    bess_cost_discounted += maint_m * df
                if ml_in.inverter_replace_year and op_year == ml_in.inverter_replace_year:
                    maint_m = (tech.pv_capacity_mwp * 1000 * capex_in.pv_capex_per_kwp * ml_in.inverter_replace_cost_pct / 12) / 1000
                    pv_cost_discounted += maint_m * df

        # 贴现充电成本
        for m in range(self.total_months):
            if self.is_operation[m] and tech.bess_capacity_mw > 0:
                op_year = self.operational_year[m]
                df = 1.0 / (1 + monthly_r) ** m
                bess_deg = (1 - tech.bess_degradation_pa) ** (op_year - 1)
                bess_thru_m = gen.get_bess_monthly_throughput_mwh(
                    m, tech.bess_capacity_mw, tech.bess_duration_hrs, bess_deg)
                charge_vol_m = bess_thru_m / tech.bess_rte
                if charge_price and charge_price > 0:
                    bess_cost_discounted += (charge_vol_m * charge_price / 1000) * df

        disc_lcoe = (pv_cost_discounted * 1000 / pv_gen_discounted) if pv_gen_discounted > 0 else 0.0
        disc_lcos = (bess_cost_discounted * 1000 / bess_thru_discounted) if bess_thru_discounted > 0 else 0.0
        disc_blended = ((pv_cost_discounted + bess_cost_discounted) * 1000 / combined_out_discounted) if combined_out_discounted > 0 else 0.0

        return {
            "lcoe_aud_mwh": round(lcoe, 2),
            "lcos_aud_mwh": round(lcos, 2),
            "blended_lcoe_aud_mwh": round(blended, 2),
            "lcoe_discounted_aud_mwh": round(disc_lcoe, 2),
            "lcos_discounted_aud_mwh": round(disc_lcos, 2),
            "blended_discounted_aud_mwh": round(disc_blended, 2),
            "discount_rate_used": discount_rate,
            "pv_cost_breakdown": {
                "capex_k": round(pv_capex_k, 2),
                "opex_k": round(pv_opex_k, 2),
                "maint_k": round(pv_maint_k, 2),
                "total_k": round(pv_total_k, 2),
                "discounted_total_k": round(pv_cost_discounted, 2),
                "pv_gen_mwh": round(total_pv_gen, 0),
                "pv_gen_discounted_mwh": round(pv_gen_discounted, 0)
            },
            "bess_cost_breakdown": {
                "capex_k": round(bess_capex_k, 2),
                "opex_k": round(bess_opex_k, 2),
                "maint_k": round(bess_maint_k, 2),
                "charge_cost_k": round(bess_charge_cost_k, 2),
                "total_k": round(bess_total_k, 2),
                "discounted_total_k": round(bess_cost_discounted, 2),
                "throughput_mwh": round(total_bess_throughput, 0),
                "throughput_discounted_mwh": round(bess_thru_discounted, 0)
            }
        }

    # ── 🔒 运行时自检（V2.0 新增：强制执行关键验证）─────────────────

    def _validate(self) -> List[str]:
        """运行时参数和逻辑验证。返回警告列表，critical 项会 raise ValueError。"""
        warnings = []
        errors = []
        tech = self.inputs.technology
        capex = self.inputs.capex
        rev = self.inputs.revenue
        fin = self.inputs.financing
        ml = self.inputs.mid_life

        # 1. CAPEX 双重计费检测
        if capex.pv_capex_per_kwp > 800 and capex.bop_epc_pct > 0:
            errors.append("CAPEX_DOUBLE_COUNT: PV单价 > $800/kWp 且 bop_epc_pct > 0，疑似全包价+EPC双重计费")
        if capex.bess_capex_per_kw > 600 and capex.bop_epc_pct > 0:
            errors.append("CAPEX_DOUBLE_COUNT: BESS单价 > $600/kW 且 bop_epc_pct > 0，疑似全包价+EPC双重计费")

        # 2. 混合项目必须设置光伏捕获价
        is_hybrid = tech.pv_capacity_mwp > 0 and tech.bess_capacity_mw > 0
        is_pure_bess = tech.pv_capacity_mwp == 0 and tech.bess_capacity_mw > 0
        if is_hybrid and rev.solar_capture_price_aud_mwh is None:
            errors.append("HYBRID_NO_CAPTURE_PRICE: 光储混合项目必须设置 solar_capture_price_aud_mwh")

        # 3. BESS 充放电压必须独立设置（不能回退到 merchant×0.4）
        if tech.bess_capacity_mw > 0:
            if rev.bess_charge_price_aud_mwh is None or rev.bess_discharge_price_aud_mwh is None:
                errors.append("BESS_NO_SPREAD: 含储能项目必须设置 bess_charge/discharge_price")

        # 4. FCAS 与项目类型匹配
        if is_pure_bess and rev.fcas_revenue_aud_kw_year < 28:
            warnings.append(f"FCAS_LOW_FOR_PURE_BESS: 纯储能FCAS={rev.fcas_revenue_aud_kw_year}/kW，建议 ≥30")
        if is_hybrid and rev.fcas_revenue_aud_kw_year > 28:
            warnings.append(f"FCAS_HIGH_FOR_HYBRID: 混合储能FCAS={rev.fcas_revenue_aud_kw_year}/kW，建议 ≤25")

        # 5. 电池更换比例与化学类型
        if tech.bess_capacity_mw > 0 and ml.battery_replace_cost_pct > 0.50:
            warnings.append(f"BATTERY_REPLACEMENT_HIGH: 更换比例={ml.battery_replace_cost_pct:.0%}，确认是否为旧NMC化学？LFP应≤35%")

        # 6. 纯储能负电价策略
        if is_pure_bess and rev.bess_charge_price_aud_mwh is not None and rev.bess_charge_price_aud_mwh > 0:
            warnings.append("PURE_BESS_NO_NEGATIVE_STRATEGY: 纯储能充电价>0，未利用负电价")

        # 7. gearing=0 时利率应为 0（否则会计算无意义的债务服务）
        if fin.gearing_pct == 0 and fin.interest_rate_pa > 0:
            warnings.append("GEARING_ZERO_WITH_INTEREST: gearing=0 但利率>0，已忽略")

        # 8. 运营年限 vs ATO 折旧年限
        if tech.pv_capacity_mwp > 0 and self.inputs.timeline.operation_years > self.inputs.tax.pv_effective_life_years:
            warnings.append(f"PV_DEPRECIATION_SHORTER_THAN_OPS: 光伏运营{self.inputs.timeline.operation_years}年>折旧{self.inputs.tax.pv_effective_life_years}年")

        if errors:
            raise ValueError("🚫 运行时验证失败:\n  " + "\n  ".join(errors))
        return warnings

    # ── 主执行 ────────────────────────────────────────────────────

    def run(self) -> dict:
        """执行完整计算"""
        # 🔒 运行时自检
        self.validation_warnings = self._validate()

        self._build_timeline()

        # 1. CAPEX
        cap_struct = self._calc_capex()

        # 2. 月度计算
        self.revenue_monthly = [0.0] * self.total_months
        self.opex_monthly = [0.0] * self.total_months
        self.maint_capex_monthly = [0.0] * self.total_months
        self.ebitda_monthly = [0.0] * self.total_months

        for m in range(self.total_months):
            self.revenue_monthly[m] = self._calc_revenue(m, cap_struct)
            self.opex_monthly[m] = self._calc_opex(m)
            self.maint_capex_monthly[m] = self._calc_midlife_capex(m)
            self.ebitda_monthly[m] = self.revenue_monthly[m] - self.opex_monthly[m]

        # 3. 折旧
        self.depn_monthly = self._calc_depreciation()

        # 4. 债务
        self.interest_monthly, self.principal_monthly, self.debt_outstanding = \
            self._calc_debt_service(cap_struct["total_debt_k"])

        # 5. 税务
        self.tax_monthly = self._calc_tax(self.ebitda_monthly, self.depn_monthly, self.interest_monthly)

        # 6. 股权现金流
        self.equity_injection, self.equity_return, self.net_cash_equity = \
            self._calc_equity_cf(cap_struct, self.principal_monthly, self.tax_monthly)

        # 7. 累计现金流
        cum = 0.0
        for v in self.net_cash_equity:
            cum += v
            self.cumulative_cash.append(cum)

        # 8. 项目现金流（不含融资）
        project_cf = [0.0] * self.total_months
        for m in range(self.total_months):
            if self.is_operation[m]:
                project_cf[m] = (self.ebitda_monthly[m] - self.tax_monthly[m] -
                                 self.maint_capex_monthly[m])
            elif self.is_construction[m]:
                project_cf[m] = -cap_struct["monthly_capex"][m]

        # 9. IRR/NPV
        monthly_irr = self._calc_irr(project_cf)
        self.project_irr_pre_tax = (1 + monthly_irr) ** 12 - 1  # 年化
        self.project_irr_post_tax = (1 + monthly_irr) ** 12 - 1  # 简化：项目IRR不区分税前税后
        equity_monthly_irr = self._calc_irr(self.net_cash_equity)
        self.equity_irr = (1 + equity_monthly_irr) ** 12 - 1  # 年化

        discount_rate = 0.06
        self.project_npv_pre_tax = self._calc_npv(project_cf, discount_rate / 12)  # 月折现率
        self.project_npv_post_tax = self._calc_npv(project_cf, discount_rate / 12)
        self.equity_npv = self._calc_npv(self.net_cash_equity, 0.08 / 12)

        # 10. 回收期
        self.equity_payback_month = self._calc_payback(self.cumulative_cash)

        # 11. DSCR
        self.min_dscr, self.avg_dscr = self._calc_dscr()

        # 12. LCOE/LCOS
        lcoe_lcos_data = self._calc_lcoe_lcos(cap_struct)
        self.lcoe = lcoe_lcos_data["lcoe_aud_mwh"]
        self.lcos = lcoe_lcos_data["lcos_aud_mwh"]
        self.lcoe_lcos_breakdown = lcoe_lcos_data  # 存完整明细

        # 13. 年度汇总
        self._build_annual_summary(cap_struct)

        # 14. 组装结果
        return self._to_dict(cap_struct)

    def _build_annual_summary(self, cap_struct: dict):
        """构建年度汇总"""
        years = sorted(set(self.financial_year))
        self.annual_summary = {
            "financial_years": [str(y) for y in years if y > 0],
            "revenue": [],
            "opex": [],
            "ebitda": [],
            "interest": [],
            "principal": [],
            "tax": [],
            "net_cash_equity": [],
            "cumulative_cash": [],
            "maint_capex": []
        }

        for fy in years:
            if fy <= 0:
                continue
            rev = sum(self.revenue_monthly[m] for m in range(self.total_months)
                      if self.financial_year[m] == fy)
            opx = sum(self.opex_monthly[m] for m in range(self.total_months)
                      if self.financial_year[m] == fy)
            ebitda = sum(self.ebitda_monthly[m] for m in range(self.total_months)
                         if self.financial_year[m] == fy)
            int_p = sum(self.interest_monthly[m] for m in range(self.total_months)
                        if self.financial_year[m] == fy)
            prin = sum(self.principal_monthly[m] for m in range(self.total_months)
                       if self.financial_year[m] == fy)
            tx = sum(self.tax_monthly[m] for m in range(self.total_months)
                     if self.financial_year[m] == fy)
            eq = sum(self.net_cash_equity[m] for m in range(self.total_months)
                     if self.financial_year[m] == fy)
            mc = sum(self.maint_capex_monthly[m] for m in range(self.total_months)
                     if self.financial_year[m] == fy)

            # 累计现金流到该财年末
            cum_at_fy = sum(self.net_cash_equity[m] for m in range(self.total_months)
                            if self.financial_year[m] <= fy)

            self.annual_summary["revenue"].append(round(rev, 2))
            self.annual_summary["opex"].append(round(opx, 2))
            self.annual_summary["ebitda"].append(round(ebitda, 2))
            self.annual_summary["interest"].append(round(int_p, 2))
            self.annual_summary["principal"].append(round(prin, 2))
            self.annual_summary["tax"].append(round(tx, 2))
            self.annual_summary["net_cash_equity"].append(round(eq, 2))
            self.annual_summary["cumulative_cash"].append(round(cum_at_fy, 2))
            self.annual_summary["maint_capex"].append(round(mc, 2))

    def _to_dict(self, cap_struct: dict) -> dict:
        """将结果转为可序列化字典"""
        return {
            "run_id": f"engine_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "workflow_id": "solar_financial_model",
            "scenario_name": self.inputs.scenario_name,
            "project_info": {
                "name": self.inputs.name,
                "location": self.inputs.location,
                "technology_type": "solar_plus_bess" if (self.inputs.technology.pv_capacity_mwp > 0 and
                                                          self.inputs.technology.bess_capacity_mw > 0)
                else "bess" if self.inputs.technology.bess_capacity_mw > 0
                else "solar_pv",
                "pv_capacity_mwp": self.inputs.technology.pv_capacity_mwp,
                "bess_capacity_mw": self.inputs.technology.bess_capacity_mw,
                "bess_duration_hrs": self.inputs.technology.bess_duration_hrs,
                "construction_start": self.inputs.timeline.construction_start,
                "construction_months": self.construction_months,
                "operation_years": self.inputs.timeline.operation_years
            },
            "key_metrics": {
                "project_irr_pre_tax": round(self.project_irr_pre_tax, 6),
                "project_irr_post_tax": round(self.project_irr_post_tax, 6),
                "project_npv_pre_tax_6pct": round(self.project_npv_pre_tax, 2),
                "project_npv_post_tax_6pct": round(self.project_npv_post_tax, 2),
                "equity_irr": round(self.equity_irr, 6),
                "equity_npv_8pct": round(self.equity_npv, 2),
                "equity_payback_months": self.equity_payback_month,
                "equity_payback_years": round(self.equity_payback_month / 12, 1),
                "lcoe_aud_mwh": round(self.lcoe, 2),
                "lcos_aud_mwh": round(self.lcos, 2),
                "blended_lcoe_aud_mwh": self.lcoe_lcos_breakdown.get("blended_lcoe_aud_mwh", 0),
                "lcoe_discounted_aud_mwh": self.lcoe_lcos_breakdown.get("lcoe_discounted_aud_mwh", 0),
                "lcos_discounted_aud_mwh": self.lcoe_lcos_breakdown.get("lcos_discounted_aud_mwh", 0),
                "blended_discounted_aud_mwh": self.lcoe_lcos_breakdown.get("blended_discounted_aud_mwh", 0),
                "currency": self.inputs.currency
            },
            "funding_structure": {
                "total_sources_k": cap_struct["total_sources_k"],
                "committed_equity_k": cap_struct["total_equity_k"],
                "committed_equity_pct": round(self.inputs.financing.gearing_pct, 4),
                "senior_debt_k": cap_struct["total_debt_k"],
                "senior_debt_pct": round(1 - self.inputs.financing.gearing_pct, 4),
                "bess_capex_k": cap_struct["bess_capex_k"],
                "pv_capex_k": cap_struct["pv_capex_k"],
                "idc_k": cap_struct["idc_k"],
                "financing_fees_k": cap_struct["financing_fees_k"],
                "dsra_k": cap_struct["dsra_k"],
                "gearing_pct": round(self.inputs.financing.gearing_pct, 4)
            },
            "debt_ratios": {
                "min_dscr": round(self.min_dscr, 4),
                "average_dscr": round(self.avg_dscr, 4)
            },
            "annual_data": self.annual_summary,
            "lcoe_lcos_breakdown": self.lcoe_lcos_breakdown if hasattr(self, 'lcoe_lcos_breakdown') else {},
            "validation_warnings": self.validation_warnings if hasattr(self, 'validation_warnings') else [],
            "charts_generated": [],
            "extraction_metadata": {
                "source": "solar_financial_engine.py",
                "engine_version": "1.0.0",
                "generated_at": datetime.datetime.now().isoformat(),
                "total_months": self.total_months
            }
        }


# ═══════════════════════════════════════════════════════════════════════
# 场景管理器
# ═══════════════════════════════════════════════════════════════════════


class ScenarioManager:
    """多场景管理器"""

    def __init__(self):
        self.scenarios: Dict[str, ProjectInput] = {}
        self.results: Dict[str, dict] = {}

    def add_scenario(self, name: str, inputs: ProjectInput):
        """添加场景"""
        inputs.scenario_name = name
        self.scenarios[name] = inputs

    def remove_scenario(self, name: str):
        if name in self.scenarios:
            del self.scenarios[name]
        if name in self.results:
            del self.results[name]

    def run_all(self) -> Dict[str, dict]:
        """运行所有场景"""
        self.results = {}
        for name, inputs in self.scenarios.items():
            model = MonthlyFinancialModel(inputs)
            self.results[name] = model.run()
        return self.results

    def compare_metrics(self) -> dict:
        """对比各场景的关键指标"""
        comparison = {}
        for name, result in self.results.items():
            km = result.get("key_metrics", {})
            comparison[name] = {
                "project_irr": km.get("project_irr_post_tax", 0),
                "equity_irr": km.get("equity_irr", 0),
                "project_npv": km.get("project_npv_post_tax_6pct", 0),
                "equity_npv": km.get("equity_npv_8pct", 0),
                "payback_years": km.get("equity_payback_years", 0),
                "lcos": km.get("lcos_aud_mwh", 0),
                "min_dscr": result.get("debt_ratios", {}).get("min_dscr", 0)
            }
        return comparison


# ═══════════════════════════════════════════════════════════════════════
# 内置示例场景 - 澳洲典型 BESS 项目
# ═══════════════════════════════════════════════════════════════════════


def create_default_bess_scenario() -> ProjectInput:
    """创建澳洲典型 BESS 项目（40MW/160MWh）"""
    return ProjectInput(
        name="Stanhope BESS",
        location="VIC, Australia",
        currency="AUD",
        scenario_name="Base Case - 40MW 4h BESS",
        timeline=TimelineInput(
            construction_start="2026-01-01",
            construction_months=24,
            operation_years=20
        ),
        technology=TechnologyInput(
            pv_capacity_mwp=0,
            bess_capacity_mw=40,
            bess_duration_hrs=4,
            bess_degradation_pa=0.02,
            bess_rte=0.90
        ),
        capex=CapexInput(
            pv_capex_per_kwp=0,
            bess_capex_per_kw=900,  # $900/kW (2026 市场参考)
            bop_epc_pct=0.10,
            development_cost=2000,  # $2M
            contingency_pct=0.05
        ),
        opex=OpexInput(
            bess_fixed_per_kw_year=20,  # $20/kW/yr
            escalation_rate=0.02
        ),
        revenue=RevenueInput(
            merchant_price_aud_mwh=80,  # $80/MWh 现货
            fcas_revenue_aud_kw_year=25,  # $25/kW/yr FCAS
            revenue_escalation=0.0
        ),
        financing=FinancingInput(
            gearing_pct=0.60,
            interest_rate_pa=0.06,
            debt_tenor_years=15,
            dsra_months=6,
            financing_fees_pct=0.025
        ),
        tax=TaxInput(
            corporate_tax_rate=0.30,
            depreciation_method="SL",
            bess_effective_life_years=15
        ),
        mid_life=MidLifeInput(
            battery_replace_year=12,
            battery_replace_cost_pct=0.65
        ),
        generation=GenerationProfile(
            bess_cycles_per_day=1.0
        )
    )


def create_default_solar_scenario() -> ProjectInput:
    """创建澳洲典型光伏项目（100MW）"""
    return ProjectInput(
        name="Solar Farm",
        location="NSW, Australia",
        currency="AUD",
        scenario_name="Base Case - 100MW Solar PV",
        timeline=TimelineInput(
            construction_start="2026-07-01",
            construction_months=18,
            operation_years=25
        ),
        technology=TechnologyInput(
            pv_capacity_mwp=100,
            bess_capacity_mw=0,
            pv_degradation_pa=0.005
        ),
        capex=CapexInput(
            pv_capex_per_kwp=1300,  # $1,300/kWp
            bop_epc_pct=0.12,
            development_cost=3000,
            contingency_pct=0.05
        ),
        opex=OpexInput(
            pv_fixed_per_kwp_year=15,
            escalation_rate=0.02
        ),
        revenue=RevenueInput(
            ppa_price_aud_mwh=60,
            ppa_percentage=0.80,
            merchant_price_aud_mwh=50,
            lgc_price_aud=40,
            lgc_rate_per_mwh=1.0,
            revenue_escalation=0.0
        ),
        financing=FinancingInput(
            gearing_pct=0.65,
            interest_rate_pa=0.055,
            debt_tenor_years=18
        ),
        tax=TaxInput(
            corporate_tax_rate=0.30,
            depreciation_method="SL",
            pv_effective_life_years=20
        ),
        mid_life=MidLifeInput(
            inverter_replace_year=15,
            inverter_replace_cost_pct=0.12
        ),
        generation=GenerationProfile(
            pv_cf_monthly=[0.18, 0.19, 0.20, 0.21, 0.22, 0.23,
                           0.22, 0.21, 0.20, 0.19, 0.18, 0.17]
        )
    )


# ═══════════════════════════════════════════════════════════════════════
# CLI 接口
# ═══════════════════════════════════════════════════════════════════════


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="澳洲光伏/储能项目财务模型引擎",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--scenarios", "-s", help="场景定义 JSON 文件")
    parser.add_argument("--output", "-o", default="OUTPUT/solar_engine_results.json",
                        help="输出文件路径 (默认: OUTPUT/solar_engine_results.json)")
    parser.add_argument("--demo", "-d", action="store_true",
                        help="运行内置示例场景")
    parser.add_argument("--compare", "-c", action="store_true",
                        help="输出场景对比表")

    args = parser.parse_args()

    manager = ScenarioManager()

    if args.demo:
        print("🏭 运行内置示例场景...")
        manager.add_scenario("BESS Base", create_default_bess_scenario())
        manager.add_scenario("Solar PV Base", create_default_solar_scenario())

        # 添加变体场景
        bess_optimistic = create_default_bess_scenario()
        bess_optimistic.scenario_name = "BESS Optimistic"
        bess_optimistic.revenue.merchant_price_aud_mwh = 100
        bess_optimistic.capex.bess_capex_per_kw = 750
        manager.add_scenario("BESS Optimistic", bess_optimistic)

        bess_conservative = create_default_bess_scenario()
        bess_conservative.scenario_name = "BESS Conservative"
        bess_conservative.revenue.merchant_price_aud_mwh = 60
        bess_conservative.capex.bess_capex_per_kw = 1050
        manager.add_scenario("BESS Conservative", bess_conservative)

    elif args.scenarios:
        with open(args.scenarios, "r") as f:
            scenarios_data = json.load(f)
        for name, params in scenarios_data.items():
            inputs = ProjectInput(**params)
            manager.add_scenario(name, inputs)
    else:
        parser.print_help()
        return

    # 执行计算
    results = manager.run_all()

    for name, result in results.items():
        km = result.get("key_metrics", {})
        print(f"\n📊 {name}")
        print(f"   项目 IRR: {km.get('project_irr_post_tax', 0)*100:.2f}%")
        print(f"   股权 IRR: {km.get('equity_irr', 0)*100:.2f}%")
        print(f"   项目 NPV: ${km.get('project_npv_post_tax_6pct', 0):,.0f}k")
        print(f"   股权 NPV: ${km.get('equity_npv_8pct', 0):,.0f}k")
        print(f"   回收期: {km.get('equity_payback_years', 0):.1f} 年")
        print(f"   LCOS: ${km.get('lcos_aud_mwh', 0):.0f}/MWh")
        print(f"   Min DSCR: {result.get('debt_ratios', {}).get('min_dscr', 0):.2f}x")

    if args.compare:
        print("\n\n📋 场景对比")
        comparison = manager.compare_metrics()
        header = f"{'场景':<20} {'IRR':>8} {'Eq IRR':>8} {'NPV(k)':>10} {'Eq NPV':>10} {'回本':>6} {'LCOS':>8} {'DSCR':>6}"
        print(header)
        print("-" * len(header))
        for name, m in comparison.items():
            print(f"{name:<20} {m['project_irr']*100:>7.1f}% {m['equity_irr']*100:>7.1f}% "
                  f"${m['project_npv']:>8,.0f} ${m['equity_npv']:>8,.0f} "
                  f"{m['payback_years']:>5.1f}y ${m['lcos']:>7.0f} {m['min_dscr']:>5.2f}x")

    # 保存结果
    import os
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    output_data = {
        "results": results,
        "comparison": manager.compare_metrics() if args.compare or args.demo else {}
    }
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n✅ 结果已保存到: {args.output}")


if __name__ == "__main__":
    main()
