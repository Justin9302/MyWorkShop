#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  🔒 FILE LOCK — 此文件已锁定，禁止任何修改                                ║
║                                                                              ║
║  financial_model_engine.py — 通用型新能源项目财务模型引擎                   ║
║                                                                              ║
║  锁定规则:                                                                    ║
║  1. 禁止修改此文件的任何代码逻辑、函数定义、计算参数                         ║
║  2. 禁止添加、删除或修改任何函数、类、常量                                   ║
║  3. 禁止修改默认参数值、计算公式、算法实现                                   ║
║  4. 禁止在此文件中添加项目特定的硬编码参数                                   ║
║  5. 所有项目参数必须通过外部 project_config.yaml 传入                        ║
║  6. 如需新增功能，请在 scripts/ 下创建新文件，不要修改此文件                 ║
║                                                                              ║
║  违反后果: 将导致财务模型计算结果不一致，影响所有项目的财务分析              ║
║                                                                              ║
║  用途：通用型新能源项目财务模型引擎，支持所有技术类型。                       ║
║        通过读取外部 project_config.yaml 加载项目边界条件，                    ║
║        运行财务模型计算，输出结构化结果。                                     ║
║        所有项目共享同一套代码，不生成项目特定的硬编码模块。                   ║
║                                                                              ║
║  支持的技术类型（technology_type）：                                          ║
║      solar     — 光伏发电                                                     ║
║      wind      — 风力发电                                                     ║
║      battery   — 电池储能（BESS）                                             ║
║      hydro     — 水力发电                                                     ║
║      hybrid    — 混合项目（如光储一体）                                       ║
║      (其他)    — 任何通过 project_config.yaml 参数化的新能源项目              ║
║                                                                              ║
║  核心逻辑：引擎不关心"电是怎么来的"，只做纯数学计算：                        ║
║      收入 = 年发电/放电量 × 加权平均电价                                      ║
║      年发电/放电量 = 装机容量 × 年等效小时数                                  ║
║      然后计算 IRR / NPV / 回收期 / LCOE / DSCR 等指标                         ║
║                                                                              ║
║  用法：                                                                      ║
║      python3 scripts/financial_model_engine.py \                             ║
║          --config OUTPUT/<项目名>/project_config.yaml \                      ║
║          --output OUTPUT/<项目名>/outputs/                                   ║
║                                                                              ║
║  依赖：                                                                      ║
║      - PyYAML (pip install pyyaml)                                           ║
║      - 项目参数文件 project_config.yaml（由工作流生成）                       ║
║                                                                              ║
║  输出：                                                                      ║
║      - financial_results.json：结构化财务分析结果                             ║
║      - financial_summary.md：可读的财务摘要报告                               ║
║                                                                              ║
║  🔒 FILE LOCK — 此文件已锁定，禁止任何修改                                  ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import json
import math
import os
import sys
import argparse
from pathlib import Path

# =============================================================================
# 核心财务计算函数（纯数学，无项目特定硬编码）
# =============================================================================

def calculate_loan_payment(principal, annual_rate, years):
    """计算等额本息年还款额"""
    monthly_rate = annual_rate / 12
    months = years * 12
    if monthly_rate == 0:
        return principal / months * 12
    payment = principal * (monthly_rate * (1 + monthly_rate) ** months) / \
              ((1 + monthly_rate) ** months - 1)
    return payment * 12


def calculate_irr(cashflows, guess=0.1, max_iter=1000, tolerance=1e-6):
    """计算内部收益率（IRR）"""
    has_positive = any(cf > 0 for cf in cashflows)
    has_negative = any(cf < 0 for cf in cashflows)
    if not (has_positive and has_negative):
        return None

    # 缩放到百万单位以避免大数溢出
    max_abs = max(abs(cf) for cf in cashflows) if cashflows else 1
    scale = 1e6 if max_abs > 1e8 else 1.0
    scaled_cf = [cf / scale for cf in cashflows]

    rate = guess
    for _ in range(max_iter):
        # 使用安全的指数计算，避免 (1+rate)^i 溢出
        try:
            npv = 0.0
            dnpv = 0.0
            factor = 1.0
            for i, cf in enumerate(scaled_cf):
                if i > 0:
                    factor *= (1 + rate)
                if factor == 0 or abs(factor) > 1e100:
                    raise OverflowError("factor overflow")
                npv += cf / factor
                dnpv += -i * cf / (factor * (1 + rate)) if i > 0 else 0
        except (OverflowError, ZeroDivisionError):
            # 如果溢出，尝试不同的初始猜测值
            if rate > 0.5:
                rate = 0.5
            elif rate < -0.5:
                rate = -0.5
            else:
                rate = 0.1
            continue
        
        if abs(dnpv) < 1e-10:
            break
        rate -= npv / dnpv
        if abs(npv) < tolerance:
            break
    return rate


def calculate_npv(cashflows, discount_rate):
    """计算净现值（NPV）"""
    return sum(cf / (1 + discount_rate) ** i for i, cf in enumerate(cashflows))


def calculate_payback_period(cashflows):
    """计算投资回收期（年）"""
    cumulative = 0
    for i, cf in enumerate(cashflows):
        cumulative += cf
        if cumulative >= 0:
            if cumulative == 0:
                return i + 1
            prev_cumulative = cumulative - cf
            fraction = -prev_cumulative / cf if cf != 0 else 0
            return i + fraction
    return None


def calculate_lcoe(config, annual_data):
    """计算平准化度电成本（LCOE）"""
    c = _flatten_config(config)
    discount_rate = c.get("discount_rate", 0.10)
    construction_years = c.get("construction_years", 2)
    capex_total = c.get("capex_total", 0)

    total_cost_pv = 0
    total_generation_pv = 0

    for y in range(construction_years):
        capex_year = capex_total / construction_years
        total_cost_pv += capex_year / (1 + discount_rate) ** y

    for year_data in annual_data:
        year = year_data["year"]
        opex = year_data.get("opex_total", 0)
        insurance = year_data.get("insurance", 0)
        generation = year_data.get("generation_kwh", 0)
        total_cost_pv += (opex + insurance) / (1 + discount_rate) ** (construction_years + year)
        total_generation_pv += generation / (1 + discount_rate) ** (construction_years + year)

    return total_cost_pv / total_generation_pv if total_generation_pv > 0 else 0


# =============================================================================
# 购电方风险评估模块（Offtaker Risk Assessment）
# =============================================================================

def assess_offtaker_risk(config):
    """
    购电方统一风险评估框架。

    根据收入模式类型，自动选择评估重点：
    - PPA模式：评估购电方信用风险
    - 电力市场模式：评估电价波动风险
    - 混合模式：综合评估

    五维评估框架（适用于所有收入模式）：
    维度1: 收入模式风险（Revenue Model Risk）— 权重 30%
    维度2: 交易对手信用风险（Counterparty Risk）— 权重 25%
    维度3: 市场与监管风险（Market & Regulatory Risk）— 权重 20%
    维度4: 国家/政治风险（Country Risk）— 权重 15%
    维度5: 信用增强措施（Credit Enhancement）— 权重 10%
    """
    offtaker_config = config.get("offtaker", {})
    revenue_model = offtaker_config.get("revenue_model", "ppa")

    score_dim1 = _assess_revenue_model_risk(offtaker_config, revenue_model)
    score_dim2 = _assess_counterparty_risk(offtaker_config, revenue_model)
    score_dim3 = _assess_market_regulatory_risk(offtaker_config, revenue_model)
    score_dim4 = _assess_country_risk(config)
    score_dim5 = _assess_credit_enhancement(offtaker_config)

    weights = [0.30, 0.25, 0.20, 0.15, 0.10]
    scores = [score_dim1, score_dim2, score_dim3, score_dim4, score_dim5]
    composite_score = sum(w * s for w, s in zip(weights, scores))

    risk_level, risk_premium = _calculate_risk_premium(composite_score)

    return {
        "revenue_model": revenue_model,
        "composite_score": round(composite_score, 2),
        "risk_level": risk_level,
        "risk_premium": risk_premium,
        "dimension_scores": {
            "revenue_model_risk": {"score": score_dim1, "weight": 0.30, "description": "收入模式风险"},
            "counterparty_risk": {"score": score_dim2, "weight": 0.25, "description": "交易对手信用风险"},
            "market_regulatory_risk": {"score": score_dim3, "weight": 0.20, "description": "市场与监管风险"},
            "country_risk": {"score": score_dim4, "weight": 0.15, "description": "国家/政治风险"},
            "credit_enhancement": {"score": score_dim5, "weight": 0.10, "description": "信用增强措施"},
        },
        "details": {
            "dim1_details": _get_revenue_model_details(offtaker_config, revenue_model),
            "dim2_details": _get_counterparty_details(offtaker_config),
            "dim3_details": _get_market_details(offtaker_config, revenue_model),
            "dim4_details": _get_country_details(config),
            "dim5_details": _get_credit_enhancement_details(offtaker_config),
        }
    }


def _assess_revenue_model_risk(offtaker_config, revenue_model):
    """维度1: 收入模式风险评估（权重 30%）"""
    if revenue_model == "ppa":
        ppa_type = offtaker_config.get("ppa_type", "corporate")
        if ppa_type == "government":
            return 4.0
        elif ppa_type == "utility":
            ppa_tenor = offtaker_config.get("ppa_tenor_years", 15)
            if ppa_tenor <= 10:
                return 4.0
            elif ppa_tenor <= 20:
                return 3.5
            else:
                return 3.0
        else:
            industry = offtaker_config.get("counterparty", {}).get("industry", "general")
            ppa_tenor = offtaker_config.get("ppa_tenor_years", 15)
            industry_risk = {
                "mining": 3.5, "manufacturing": 3.5, "commercial": 4.0,
                "technology": 3.5, "utility": 4.0, "government": 4.5,
            }
            base_score = industry_risk.get(industry, 3.5)
            tenor_penalty = max(0, (ppa_tenor - 15) * 0.05)
            return max(1.0, base_score - tenor_penalty)
    elif revenue_model == "market":
        market_risk = offtaker_config.get("market_risk", {})
        volatility = market_risk.get("historical_price_volatility", 0.30)
        liquidity = market_risk.get("market_liquidity", "medium")
        vol_score = max(1.0, 5.0 - volatility * 10)
        liq_map = {"high": 4.5, "medium": 3.5, "low": 2.5}
        liq_score = liq_map.get(liquidity, 3.0)
        return (vol_score + liq_score) / 2
    elif revenue_model == "hybrid":
        ppa_coverage = offtaker_config.get("market_risk", {}).get("ppa_coverage_ratio", 0.5)
        return 2.0 + ppa_coverage * 2.5
    return 3.0


def _assess_counterparty_risk(offtaker_config, revenue_model):
    """维度2: 交易对手信用风险评估（权重 25%）"""
    if revenue_model == "market":
        return 3.5

    counterparty = offtaker_config.get("counterparty", {})
    if not counterparty:
        return 3.0

    score = 0.0
    criteria_count = 0

    credit_rating = counterparty.get("credit_rating")
    rating_map = {
        "AAA": 5.0, "AA": 4.5, "A": 4.0, "BBB": 3.5,
        "BB": 3.0, "B": 2.5, "CCC": 2.0, "CC": 1.5, "C": 1.0, "D": 0.5,
    }
    if credit_rating and credit_rating in rating_map:
        score += rating_map[credit_rating]
        criteria_count += 1

    fcf = counterparty.get("annual_free_cashflow")
    elec_cost = counterparty.get("annual_electricity_cost")
    if fcf is not None and elec_cost is not None and elec_cost > 0:
        ratio = fcf / elec_cost
        if ratio >= 10:
            score += 5.0
        elif ratio >= 5:
            score += 4.0
        elif ratio >= 3:
            score += 3.0
        elif ratio >= 1:
            score += 2.0
        else:
            score += 1.0
        criteria_count += 1

    dar = counterparty.get("debt_to_asset_ratio")
    if dar is not None:
        if dar <= 0.4:
            score += 5.0
        elif dar <= 0.6:
            score += 4.0
        elif dar <= 0.7:
            score += 3.0
        elif dar <= 0.8:
            score += 2.0
        else:
            score += 1.0
        criteria_count += 1

    icr = counterparty.get("interest_coverage_ratio")
    if icr is not None:
        if icr >= 5:
            score += 5.0
        elif icr >= 3:
            score += 4.0
        elif icr >= 2:
            score += 3.0
        elif icr >= 1:
            score += 2.0
        else:
            score += 1.0
        criteria_count += 1

    is_listed = counterparty.get("is_listed", False)
    score += 4.5 if is_listed else 3.0
    criteria_count += 1

    return score / criteria_count if criteria_count > 0 else 3.0


def _assess_market_regulatory_risk(offtaker_config, revenue_model):
    """维度3: 市场与监管风险评估（权重 20%）"""
    score = 3.5

    if revenue_model == "ppa":
        ppa_type = offtaker_config.get("ppa_type", "corporate")
        if ppa_type == "government":
            score -= 0.5
        elif ppa_type == "utility":
            score -= 0.3
    elif revenue_model == "market":
        market_risk = offtaker_config.get("market_risk", {})
        hedging = market_risk.get("hedging_available", False)
        score += 0.5 if hedging else -0.5
        liquidity = market_risk.get("market_liquidity", "medium")
        if liquidity == "low":
            score -= 1.0
        elif liquidity == "high":
            score += 0.5
    elif revenue_model == "hybrid":
        ppa_coverage = offtaker_config.get("market_risk", {}).get("ppa_coverage_ratio", 0.5)
        score = 3.0 + ppa_coverage * 1.5

    subsidy_risk = offtaker_config.get("subsidy_risk", "low")
    subsidy_map = {"low": 0, "medium": -0.5, "high": -1.0, "uncertain": -1.5}
    score += subsidy_map.get(subsidy_risk, 0)

    return max(1.0, min(5.0, score))


def _assess_country_risk(config):
    """维度4: 国家/政治风险评估（权重 15%）"""
    country_risk = config.get("country_risk_level", "medium")
    risk_map = {
        "very_low": 5.0, "low": 4.5, "medium_low": 4.0,
        "medium": 3.5, "medium_high": 3.0, "high": 2.5, "very_high": 1.5,
    }
    base_score = risk_map.get(country_risk, 3.0)

    exchange_rate_risk = config.get("exchange_rate_risk", "medium")
    er_map = {"low": 0, "medium": -0.3, "high": -0.7}
    base_score += er_map.get(exchange_rate_risk, 0)

    ppa_currency = config.get("ppa_currency", "USD")
    if ppa_currency == "USD":
        base_score += 0.3

    return max(1.0, min(5.0, base_score))


def _assess_credit_enhancement(offtaker_config):
    """维度5: 信用增强措施评估（权重 10%）"""
    ce = offtaker_config.get("credit_enhancement", {})
    if not ce:
        return 2.0

    score = 2.0
    enhancements = [
        ("parent_guarantee", 1.0),
        ("letter_of_credit", 1.0),
        ("escrow_account", 1.0),
        ("default_compensation", 0.5),
        ("multilateral_guarantee", 1.5),
        ("government_guarantee", 1.5),
    ]
    for key, value in enhancements:
        if ce.get(key, False):
            score += value

    return min(5.0, score)


def _calculate_risk_premium(composite_score):
    """根据综合风险评分计算风险等级和折现率溢价"""
    if composite_score >= 4.5:
        return "very_low", 0.0
    elif composite_score >= 4.0:
        return "low", 0.0
    elif composite_score >= 3.5:
        return "medium_low", 0.01
    elif composite_score >= 3.0:
        return "medium_low", 0.02
    elif composite_score >= 2.5:
        return "medium", 0.03
    elif composite_score >= 2.0:
        return "medium", 0.05
    elif composite_score >= 1.5:
        return "high", 0.08
    elif composite_score >= 1.0:
        return "high", 0.10
    else:
        return "very_high", None


def _get_revenue_model_details(offtaker_config, revenue_model):
    """生成收入模式风险详细说明"""
    details = []
    if revenue_model == "ppa":
        ppa_type = offtaker_config.get("ppa_type", "corporate")
        ppa_tenor = offtaker_config.get("ppa_tenor_years", 15)
        details.append(f"PPA模式 ({ppa_type}), 期限 {ppa_tenor} 年")
        if ppa_type == "corporate":
            industry = offtaker_config.get("counterparty", {}).get("industry", "未指定")
            details.append(f"购电方行业: {industry}")
    elif revenue_model == "market":
        market_risk = offtaker_config.get("market_risk", {})
        volatility = market_risk.get("historical_price_volatility", "未知")
        liquidity = market_risk.get("market_liquidity", "未知")
        details.append(f"电力市场交易模式")
        details.append(f"历史电价波动率: {volatility}, 市场流动性: {liquidity}")
    elif revenue_model == "hybrid":
        ppa_coverage = offtaker_config.get("market_risk", {}).get("ppa_coverage_ratio", 0)
        details.append(f"混合模式, PPA覆盖比例: {ppa_coverage:.0%}")
    return details


def _get_counterparty_details(offtaker_config):
    """生成交易对手信用风险详细说明"""
    details = []
    counterparty = offtaker_config.get("counterparty", {})
    if counterparty:
        name = counterparty.get("name", "未指定")
        details.append(f"购电方: {name}")
        if counterparty.get("credit_rating"):
            details.append(f"信用评级: {counterparty['credit_rating']}")
        fcf = counterparty.get("annual_free_cashflow")
        elec = counterparty.get("annual_electricity_cost")
        if fcf and elec and elec > 0:
            details.append(f"自由现金流/电费比: {fcf/elec:.1f}x")
        dar = counterparty.get("debt_to_asset_ratio")
        if dar is not None:
            details.append(f"资产负债率: {dar:.0%}")
        if counterparty.get("is_listed"):
            details.append("上市公司: 是")
        else:
            details.append("上市公司: 否（信息透明度较低）")
    else:
        details.append("未提供购电方信息")
    return details


def _get_market_details(offtaker_config, revenue_model):
    """生成市场与监管风险详细说明"""
    details = []
    if revenue_model in ("market", "hybrid"):
        market_risk = offtaker_config.get("market_risk", {})
        hedging = market_risk.get("hedging_available", False)
        details.append(f"对冲工具: {'可用' if hedging else '不可用'}")
    subsidy = offtaker_config.get("subsidy_risk", "low")
    details.append(f"补贴/绿证风险: {subsidy}")
    return details


def _get_country_details(config):
    """生成国家风险详细说明"""
    details = []
    country_risk = config.get("country_risk_level", "medium")
    details.append(f"政治风险等级: {country_risk}")
    er_risk = config.get("exchange_rate_risk", "medium")
    details.append(f"汇率风险: {er_risk}")
    currency = config.get("ppa_currency", "USD")
    details.append(f"PPA计价货币: {currency}")
    return details


def _get_credit_enhancement_details(offtaker_config):
    """生成信用增强措施详细说明"""
    details = []
    ce = offtaker_config.get("credit_enhancement", {})
    if not ce:
        details.append("无合同约定的信用增强措施")
        return details

    enhancement_labels = [
        ("parent_guarantee", "母公司担保"),
        ("letter_of_credit", "信用证"),
        ("escrow_account", "电费支付托管账户"),
        ("default_compensation", "违约赔偿条款"),
        ("multilateral_guarantee", "多边担保"),
        ("government_guarantee", "政府担保"),
    ]
    for key, label in enhancement_labels:
        if ce.get(key, False):
            details.append(f"✅ {label}")
        else:
            details.append(f"❌ {label}")
    return details


# =============================================================================
# 财务模型构建器
# =============================================================================

def _flatten_config(config):
    """
    将配置展平为引擎可读的扁平结构。
    
    同时支持两种格式：
    1. 嵌套格式（由工作流生成）：{project: {name: ...}, technical: {equivalent_hours: ...}, ...}
    2. 扁平格式（测试用例使用）：{capacity_kw: ..., ppa_price_per_kwh: ..., ...}
    """
    flat = {}
    
    # 检测是否为嵌套格式（包含 project/technical/costs/revenue/financing 等顶层键）
    has_nested = any(k in config for k in ["project", "technical", "costs", "revenue", "financing"])
    
    if has_nested:
        # 嵌套格式
        proj = config.get("project", {})
        flat["project_name"] = proj.get("name", "未命名")
        flat["technology_type"] = proj.get("technology_type", "未指定")
        flat["capacity_mw"] = proj.get("capacity_mw", 0)
        flat["capacity_kw"] = proj.get("capacity_kw", flat["capacity_mw"] * 1000)
        
        tech = config.get("technical", {})
        flat["equivalent_hours"] = tech.get("equivalent_hours", 0)
        flat["capacity_factor"] = tech.get("capacity_factor", 0)
        flat["degradation_rate"] = tech.get("degradation_rate", 0.005)
        flat["construction_years"] = tech.get("construction_years", 2)
        flat["operation_years"] = tech.get("operation_years", 25)
        
        costs = config.get("costs", {})
        flat["capex_per_watt"] = costs.get("capex_per_watt", 0)
        flat["capex_total"] = costs.get("capex_total", 0)
        flat["capex_schedule"] = costs.get("capex_schedule", [0.6, 0.4])
        flat["opex_fixed_per_kw_year"] = costs.get("opex_fixed_per_kw_year", 0)
        flat["opex_escalation_rate"] = costs.get("opex_escalation_rate", 0.02)
        flat["insurance_rate"] = costs.get("insurance_rate", 0.005)
        
        rev = config.get("revenue", {})
        flat["ppa_price_per_kwh"] = rev.get("ppa_price_per_kwh", 0)
        flat["annual_generation_kwh"] = rev.get("annual_generation_kwh", flat["capacity_kw"] * flat["equivalent_hours"])
        
        fin = config.get("financing", {})
        flat["debt_ratio"] = fin.get("debt_ratio", 0.70)
        flat["equity_ratio"] = fin.get("equity_ratio", 1 - flat["debt_ratio"])
        flat["interest_rate"] = fin.get("interest_rate", 0.06)
        flat["loan_tenor_years"] = fin.get("loan_tenor_years", 10)
        flat["discount_rate"] = fin.get("discount_rate", 0.10)
        flat["tax_rate"] = fin.get("tax_rate", 0.25)
        flat["depreciation_years"] = fin.get("depreciation_years", 15)
        
        if "offtaker" in config:
            flat["offtaker"] = config["offtaker"]
        
        flat["country_risk_level"] = config.get("country_risk_level", "medium")
        flat["exchange_rate_risk"] = config.get("exchange_rate_risk", "medium")
        flat["ppa_currency"] = config.get("ppa_currency", "USD")
        
        opt = config.get("optional", {})
        flat["dust_cleaning_opex_per_kw"] = opt.get("dust_cleaning_opex_per_kw", 0)
        flat["security_opex_per_kw"] = opt.get("security_opex_per_kw", 0)
        flat["community_opex_per_kw"] = opt.get("community_opex_per_kw", 0)
        flat["dust_degradation_penalty"] = opt.get("dust_degradation_penalty", 0)
        flat["land_rent_per_kw"] = opt.get("land_rent_per_kw", 0)
    else:
        # 扁平格式：直接读取顶层键
        flat["project_name"] = config.get("project_name", "未命名")
        flat["technology_type"] = config.get("technology_type", "未指定")
        flat["capacity_mw"] = config.get("capacity_mw", 0)
        flat["capacity_kw"] = config.get("capacity_kw", flat["capacity_mw"] * 1000)
        flat["equivalent_hours"] = config.get("equivalent_hours", 0)
        flat["capacity_factor"] = config.get("capacity_factor", 0)
        flat["degradation_rate"] = config.get("degradation_rate", 0.005)
        flat["construction_years"] = config.get("construction_years", 2)
        flat["operation_years"] = config.get("operation_years", 25)
        flat["capex_per_watt"] = config.get("capex_per_watt", 0)
        flat["capex_total"] = config.get("capex_total", 0)
        flat["capex_schedule"] = config.get("capex_schedule", [0.6, 0.4])
        flat["opex_fixed_per_kw_year"] = config.get("opex_fixed_per_kw_year", 0)
        flat["opex_escalation_rate"] = config.get("opex_escalation_rate", 0.02)
        flat["insurance_rate"] = config.get("insurance_rate", 0.005)
        flat["ppa_price_per_kwh"] = config.get("ppa_price_per_kwh", 0)
        flat["annual_generation_kwh"] = config.get("annual_generation_kwh", flat["capacity_kw"] * flat["equivalent_hours"])
        flat["debt_ratio"] = config.get("debt_ratio", 0.70)
        flat["equity_ratio"] = config.get("equity_ratio", 1 - flat["debt_ratio"])
        flat["interest_rate"] = config.get("interest_rate", 0.06)
        flat["loan_tenor_years"] = config.get("loan_tenor_years", 10)
        flat["discount_rate"] = config.get("discount_rate", 0.10)
        flat["tax_rate"] = config.get("tax_rate", 0.25)
        flat["depreciation_years"] = config.get("depreciation_years", 15)
        if "offtaker" in config:
            flat["offtaker"] = config["offtaker"]
        flat["country_risk_level"] = config.get("country_risk_level", "medium")
        flat["exchange_rate_risk"] = config.get("exchange_rate_risk", "medium")
        flat["ppa_currency"] = config.get("ppa_currency", "USD")
        flat["dust_cleaning_opex_per_kw"] = config.get("dust_cleaning_opex_per_kw", 0)
        flat["security_opex_per_kw"] = config.get("security_opex_per_kw", 0)
        flat["community_opex_per_kw"] = config.get("community_opex_per_kw", 0)
        flat["dust_degradation_penalty"] = config.get("dust_degradation_penalty", 0)
        flat["land_rent_per_kw"] = config.get("land_rent_per_kw", 0)
    
    return flat


def build_cashflow_model(config):
    """构建项目全生命周期现金流模型"""
    c = _flatten_config(config)

    capacity_kw = c.get("capacity_kw", c.get("capacity_mw", 0) * 1000)
    capacity_mw = capacity_kw / 1000
    total_capex = c.get("capex_total", 0)
    debt_ratio = c.get("debt_ratio", 0.70)
    equity_ratio = c.get("equity_ratio", 1 - debt_ratio)
    debt_amount = total_capex * debt_ratio
    equity_amount = total_capex * equity_ratio

    interest_rate = c.get("interest_rate", 0.06)
    loan_tenor_years = c.get("loan_tenor_years", 10)
    annual_loan_payment = calculate_loan_payment(debt_amount, interest_rate, loan_tenor_years)

    depreciation_years = c.get("depreciation_years", 15)
    annual_depreciation = total_capex / depreciation_years

    equivalent_hours = c.get("equivalent_hours", 0)
    annual_generation_kwh = c.get("annual_generation_kwh", capacity_kw * equivalent_hours)
    degradation_rate = c.get("degradation_rate", 0.005)
    ppa_price = c.get("ppa_price_per_kwh", 0)

    opex_fixed_per_kw = c.get("opex_fixed_per_kw_year", 0)
    base_opex_annual = c.get("opex_annual", capacity_kw * opex_fixed_per_kw)
    opex_escalation = c.get("opex_escalation_rate", 0.02)
    insurance_rate = c.get("insurance_rate", 0.005)
    annual_insurance = total_capex * insurance_rate

    dust_cleaning_per_kw = c.get("dust_cleaning_opex_per_kw", 0)
    security_per_kw = c.get("security_opex_per_kw", 0)
    community_per_kw = c.get("community_opex_per_kw", 0)
    dust_degradation = c.get("dust_degradation_penalty", 0)

    tax_rate = c.get("tax_rate", 0.25)
    construction_years = c.get("construction_years", 2)
    operation_years = c.get("operation_years", 25)

    construction_phase = {
        "year": list(range(-construction_years, 0)),
        "capex": [], "equity": [], "debt": [],
    }
    capex_schedule = c.get("capex_schedule", [0.6, 0.4])
    if len(capex_schedule) != construction_years:
        capex_schedule = [1.0 / construction_years] * construction_years

    for y in range(construction_years):
        capex_yr = total_capex * capex_schedule[y]
        construction_phase["capex"].append(capex_yr)
        construction_phase["equity"].append(capex_yr * equity_ratio)
        construction_phase["debt"].append(capex_yr * debt_ratio)

    annual_data = []
    cumulative_fcf = -equity_amount
    remaining_balance = debt_amount
    tax_loss_carryforward = 0.0

    for year in range(1, operation_years + 1):
        total_degradation = degradation_rate + dust_degradation
        degradation_factor = (1 - total_degradation) ** (year - 1)
        generation = annual_generation_kwh * degradation_factor
        revenue = generation * ppa_price

        opex_base = base_opex_annual * (1 + opex_escalation) ** (year - 1)
        opex_dust = dust_cleaning_per_kw * capacity_kw * (1 + opex_escalation) ** (year - 1)
        opex_security = security_per_kw * capacity_kw * (1 + opex_escalation) ** (year - 1)
        opex_community = community_per_kw * capacity_kw * (1 + opex_escalation) ** (year - 1)
        opex_total = opex_base + opex_dust + opex_security + opex_community
        insurance = annual_insurance
        ebitda = revenue - opex_total - insurance
        depreciation = annual_depreciation if year <= depreciation_years else 0

        if year <= loan_tenor_years and remaining_balance > 0:
            interest = remaining_balance * interest_rate
            principal_payment = annual_loan_payment - interest
            if principal_payment > remaining_balance:
                principal_payment = remaining_balance
                interest = annual_loan_payment - principal_payment
            remaining_balance -= principal_payment
            if remaining_balance < 0:
                remaining_balance = 0.0
        else:
            interest = 0
            principal_payment = 0

        ebt = ebitda - depreciation - interest
        taxable_income = ebt - tax_loss_carryforward
        if taxable_income > 0:
            tax = taxable_income * tax_rate
            tax_loss_carryforward = 0.0
        else:
            tax = 0.0
            tax_loss_carryforward = -taxable_income

        if year <= loan_tenor_years:
            fcf_equity = ebitda - tax - principal_payment - interest
        else:
            fcf_equity = ebitda - tax
        cumulative_fcf += fcf_equity

        year_data = {
            "year": year, "generation_kwh": generation, "generation_gwh": generation / 1e6,
            "revenue": revenue, "opex_base": opex_base,
            "opex_dust_cleaning": opex_dust, "opex_security": opex_security,
            "opex_community": opex_community, "opex_total": opex_total,
            "insurance": insurance, "ebitda": ebitda, "depreciation": depreciation,
            "interest": interest, "principal_payment": principal_payment,
            "remaining_balance": remaining_balance, "ebt": ebt, "tax": tax,
            "tax_loss_carryforward": tax_loss_carryforward,
            "fcf_equity": fcf_equity, "cumulative_fcf": cumulative_fcf,
        }
        annual_data.append(year_data)

    return {
        "construction": construction_phase,
        "operations": annual_data,
        "summary": {
            "total_capex": total_capex, "debt_amount": debt_amount,
            "equity_amount": equity_amount, "annual_loan_payment": annual_loan_payment,
            "annual_depreciation": annual_depreciation,
            "capacity_mw": capacity_mw, "capacity_kw": capacity_kw,
        }
    }


def run_scenario(config):
    """
    运行单个情景的财务模型。

    参数：
        config (dict)：项目参数配置（可包含覆盖值）

    返回：
        dict：包含所有财务指标的结构化结果
    """
    cashflow = build_cashflow_model(config)

    project_cashflows = []
    for capex in cashflow["construction"]["capex"]:
        project_cashflows.append(-capex)
    for year_data in cashflow["operations"]:
        project_cashflows.append(year_data["ebitda"] - year_data["tax"])

    equity_cashflows = []
    for eq in cashflow["construction"]["equity"]:
        equity_cashflows.append(-eq)
    for year_data in cashflow["operations"]:
        equity_cashflows.append(year_data["fcf_equity"])

    c = _flatten_config(config)
    discount_rate = c.get("discount_rate", 0.10)
    loan_tenor_years = c.get("loan_tenor_years", 10)

    project_irr = calculate_irr(project_cashflows)
    equity_irr = calculate_irr(equity_cashflows)
    project_npv = calculate_npv(project_cashflows, discount_rate)
    equity_npv = calculate_npv(equity_cashflows, discount_rate)
    payback = calculate_payback_period(equity_cashflows)
    lcoe = calculate_lcoe(config, cashflow["operations"])

    dscr_values = []
    for year_data in cashflow["operations"]:
        if year_data["year"] <= loan_tenor_years:
            debt_service = year_data["principal_payment"] + year_data["interest"]
            dscr = year_data["ebitda"] / debt_service if debt_service > 0 else 0
            dscr_values.append(dscr)

    avg_dscr = sum(dscr_values) / len(dscr_values) if dscr_values else 0
    min_dscr = min(dscr_values) if dscr_values else 0

    # 购电方风险评估（如配置中包含）
    offtaker_risk = None
    if "offtaker" in config:
        offtaker_risk = assess_offtaker_risk(config)

    result = {
        "project_irr": project_irr,
        "equity_irr": equity_irr,
        "project_npv": project_npv,
        "equity_npv": equity_npv,
        "payback_years": payback,
        "lcoe_per_kwh": lcoe,
        "avg_dscr": avg_dscr,
        "min_dscr": min_dscr,
        "annual_data": cashflow["operations"],
        "summary": cashflow["summary"],
    }

    if offtaker_risk:
        result["offtaker_risk"] = offtaker_risk
        base_discount_rate = config.get("discount_rate", 0.10)
        risk_premium = offtaker_risk.get("risk_premium", 0.0)
        if risk_premium is not None:
            result["risk_adjusted_discount_rate"] = base_discount_rate + risk_premium
            result["risk_adjusted_project_npv"] = calculate_npv(project_cashflows, base_discount_rate + risk_premium)
            result["risk_adjusted_equity_npv"] = calculate_npv(equity_cashflows, base_discount_rate + risk_premium)

    return result


def run_sensitivity_analysis(config):
    """运行单因素敏感性分析"""
    flat = _flatten_config(config)
    
    sensitivity_params = config.get("sensitivity_params", {
        "PPA电价": {
            "key": "ppa_price_per_kwh",
            "low": flat.get("ppa_price_per_kwh", 0) * 0.8,
            "high": flat.get("ppa_price_per_kwh", 0) * 1.2,
            "steps": 5,
        },
        "等效小时数": {
            "key": "equivalent_hours",
            "low": flat.get("equivalent_hours", 0) * 0.8,
            "high": flat.get("equivalent_hours", 0) * 1.2,
            "steps": 5,
        },
        "CAPEX": {
            "key": "capex_per_watt",
            "low": flat.get("capex_per_watt", 0) * 0.8,
            "high": flat.get("capex_per_watt", 0) * 1.2,
            "steps": 5,
        },
        "折现率": {
            "key": "discount_rate",
            "low": max(0.04, flat.get("discount_rate", 0.10) - 0.03),
            "high": flat.get("discount_rate", 0.10) + 0.03,
            "steps": 5,
        },
    })

    results = []
    for param_name, param_config in sensitivity_params.items():
        key = param_config["key"]
        low = param_config["low"]
        high = param_config["high"]
        steps = param_config["steps"]

        values = []
        project_irrs = []
        equity_irrs = []

        step_size = (high - low) / (steps - 1) if steps > 1 else 0
        for s in range(steps):
            val = low + s * step_size
            override = {key: val}

            if key == "capex_per_watt":
                override["capex_total"] = flat.get("capacity_kw", 0) * 1000 * val
            elif key == "equivalent_hours":
                override["annual_generation_kwh"] = flat.get("capacity_kw", 0) * val
            elif key == "ppa_price_per_kwh":
                override["annual_revenue"] = flat.get("annual_generation_kwh", 0) * val

            # 将override映射到嵌套结构
            nested_override = {}
            if key == "ppa_price_per_kwh":
                nested_override["revenue"] = {"ppa_price_per_kwh": val}
            elif key == "equivalent_hours":
                nested_override["technical"] = {"equivalent_hours": val}
                nested_override["revenue"] = {"equivalent_hours": val}
            elif key == "capex_per_watt":
                new_capex_total = flat.get("capacity_kw", 0) * 1000 * val
                nested_override["costs"] = {"capex_per_watt": val, "capex_total": new_capex_total}
            elif key == "discount_rate":
                nested_override["financing"] = {"discount_rate": val}
            else:
                nested_override[key] = val

            merged_config = _deep_merge(config, nested_override)
            result = run_scenario(merged_config)

            values.append(val)
            project_irrs.append(result["project_irr"])
            equity_irrs.append(result["equity_irr"])

        # 过滤掉None值
        valid_project_irrs = [x for x in project_irrs if x is not None]
        valid_equity_irrs = [x for x in equity_irrs if x is not None]
        
        results.append({
            "param_name": param_name,
            "param_key": key,
            "values": values,
            "project_irr_range": [min(valid_project_irrs), max(valid_project_irrs)] if valid_project_irrs else [0, 0],
            "equity_irr_range": [min(valid_equity_irrs), max(valid_equity_irrs)] if valid_equity_irrs else [0, 0],
            "project_irr_values": project_irrs,
            "equity_irr_values": equity_irrs,
        })

    return results


def _deep_merge(base, override):
    """深度合并两个字典，override中的值覆盖base"""
    result = {}
    for key in base:
        if key in override:
            if isinstance(base[key], dict) and isinstance(override[key], dict):
                result[key] = _deep_merge(base[key], override[key])
            else:
                result[key] = override[key]
        else:
            result[key] = base[key]
    for key in override:
        if key not in base:
            result[key] = override[key]
    return result


# =============================================================================
# 报告生成
# =============================================================================

def generate_summary_report(config, base_result, scenario_results, sensitivity_results):
    """生成可读的财务摘要报告（Markdown）"""
    from datetime import datetime

    c = _flatten_config(config)

    lines = []
    lines.append("# 财务模型分析报告")
    lines.append("")
    lines.append(f"**项目**: {c.get('project_name', '未命名项目')}")
    lines.append(f"**装机容量**: {c.get('capacity_mw', 0):.0f} MW")
    lines.append(f"**技术方案**: {c.get('technology_type', '未指定')}")
    lines.append(f"**报告生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    # ── 购电方风险评估章节 ──
    if base_result and "offtaker_risk" in base_result:
        risk = base_result["offtaker_risk"]
        lines.append("## 购电方风险评估")
        lines.append("")
        lines.append(f"**收入模式**: {risk['revenue_model']}")
        lines.append(f"**综合风险评分**: {risk['composite_score']}/5.0")
        lines.append(f"**风险等级**: {risk['risk_level']}")
        if risk['risk_premium'] is not None:
            lines.append(f"**建议风险溢价**: +{risk['risk_premium']*100:.1f}%")
        else:
            lines.append("**建议风险溢价**: 不推荐（风险过高）")
        lines.append("")
        lines.append("### 五维评分明细")
        lines.append("")
        lines.append("| 维度 | 评分 | 权重 | 加权得分 |")
        lines.append("|------|------|------|----------|")
        for dim_key, dim_data in risk["dimension_scores"].items():
            weighted = dim_data["score"] * dim_data["weight"]
            lines.append(f"| {dim_data['description']} | {dim_data['score']}/5.0 | {dim_data['weight']*100:.0f}% | {weighted:.2f} |")
        lines.append("")
        lines.append("### 详细说明")
        lines.append("")
        for dim_key, dim_details in risk["details"].items():
            label_map = {
                "dim1_details": "收入模式风险",
                "dim2_details": "交易对手信用风险",
                "dim3_details": "市场与监管风险",
                "dim4_details": "国家/政治风险",
                "dim5_details": "信用增强措施",
            }
            lines.append(f"**{label_map.get(dim_key, dim_key)}**:")
            for detail in dim_details:
                lines.append(f"- {detail}")
            lines.append("")
        if "risk_adjusted_discount_rate" in base_result:
            lines.append(f"**风险调整后折现率**: {base_result['risk_adjusted_discount_rate']*100:.1f}%")
            lines.append(f"**风险调整后项目NPV**: ${base_result['risk_adjusted_project_npv']:,.0f}")
            lines.append(f"**风险调整后资本金NPV**: ${base_result['risk_adjusted_equity_npv']:,.0f}")
            lines.append("")

    # ── 核心财务指标 ──
    lines.append("## 核心财务指标")
    lines.append("")
    lines.append("| 指标 | 基准情景 |")
    lines.append("|------|----------|")
    if base_result:
        irr_str = f"{base_result.get('project_irr', 'N/A')*100:.2f}%" if base_result.get('project_irr') is not None else "N/A"
        eirr_str = f"{base_result.get('equity_irr', 'N/A')*100:.2f}%" if base_result.get('equity_irr') is not None else "N/A"
        payback_str = f"{base_result.get('payback_years', 'N/A'):.1f} 年" if base_result.get('payback_years') is not None else "N/A"
        lines.append(f"| 项目IRR | {irr_str} |")
        lines.append(f"| 资本金IRR | {eirr_str} |")
        lines.append(f"| 项目NPV | ${base_result.get('project_npv', 0):,.0f} |")
        lines.append(f"| 资本金NPV | ${base_result.get('equity_npv', 0):,.0f} |")
        lines.append(f"| 投资回收期 | {payback_str} |")
        lines.append(f"| LCOE | ${base_result.get('lcoe_per_kwh', 0):.4f}/kWh |")
        lines.append(f"| 平均偿债覆盖率 | {base_result.get('avg_dscr', 0):.2f}x |")
        lines.append(f"| 最低偿债覆盖率 | {base_result.get('min_dscr', 0):.2f}x |")
    lines.append("")

    # ── 多情景分析 ──
    if scenario_results:
        lines.append("## 多情景分析")
        lines.append("")
        lines.append("| 情景 | 项目IRR | 资本金IRR | 项目NPV | 资本金NPV |")
        lines.append("|------|---------|-----------|---------|-----------|")
        for scenario_name, scenario_result in scenario_results.items():
            sirr = scenario_result.get('project_irr')
            seirr = scenario_result.get('equity_irr')
            sirr_str = f"{sirr*100:.2f}%" if sirr is not None else "N/A"
            seirr_str = f"{seirr*100:.2f}%" if seirr is not None else "N/A"
            lines.append(f"| {scenario_name} | {sirr_str} | {seirr_str} | ${scenario_result.get('project_npv', 0):,.0f} | ${scenario_result.get('equity_npv', 0):,.0f} |")
        lines.append("")

    # ── 敏感性分析 ──
    if sensitivity_results:
        lines.append("## 敏感性分析")
        lines.append("")
        for sr in sensitivity_results:
            lines.append(f"### {sr['param_name']}")
            lines.append("")
            lines.append(f"- 项目IRR范围: {sr['project_irr_range'][0]*100:.2f}% ~ {sr['project_irr_range'][1]*100:.2f}%")
            lines.append(f"- 资本金IRR范围: {sr['equity_irr_range'][0]*100:.2f}% ~ {sr['equity_irr_range'][1]*100:.2f}%")
            lines.append("")

    # ── 项目参数摘要 ──
    lines.append("## 项目参数摘要")
    lines.append("")
    lines.append(f"| 参数 | 值 |")
    lines.append(f"|------|-----|")
    lines.append(f"| 装机容量 | {c.get('capacity_mw', 0):.0f} MW |")
    lines.append(f"| CAPEX总额 | ${c.get('capex_total', 0):,.0f} |")
    lines.append(f"| CAPEX单价 | ${c.get('capex_per_watt', 0):.2f}/W |")
    lines.append(f"| PPA电价 | ${c.get('ppa_price_per_kwh', 0):.4f}/kWh |")
    lines.append(f"| 等效小时数 | {c.get('equivalent_hours', 0):.0f} h |")
    lines.append(f"| 折现率 | {c.get('discount_rate', 0.10)*100:.1f}% |")
    lines.append(f"| 债务比例 | {c.get('debt_ratio', 0.70)*100:.0f}% |")
    lines.append(f"| 贷款利率 | {c.get('interest_rate', 0.06)*100:.1f}% |")
    lines.append(f"| 贷款期限 | {c.get('loan_tenor_years', 10)} 年 |")
    lines.append(f"| 运营年限 | {c.get('operation_years', 25)} 年 |")
    lines.append("")

    return "\n".join(lines)


# =============================================================================
# 主入口
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="通用型新能源项目财务模型引擎")
    parser.add_argument("--config", required=True, help="项目参数配置文件路径 (project_config.yaml)")
    parser.add_argument("--output", required=True, help="输出目录路径")
    args = parser.parse_args()

    config_path = Path(args.config)
    output_dir = Path(args.output)

    if not config_path.exists():
        print(f"错误: 配置文件不存在: {config_path}")
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    # 加载配置
    import yaml
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 获取项目名称（支持嵌套格式和扁平格式）
    proj_name = "未命名"
    if "project" in config and isinstance(config["project"], dict):
        proj_name = config["project"].get("name", "未命名")
    else:
        proj_name = config.get("project_name", "未命名")
    print(f"加载项目配置: {proj_name}")

    # 运行基准情景
    print("运行基准情景...")
    base_result = run_scenario(config)

    # 运行多情景分析
    scenario_results = {}
    scenarios = config.get("scenarios", {})
    if scenarios:
        print(f"运行 {len(scenarios)} 个情景分析...")
        for scenario_name, scenario_overrides in scenarios.items():
            merged = _deep_merge(config, scenario_overrides)
            scenario_results[scenario_name] = run_scenario(merged)

    # 运行敏感性分析
    print("运行敏感性分析...")
    sensitivity_results = run_sensitivity_analysis(config)

    # 生成报告
    print("生成报告...")
    report = generate_summary_report(config, base_result, scenario_results, sensitivity_results)

    # 输出结果
    results_path = output_dir / "financial_results.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump({
            "base_result": base_result,
            "scenario_results": scenario_results,
            "sensitivity_results": sensitivity_results,
        }, f, indent=2, ensure_ascii=False, default=str)
    print(f"结构化结果已保存: {results_path}")

    summary_path = output_dir / "financial_summary.md"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"摘要报告已保存: {summary_path}")

    print("完成!")


if __name__ == "__main__":
    main()
