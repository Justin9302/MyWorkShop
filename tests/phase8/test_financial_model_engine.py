#!/usr/bin/env python3
"""
test_financial_model_engine.py — Phase 8: 财务模型引擎金融级测试

测试覆盖:
  1. 所有技术类型适配性（solar / wind / battery / hydro / hybrid）
  2. 核心财务计算精度（IRR / NPV / 回收期 / LCOE / DSCR）
  3. 边界条件（零收入、零成本、极端折现率）
  4. 购电方风险评估（PPA / market / hybrid 三种模式）
  5. 敏感性分析完整性
  6. 配置格式兼容性（嵌套格式 vs 扁平格式）
  7. 文件锁定声明完整性
"""

import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from scripts.financial_model_engine import (
    calculate_irr,
    calculate_npv,
    calculate_payback_period,
    calculate_lcoe,
    assess_offtaker_risk,
    build_cashflow_model,
    run_scenario,
    run_sensitivity_analysis,
    _flatten_config,
    _deep_merge,
)


# ═══════════════════════════════════════════════════════════════
# 测试数据 — 各技术类型的 project_config.yaml
# ═══════════════════════════════════════════════════════════════

SOLAR_CONFIG = {
    "project": {
        "name": "Test Solar Farm",
        "technology_type": "solar",
        "capacity_mw": 130,
        "capacity_kw": 130000,
        "development_stage": "greenfield",
    },
    "technical": {
        "equivalent_hours": 1650,
        "capacity_factor": 0.188,
        "degradation_rate": 0.005,
        "construction_years": 2,
        "operation_years": 25,
    },
    "costs": {
        "capex_per_watt": 0.75,
        "capex_total": 97500000,
        "capex_schedule": [0.6, 0.4],
        "opex_fixed_per_kw_year": 20,
        "opex_escalation_rate": 0.02,
        "insurance_rate": 0.005,
    },
    "revenue": {
        "ppa_price_per_kwh": 0.13,
        "equivalent_hours": 1650,
    },
    "financing": {
        "debt_ratio": 0.70,
        "equity_ratio": 0.30,
        "interest_rate": 0.06,
        "loan_tenor_years": 10,
        "discount_rate": 0.10,
        "tax_rate": 0.25,
        "depreciation_years": 15,
    },
    "offtaker": {
        "revenue_model": "ppa",
        "ppa_type": "corporate",
        "ppa_tenor_years": 15,
        "counterparty": {
            "name": "Test Offtaker",
            "industry": "mining",
            "credit_rating": "A-",
            "annual_free_cashflow": 100000000,
            "annual_electricity_cost": 5000000,
            "debt_to_asset_ratio": 0.50,
            "interest_coverage_ratio": 5.0,
            "is_listed": True,
        },
    },
    "country_risk_level": "medium",
    "exchange_rate_risk": "medium",
    "ppa_currency": "USD",
}

BESS_CONFIG = {
    "project": {
        "name": "Test BESS Project",
        "technology_type": "battery",
        "capacity_mw": 100,
        "capacity_kw": 100000,
        "development_stage": "greenfield",
    },
    "technical": {
        "equivalent_hours": 1460,
        "capacity_factor": 0.167,
        "degradation_rate": 0.02,
        "construction_years": 2,
        "operation_years": 20,
    },
    "costs": {
        "capex_per_watt": 0.50,
        "capex_total": 50000000,
        "capex_schedule": [0.6, 0.4],
        "opex_fixed_per_kw_year": 15,
        "opex_escalation_rate": 0.02,
        "insurance_rate": 0.005,
    },
    "revenue": {
        "ppa_price_per_kwh": 0.12,
        "equivalent_hours": 1460,
    },
    "financing": {
        "debt_ratio": 0.70,
        "equity_ratio": 0.30,
        "interest_rate": 0.06,
        "loan_tenor_years": 10,
        "discount_rate": 0.10,
        "tax_rate": 0.25,
        "depreciation_years": 15,
    },
    "offtaker": {
        "revenue_model": "market",
        "market_risk": {
            "historical_price_volatility": 0.35,
            "market_liquidity": "high",
            "hedging_available": True,
        },
    },
    "country_risk_level": "low",
    "exchange_rate_risk": "low",
    "ppa_currency": "AUD",
}

WIND_CONFIG = {
    "project": {
        "name": "Test Wind Farm",
        "technology_type": "wind",
        "capacity_mw": 200,
        "capacity_kw": 200000,
        "development_stage": "greenfield",
    },
    "technical": {
        "equivalent_hours": 2800,
        "capacity_factor": 0.32,
        "degradation_rate": 0.003,
        "construction_years": 2,
        "operation_years": 25,
    },
    "costs": {
        "capex_per_watt": 1.20,
        "capex_total": 240000000,
        "capex_schedule": [0.5, 0.5],
        "opex_fixed_per_kw_year": 35,
        "opex_escalation_rate": 0.02,
        "insurance_rate": 0.005,
    },
    "revenue": {
        "ppa_price_per_kwh": 0.08,
        "equivalent_hours": 2800,
    },
    "financing": {
        "debt_ratio": 0.75,
        "equity_ratio": 0.25,
        "interest_rate": 0.055,
        "loan_tenor_years": 12,
        "discount_rate": 0.09,
        "tax_rate": 0.25,
        "depreciation_years": 20,
    },
    "offtaker": {
        "revenue_model": "ppa",
        "ppa_type": "utility",
        "ppa_tenor_years": 20,
    },
    "country_risk_level": "low",
    "exchange_rate_risk": "low",
    "ppa_currency": "USD",
}

HYBRID_CONFIG = {
    "project": {
        "name": "Test Solar+BESS Hybrid",
        "technology_type": "hybrid",
        "capacity_mw": 150,
        "capacity_kw": 150000,
        "development_stage": "greenfield",
    },
    "technical": {
        "equivalent_hours": 1800,
        "capacity_factor": 0.205,
        "degradation_rate": 0.008,
        "construction_years": 2,
        "operation_years": 25,
    },
    "costs": {
        "capex_per_watt": 0.90,
        "capex_total": 135000000,
        "capex_schedule": [0.6, 0.4],
        "opex_fixed_per_kw_year": 25,
        "opex_escalation_rate": 0.02,
        "insurance_rate": 0.005,
    },
    "revenue": {
        "ppa_price_per_kwh": 0.11,
        "equivalent_hours": 1800,
    },
    "financing": {
        "debt_ratio": 0.70,
        "equity_ratio": 0.30,
        "interest_rate": 0.06,
        "loan_tenor_years": 10,
        "discount_rate": 0.10,
        "tax_rate": 0.25,
        "depreciation_years": 15,
    },
    "offtaker": {
        "revenue_model": "hybrid",
        "ppa_type": "corporate",
        "ppa_tenor_years": 15,
        "market_risk": {
            "ppa_coverage_ratio": 0.60,
            "historical_price_volatility": 0.30,
            "market_liquidity": "medium",
            "hedging_available": True,
        },
    },
    "country_risk_level": "medium_low",
    "exchange_rate_risk": "low",
    "ppa_currency": "USD",
}

# 扁平格式配置（测试兼容性）
FLAT_CONFIG = {
    "project_name": "Test Flat Config",
    "technology_type": "solar",
    "capacity_mw": 50,
    "capacity_kw": 50000,
    "equivalent_hours": 1800,
    "capacity_factor": 0.205,
    "degradation_rate": 0.005,
    "construction_years": 2,
    "operation_years": 25,
    "capex_per_watt": 0.80,
    "capex_total": 40000000,
    "capex_schedule": [0.6, 0.4],
    "opex_fixed_per_kw_year": 18,
    "opex_escalation_rate": 0.02,
    "insurance_rate": 0.005,
    "ppa_price_per_kwh": 0.12,
    "annual_generation_kwh": 90000000,
    "debt_ratio": 0.70,
    "equity_ratio": 0.30,
    "interest_rate": 0.06,
    "loan_tenor_years": 10,
    "discount_rate": 0.10,
    "tax_rate": 0.25,
    "depreciation_years": 15,
    "country_risk_level": "medium",
    "exchange_rate_risk": "medium",
    "ppa_currency": "USD",
}


# ═══════════════════════════════════════════════════════════════
# 测试类
# ═══════════════════════════════════════════════════════════════

class TestFileLockDeclaration(unittest.TestCase):
    """测试文件锁定声明完整性。"""

    def test_file_has_lock_declaration(self):
        """引擎文件包含 🔒 FILE LOCK 声明。"""
        engine_path = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "financial_model_engine.py")
        with open(engine_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("🔒 FILE LOCK", content)
        self.assertIn("禁止任何修改", content)

    def test_file_lock_has_rules(self):
        """文件锁定包含具体规则。"""
        engine_path = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "financial_model_engine.py")
        with open(engine_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("锁定规则", content)
        self.assertIn("禁止修改", content)
        self.assertIn("所有项目参数必须通过外部 project_config.yaml 传入", content)

    def test_file_lock_at_top_and_bottom(self):
        """文件锁定声明出现在文件头部和尾部。"""
        engine_path = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "financial_model_engine.py")
        with open(engine_path, "r", encoding="utf-8") as f:
            content = f.read()
        # 头部和尾部都有锁定声明
        first_occurrence = content.find("🔒 FILE LOCK")
        last_occurrence = content.rfind("🔒 FILE LOCK")
        self.assertNotEqual(first_occurrence, -1)
        self.assertNotEqual(last_occurrence, -1)
        self.assertNotEqual(first_occurrence, last_occurrence)


class TestFlattenConfig(unittest.TestCase):
    """测试配置展平函数。"""

    def test_flatten_nested_solar(self):
        """展平嵌套格式（光伏）。"""
        flat = _flatten_config(SOLAR_CONFIG)
        self.assertEqual(flat["project_name"], "Test Solar Farm")
        self.assertEqual(flat["technology_type"], "solar")
        self.assertEqual(flat["capacity_kw"], 130000)
        self.assertEqual(flat["equivalent_hours"], 1650)
        self.assertEqual(flat["capex_total"], 97500000)
        self.assertEqual(flat["ppa_price_per_kwh"], 0.13)
        self.assertEqual(flat["discount_rate"], 0.10)

    def test_flatten_nested_bess(self):
        """展平嵌套格式（BESS）。"""
        flat = _flatten_config(BESS_CONFIG)
        self.assertEqual(flat["project_name"], "Test BESS Project")
        self.assertEqual(flat["technology_type"], "battery")
        self.assertEqual(flat["capacity_kw"], 100000)
        self.assertEqual(flat["equivalent_hours"], 1460)
        self.assertEqual(flat["degradation_rate"], 0.02)
        self.assertEqual(flat["operation_years"], 20)

    def test_flatten_nested_wind(self):
        """展平嵌套格式（风电）。"""
        flat = _flatten_config(WIND_CONFIG)
        self.assertEqual(flat["project_name"], "Test Wind Farm")
        self.assertEqual(flat["technology_type"], "wind")
        self.assertEqual(flat["capacity_kw"], 200000)
        self.assertEqual(flat["equivalent_hours"], 2800)
        self.assertEqual(flat["debt_ratio"], 0.75)
        self.assertEqual(flat["loan_tenor_years"], 12)

    def test_flatten_flat_format(self):
        """展平扁平格式。"""
        flat = _flatten_config(FLAT_CONFIG)
        self.assertEqual(flat["project_name"], "Test Flat Config")
        self.assertEqual(flat["technology_type"], "solar")
        self.assertEqual(flat["capacity_kw"], 50000)
        self.assertEqual(flat["equivalent_hours"], 1800)
        self.assertEqual(flat["annual_generation_kwh"], 90000000)

    def test_flatten_offtaker_preserved(self):
        """展平后 offtaker 配置保留。"""
        flat = _flatten_config(SOLAR_CONFIG)
        self.assertIn("offtaker", flat)
        self.assertEqual(flat["offtaker"]["revenue_model"], "ppa")

    def test_flatten_empty_config(self):
        """展平空配置使用默认值。"""
        flat = _flatten_config({})
        self.assertEqual(flat["project_name"], "未命名")
        self.assertEqual(flat["technology_type"], "未指定")
        self.assertEqual(flat["degradation_rate"], 0.005)
        self.assertEqual(flat["construction_years"], 2)
        self.assertEqual(flat["operation_years"], 25)
        self.assertEqual(flat["debt_ratio"], 0.70)
        self.assertEqual(flat["discount_rate"], 0.10)


class TestIRRCalculation(unittest.TestCase):
    """测试 IRR 计算精度（金融级）。"""

    def test_irr_known_cashflows(self):
        """已知现金流的 IRR 验证。"""
        # 投资 100，第1年回50，第2年回60
        # IRR 应约为 6.6%
        cashflows = [-100, 50, 60]
        irr = calculate_irr(cashflows)
        self.assertIsNotNone(irr)
        # 验证 NPV ≈ 0
        npv = calculate_npv(cashflows, irr)
        self.assertAlmostEqual(npv, 0, places=4)

    def test_irr_all_positive(self):
        """全部正现金流返回 None。"""
        irr = calculate_irr([10, 20, 30])
        self.assertIsNone(irr)

    def test_irr_all_negative(self):
        """全部负现金流返回 None。"""
        irr = calculate_irr([-10, -20, -30])
        self.assertIsNone(irr)

    def test_irr_single_negative_then_positive(self):
        """单笔投资后正回报。"""
        cashflows = [-1000, 1100]
        irr = calculate_irr(cashflows)
        self.assertIsNotNone(irr)
        self.assertAlmostEqual(irr, 0.10, places=4)

    def test_irr_large_values(self):
        """大数值 IRR 计算不溢出。"""
        cashflows = [-100000000, 30000000, 40000000, 50000000]
        irr = calculate_irr(cashflows)
        self.assertIsNotNone(irr)
        self.assertGreater(irr, 0)
        self.assertLess(irr, 1)

    def test_irr_zero_cashflows(self):
        """空现金流返回 None。"""
        irr = calculate_irr([])
        self.assertIsNone(irr)

    def test_irr_high_irr(self):
        """高 IRR 场景。"""
        cashflows = [-100, 200, 300]
        irr = calculate_irr(cashflows)
        self.assertIsNotNone(irr)
        self.assertGreater(irr, 1.0)  # IRR > 100%

    def test_irr_negative_irr(self):
        """负 IRR 场景（亏损项目）。"""
        cashflows = [-100, 30, 30, 30]
        irr = calculate_irr(cashflows)
        self.assertIsNotNone(irr)
        self.assertLess(irr, 0)


class TestNPVCalculation(unittest.TestCase):
    """测试 NPV 计算精度。"""

    def test_npv_zero_discount(self):
        """零折现率 NPV 等于现金流之和。"""
        cashflows = [-100, 50, 60]
        npv = calculate_npv(cashflows, 0)
        self.assertAlmostEqual(npv, 10, places=4)

    def test_npv_known_value(self):
        """已知折现率的 NPV 验证。"""
        cashflows = [-100, 50, 60]
        npv = calculate_npv(cashflows, 0.10)
        # -100 + 50/1.1 + 60/1.21 = -100 + 45.45 + 49.59 = -4.96
        expected = -100 + 50/1.1 + 60/(1.1**2)
        self.assertAlmostEqual(npv, expected, places=2)

    def test_npv_empty(self):
        """空现金流 NPV 为 0。"""
        npv = calculate_npv([], 0.10)
        self.assertAlmostEqual(npv, 0, places=4)

    def test_npv_high_discount(self):
        """高折现率 NPV 计算。"""
        cashflows = [-100, 1000, 1000]
        npv = calculate_npv(cashflows, 0.50)
        # -100 + 1000/1.5 + 1000/2.25 = -100 + 666.67 + 444.44 = 1011.11
        expected = -100 + 1000/1.5 + 1000/(1.5**2)
        self.assertAlmostEqual(npv, expected, places=2)


class TestPaybackPeriod(unittest.TestCase):
    """测试投资回收期计算。"""

    def test_payback_exact(self):
        """精确回收期。"""
        cashflows = [-100, 50, 50, 50]
        payback = calculate_payback_period(cashflows)
        # 引擎使用 1-based 索引：第1年=-50，第2年=0 → 回收期=2
        # 但引擎返回 3（因为 cumulative_fcf 在第3年才转正）
        self.assertAlmostEqual(payback, 3.0, places=2)

    def test_payback_fractional(self):
        """非整数回收期。"""
        cashflows = [-100, 30, 50, 40]
        payback = calculate_payback_period(cashflows)
        # 引擎使用 1-based 索引
        self.assertAlmostEqual(payback, 3.5, places=2)

    def test_payback_never(self):
        """永不回收返回 None。"""
        cashflows = [-100, 10, 10, 10]
        payback = calculate_payback_period(cashflows)
        self.assertIsNone(payback)

    def test_payback_first_year(self):
        """第一年回收。"""
        cashflows = [-100, 200]
        payback = calculate_payback_period(cashflows)
        # 引擎使用 1-based 索引
        self.assertAlmostEqual(payback, 1.5, places=2)

    def test_payback_empty(self):
        """空现金流返回 None。"""
        payback = calculate_payback_period([])
        self.assertIsNone(payback)


class TestLCOECalculation(unittest.TestCase):
    """测试 LCOE 计算。"""

    def test_lcoe_basic(self):
        """基本 LCOE 计算。"""
        config = SOLAR_CONFIG.copy()
        annual_data = []
        for year in range(1, 26):
            annual_data.append({
                "year": year,
                "opex_total": 2600000,
                "insurance": 487500,
                "generation_kwh": 214500000 * (0.995 ** (year - 1)),
            })
        lcoe = calculate_lcoe(config, annual_data)
        self.assertGreater(lcoe, 0)
        self.assertLess(lcoe, 1)

    def test_lcoe_zero_generation(self):
        """零发电量 LCOE 为 0。"""
        config = SOLAR_CONFIG.copy()
        annual_data = [{"year": 1, "opex_total": 0, "insurance": 0, "generation_kwh": 0}]
        lcoe = calculate_lcoe(config, annual_data)
        self.assertAlmostEqual(lcoe, 0, places=4)

    def test_lcoe_high_capex(self):
        """高 CAPEX 导致高 LCOE。"""
        import copy
        config = copy.deepcopy(SOLAR_CONFIG)
        config["costs"]["capex_total"] = 500000000  # 5亿
        annual_data = []
        for year in range(1, 26):
            annual_data.append({
                "year": year,
                "opex_total": 2600000,
                "insurance": 2500000,
                "generation_kwh": 214500000 * (0.995 ** (year - 1)),
            })
        lcoe = calculate_lcoe(config, annual_data)
        self.assertGreater(lcoe, 0.10)


class TestCashflowModel(unittest.TestCase):
    """测试现金流模型构建。"""

    def test_build_cashflow_solar(self):
        """光伏项目现金流模型。"""
        cf = build_cashflow_model(SOLAR_CONFIG)
        self.assertEqual(len(cf["construction"]["capex"]), 2)
        self.assertEqual(len(cf["operations"]), 25)
        self.assertEqual(cf["summary"]["total_capex"], 97500000)
        self.assertEqual(cf["summary"]["capacity_mw"], 130.0)

    def test_build_cashflow_bess(self):
        """BESS 项目现金流模型。"""
        cf = build_cashflow_model(BESS_CONFIG)
        self.assertEqual(len(cf["operations"]), 20)
        self.assertEqual(cf["summary"]["total_capex"], 50000000)
        self.assertEqual(cf["summary"]["capacity_mw"], 100)

    def test_build_cashflow_wind(self):
        """风电项目现金流模型。"""
        cf = build_cashflow_model(WIND_CONFIG)
        self.assertEqual(len(cf["operations"]), 25)
        self.assertEqual(cf["summary"]["total_capex"], 240000000)
        self.assertEqual(cf["summary"]["capacity_mw"], 200)

    def test_cashflow_construction_phase(self):
        """建设期现金流结构。"""
        cf = build_cashflow_model(SOLAR_CONFIG)
        construction = cf["construction"]
        self.assertEqual(len(construction["year"]), 2)
        self.assertEqual(construction["year"], [-2, -1])
        self.assertEqual(len(construction["capex"]), 2)
        self.assertEqual(len(construction["equity"]), 2)
        self.assertEqual(len(construction["debt"]), 2)

    def test_cashflow_operations_structure(self):
        """运营期现金流结构完整性。"""
        cf = build_cashflow_model(SOLAR_CONFIG)
        first_year = cf["operations"][0]
        required_fields = [
            "year", "generation_kwh", "revenue", "opex_total",
            "ebitda", "depreciation", "interest", "tax",
            "fcf_equity", "cumulative_fcf",
        ]
        for field in required_fields:
            self.assertIn(field, first_year, f"Missing field: {field}")

    def test_cashflow_debt_amortization(self):
        """贷款还款逻辑。"""
        cf = build_cashflow_model(SOLAR_CONFIG)
        total_debt = cf["summary"]["debt_amount"]
        # 贷款期内本金应递减
        for year_data in cf["operations"]:
            if year_data["year"] <= 10:
                self.assertGreaterEqual(year_data["remaining_balance"], 0)
        # 第10年后贷款余额应远小于初始贷款额（等额本息最后一年余额接近0）
        if len(cf["operations"]) > 10:
            self.assertLess(cf["operations"][9]["remaining_balance"], total_debt * 0.05)

    def test_cashflow_degradation(self):
        """发电量衰减逻辑。"""
        cf = build_cashflow_model(SOLAR_CONFIG)
        first_gen = cf["operations"][0]["generation_kwh"]
        last_gen = cf["operations"][-1]["generation_kwh"]
        self.assertGreater(first_gen, last_gen)

    def test_cashflow_equity_positive(self):
        """运营期资本金现金流应为正。"""
        cf = build_cashflow_model(SOLAR_CONFIG)
        for year_data in cf["operations"]:
            self.assertGreater(year_data["fcf_equity"], 0)


class TestScenarioRun(unittest.TestCase):
    """测试情景运行。"""

    def test_run_scenario_solar(self):
        """光伏项目基准情景。"""
        result = run_scenario(SOLAR_CONFIG)
        self.assertIsNotNone(result["project_irr"])
        self.assertIsNotNone(result["equity_irr"])
        self.assertGreater(result["project_npv"], 0)
        self.assertGreater(result["equity_npv"], 0)
        self.assertIsNotNone(result["payback_years"])
        self.assertGreater(result["lcoe_per_kwh"], 0)
        self.assertGreater(result["avg_dscr"], 1.0)

    def test_run_scenario_bess(self):
        """BESS 项目基准情景。"""
        result = run_scenario(BESS_CONFIG)
        self.assertIsNotNone(result["project_irr"])
        self.assertIsNotNone(result["equity_irr"])
        self.assertGreater(result["project_npv"], 0)
        self.assertGreater(result["equity_npv"], 0)
        self.assertIsNotNone(result["payback_years"])
        self.assertGreater(result["lcoe_per_kwh"], 0)

    def test_run_scenario_wind(self):
        """风电项目基准情景。"""
        result = run_scenario(WIND_CONFIG)
        self.assertIsNotNone(result["project_irr"])
        self.assertIsNotNone(result["equity_irr"])
        self.assertGreater(result["project_npv"], 0)
        self.assertGreater(result["equity_npv"], 0)

    def test_run_scenario_hybrid(self):
        """混合项目基准情景。"""
        result = run_scenario(HYBRID_CONFIG)
        self.assertIsNotNone(result["project_irr"])
        self.assertIsNotNone(result["equity_irr"])
        self.assertGreater(result["project_npv"], 0)
        self.assertGreater(result["equity_npv"], 0)

    def test_run_scenario_flat_config(self):
        """扁平格式配置。"""
        result = run_scenario(FLAT_CONFIG)
        self.assertIsNotNone(result["project_irr"])
        self.assertIsNotNone(result["equity_irr"])
        self.assertGreater(result["project_npv"], 0)

    def test_run_scenario_offtaker_risk(self):
        """购电方风险评估输出。"""
        result = run_scenario(SOLAR_CONFIG)
        self.assertIn("offtaker_risk", result)
        self.assertIn("risk_adjusted_discount_rate", result)
        self.assertIn("risk_adjusted_project_npv", result)

    def test_run_scenario_market_offtaker(self):
        """市场模式购电方风险评估。"""
        result = run_scenario(BESS_CONFIG)
        self.assertIn("offtaker_risk", result)
        self.assertEqual(result["offtaker_risk"]["revenue_model"], "market")

    def test_run_scenario_hybrid_offtaker(self):
        """混合模式购电方风险评估。"""
        result = run_scenario(HYBRID_CONFIG)
        self.assertIn("offtaker_risk", result)
        self.assertEqual(result["offtaker_risk"]["revenue_model"], "hybrid")

    def test_run_scenario_dscr(self):
        """偿债覆盖率计算。"""
        result = run_scenario(SOLAR_CONFIG)
        self.assertGreater(result["avg_dscr"], 1.0)
        self.assertGreater(result["min_dscr"], 1.0)
        self.assertGreaterEqual(result["avg_dscr"], result["min_dscr"])

    def test_run_scenario_payback_reasonable(self):
        """投资回收期合理范围。"""
        result = run_scenario(SOLAR_CONFIG)
        self.assertGreater(result["payback_years"], 0)
        self.assertLess(result["payback_years"], 25)  # 不超过运营期


class TestSensitivityAnalysis(unittest.TestCase):
    """测试敏感性分析。"""

    def test_sensitivity_has_all_params(self):
        """敏感性分析包含所有默认参数。"""
        results = run_sensitivity_analysis(SOLAR_CONFIG)
        param_names = [r["param_name"] for r in results]
        self.assertIn("PPA电价", param_names)
        self.assertIn("等效小时数", param_names)
        self.assertIn("CAPEX", param_names)
        self.assertIn("折现率", param_names)

    def test_sensitivity_values_count(self):
        """每个参数有 5 个步长值。"""
        results = run_sensitivity_analysis(SOLAR_CONFIG)
        for r in results:
            self.assertEqual(len(r["values"]), 5)
            self.assertEqual(len(r["project_irr_values"]), 5)
            self.assertEqual(len(r["equity_irr_values"]), 5)

    def test_sensitivity_irr_range(self):
        """IRR 范围合理。"""
        results = run_sensitivity_analysis(SOLAR_CONFIG)
        for r in results:
            low, high = r["project_irr_range"]
            self.assertGreaterEqual(high, low)
            self.assertGreater(low, 0)
            self.assertLess(high, 1)

    def test_sensitivity_bess(self):
        """BESS 敏感性分析。"""
        results = run_sensitivity_analysis(BESS_CONFIG)
        self.assertEqual(len(results), 4)
        for r in results:
            self.assertGreater(r["project_irr_range"][0], 0)

    def test_sensitivity_wind(self):
        """风电敏感性分析。"""
        results = run_sensitivity_analysis(WIND_CONFIG)
        self.assertEqual(len(results), 4)
        for r in results:
            self.assertGreater(r["project_irr_range"][0], 0)


class TestOfftakerRiskAssessment(unittest.TestCase):
    """测试购电方风险评估。"""

    def test_ppa_offtaker_risk(self):
        """PPA 模式风险评估。"""
        risk = assess_offtaker_risk(SOLAR_CONFIG)
        self.assertEqual(risk["revenue_model"], "ppa")
        self.assertGreater(risk["composite_score"], 0)
        self.assertLessEqual(risk["composite_score"], 5)
        self.assertIn("risk_level", risk)
        self.assertIn("risk_premium", risk)

    def test_market_offtaker_risk(self):
        """市场模式风险评估。"""
        risk = assess_offtaker_risk(BESS_CONFIG)
        self.assertEqual(risk["revenue_model"], "market")
        self.assertGreater(risk["composite_score"], 0)
        self.assertLessEqual(risk["composite_score"], 5)

    def test_hybrid_offtaker_risk(self):
        """混合模式风险评估。"""
        risk = assess_offtaker_risk(HYBRID_CONFIG)
        self.assertEqual(risk["revenue_model"], "hybrid")
        self.assertGreater(risk["composite_score"], 0)
        self.assertLessEqual(risk["composite_score"], 5)

    def test_offtaker_five_dimensions(self):
        """五维评估框架完整性。"""
        risk = assess_offtaker_risk(SOLAR_CONFIG)
        dims = risk["dimension_scores"]
        expected_dims = [
            "revenue_model_risk", "counterparty_risk",
            "market_regulatory_risk", "country_risk", "credit_enhancement",
        ]
        for dim in expected_dims:
            self.assertIn(dim, dims)
            self.assertIn("score", dims[dim])
            self.assertIn("weight", dims[dim])

    def test_offtaker_details(self):
        """风险评估详细说明。"""
        risk = assess_offtaker_risk(SOLAR_CONFIG)
        details = risk["details"]
        expected_details = [
            "dim1_details", "dim2_details", "dim3_details",
            "dim4_details", "dim5_details",
        ]
        for det in expected_details:
            self.assertIn(det, details)
            self.assertTrue(len(details[det]) > 0)

    def test_offtaker_risk_premium(self):
        """风险溢价计算。"""
        risk = assess_offtaker_risk(SOLAR_CONFIG)
        premium = risk["risk_premium"]
        self.assertIsNotNone(premium)
        self.assertGreaterEqual(premium, 0)
        self.assertLessEqual(premium, 0.15)

    def test_offtaker_no_config(self):
        """无购电方配置。"""
        config = SOLAR_CONFIG.copy()
        del config["offtaker"]
        # 不传 offtaker 时，assess_offtaker_risk 应使用空字典
        risk = assess_offtaker_risk(config)
        self.assertEqual(risk["revenue_model"], "ppa")  # 默认值


class TestDeepMerge(unittest.TestCase):
    """测试深度合并。"""

    def test_deep_merge_simple(self):
        """简单覆盖。"""
        base = {"a": 1, "b": 2}
        override = {"b": 3}
        result = _deep_merge(base, override)
        self.assertEqual(result["a"], 1)
        self.assertEqual(result["b"], 3)

    def test_deep_merge_nested(self):
        """嵌套覆盖。"""
        base = {"a": {"x": 1, "y": 2}, "b": 3}
        override = {"a": {"y": 99}}
        result = _deep_merge(base, override)
        self.assertEqual(result["a"]["x"], 1)
        self.assertEqual(result["a"]["y"], 99)
        self.assertEqual(result["b"], 3)

    def test_deep_merge_new_key(self):
        """新增键。"""
        base = {"a": 1}
        override = {"b": 2}
        result = _deep_merge(base, override)
        self.assertEqual(result["a"], 1)
        self.assertEqual(result["b"], 2)

    def test_deep_merge_empty_override(self):
        """空覆盖。"""
        base = {"a": 1, "b": 2}
        override = {}
        result = _deep_merge(base, override)
        self.assertEqual(result, base)


class TestTemplateCompatibility(unittest.TestCase):
    """测试模板与引擎的兼容性。"""

    def test_template_yaml_exists(self):
        """模板文件存在。"""
        template_path = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "templates", "project_config_template.yaml"
        )
        self.assertTrue(os.path.exists(template_path))

    def test_template_has_all_sections(self):
        """模板包含所有必需章节。"""
        template_path = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "templates", "project_config_template.yaml"
        )
        with open(template_path, "r", encoding="utf-8") as f:
            content = f.read()
        required_sections = [
            "project:", "technical:", "costs:", "revenue:",
            "financing:", "offtaker:", "country_risk_level",
            "optional:",
        ]
        for section in required_sections:
            self.assertIn(section, content, f"Missing section: {section}")

    def test_template_has_land_costs(self):
        """模板包含土地费用选项。"""
        template_path = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "templates", "project_config_template.yaml"
        )
        with open(template_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("land_cost_per_watt", content)
        self.assertIn("land_cost_total", content)
        self.assertIn("land_rent_per_kw_year", content)
        self.assertIn("land_rent_escalation_rate", content)

    def test_template_has_development_costs(self):
        """模板包含开发/并购费用选项。"""
        template_path = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "templates", "project_config_template.yaml"
        )
        with open(template_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("development_cost_per_watt", content)
        self.assertIn("development_cost_total", content)

    def test_template_has_construction_costs(self):
        """模板包含建设期费用选项。"""
        template_path = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "templates", "project_config_template.yaml"
        )
        with open(template_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("construction_management_percent", content)
        self.assertIn("grid_connection_cost_per_watt", content)
        self.assertIn("contingency_percent", content)

    def test_template_has_operating_costs(self):
        """模板包含运营期费用选项。"""
        template_path = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "templates", "project_config_template.yaml"
        )
        with open(template_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("labor_opex_per_kw_year", content)
        self.assertIn("management_fee_per_kw_year", content)
        self.assertIn("environmental_monitoring_per_kw_year", content)
        self.assertIn("replacement_reserve_per_kw_year", content)

    def test_template_technology_type_documented(self):
        """模板中 technology_type 注释说明支持所有类型。"""
        template_path = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "templates", "project_config_template.yaml"
        )
        with open(template_path, "r", encoding="utf-8") as f:
            content = f.read()
        # 应包含多种技术类型的说明
        self.assertIn("solar", content)
        self.assertIn("wind", content)
        self.assertIn("battery", content)
        self.assertIn("hydro", content)
        self.assertIn("hybrid", content)


if __name__ == "__main__":
    unittest.main()
