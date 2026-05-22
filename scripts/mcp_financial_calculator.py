#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  MCP 金融模型计算器                                                         ║
║                                                                              ║
║  用途：作为 MCP 工具，封装 financial_model_engine.py 的核心功能，             ║
║        让 CLINE Agent 可以通过 use_mcp_tool 直接调用金融计算。                ║
║                                                                              ║
║  MCP 协议：通过 stdio 接收 JSON-RPC 请求，返回计算结果                        ║
║                                                                              ║
║  可用工具：                                                                  ║
║    1. calculate_npv          — 计算净现值                                    ║
║    2. calculate_irr          — 计算内部收益率                                ║
║    3. calculate_lcoe         — 计算平准化度电成本                            ║
║    4. calculate_payback      — 计算投资回收期                                ║
║    5. run_financial_model    — 运行完整财务模型                              ║
║    6. run_sensitivity        — 运行敏感性分析                                ║
║    7. assess_offtaker_risk   — 购电方风险评估                                ║
║    8. calculate_loan_payment — 计算贷款还款额                                ║
║                                                                              ║
║  用法：                                                                      ║
║    python3 scripts/mcp_financial_calculator.py                               ║
║                                                                              ║
║  依赖：                                                                      ║
║    - PyYAML (pip install pyyaml)                                             ║
║    - 引用 scripts/financial_model_engine.py 中的核心函数                      ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import json
import sys
import os
import math
from typing import Any, Dict, List, Optional, Union

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 导入 financial_model_engine 的核心函数
from scripts.financial_model_engine import (
    calculate_irr as _calculate_irr,
    calculate_npv as _calculate_npv,
    calculate_payback_period as _calculate_payback,
    calculate_lcoe as _calculate_lcoe,
    calculate_loan_payment as _calculate_loan_payment,
    build_cashflow_model as _build_cashflow_model,
    run_scenario as _run_scenario,
    run_sensitivity_analysis as _run_sensitivity,
    assess_offtaker_risk as _assess_offtaker_risk,
    _flatten_config,
)


# ═══════════════════════════════════════════════════════════════
# MCP 工具定义
# ═══════════════════════════════════════════════════════════════

TOOLS = [
    {
        "name": "calculate_npv",
        "description": "计算净现值（NPV）。输入现金流列表和折现率，返回净现值。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cashflows": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "现金流列表（第0年为初始投资，负值表示支出）",
                },
                "discount_rate": {
                    "type": "number",
                    "description": "折现率（如 0.10 表示 10%）",
                },
            },
            "required": ["cashflows", "discount_rate"],
        },
    },
    {
        "name": "calculate_irr",
        "description": "计算内部收益率（IRR）。输入现金流列表，返回IRR值。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cashflows": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "现金流列表（第0年为初始投资，负值表示支出）",
                },
                "guess": {
                    "type": "number",
                    "description": "初始猜测值（默认 0.1）",
                    "default": 0.1,
                },
            },
            "required": ["cashflows"],
        },
    },
    {
        "name": "calculate_lcoe",
        "description": "计算平准化度电成本（LCOE）。输入项目参数和年度数据，返回LCOE值。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "capex_total": {
                    "type": "number",
                    "description": "CAPEX总额（美元）",
                },
                "discount_rate": {
                    "type": "number",
                    "description": "折现率（如 0.10 表示 10%）",
                },
                "construction_years": {
                    "type": "integer",
                    "description": "建设期年数",
                },
                "operation_years": {
                    "type": "integer",
                    "description": "运营期年数",
                },
                "annual_generation_kwh": {
                    "type": "number",
                    "description": "年发电量（kWh）",
                },
                "annual_opex": {
                    "type": "number",
                    "description": "年运营成本（美元）",
                },
                "degradation_rate": {
                    "type": "number",
                    "description": "年衰减率（默认 0.005）",
                    "default": 0.005,
                },
            },
            "required": [
                "capex_total",
                "discount_rate",
                "construction_years",
                "operation_years",
                "annual_generation_kwh",
                "annual_opex",
            ],
        },
    },
    {
        "name": "calculate_payback",
        "description": "计算投资回收期。输入现金流列表，返回回收期（年）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cashflows": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "现金流列表（第0年为初始投资，负值表示支出）",
                },
            },
            "required": ["cashflows"],
        },
    },
    {
        "name": "calculate_loan_payment",
        "description": "计算等额本息年还款额。输入贷款本金、年利率和期限，返回年还款额。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "principal": {
                    "type": "number",
                    "description": "贷款本金",
                },
                "annual_rate": {
                    "type": "number",
                    "description": "年利率（如 0.06 表示 6%）",
                },
                "years": {
                    "type": "integer",
                    "description": "贷款期限（年）",
                },
            },
            "required": ["principal", "annual_rate", "years"],
        },
    },
    {
        "name": "run_financial_model",
        "description": "运行完整财务模型。输入项目参数，返回所有财务指标（IRR、NPV、LCOE、回收期、DSCR等）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "项目名称",
                },
                "capacity_mw": {
                    "type": "number",
                    "description": "装机容量（MW）",
                },
                "technology_type": {
                    "type": "string",
                    "description": "技术类型（solar/wind/battery/hybrid）",
                },
                "capex_total": {
                    "type": "number",
                    "description": "CAPEX总额（美元）",
                },
                "equivalent_hours": {
                    "type": "number",
                    "description": "年等效满发小时数",
                },
                "ppa_price_per_kwh": {
                    "type": "number",
                    "description": "PPA电价（美元/kWh）",
                },
                "discount_rate": {
                    "type": "number",
                    "description": "折现率（如 0.10 表示 10%）",
                    "default": 0.10,
                },
                "debt_ratio": {
                    "type": "number",
                    "description": "债务比例（如 0.70 表示 70%）",
                    "default": 0.70,
                },
                "interest_rate": {
                    "type": "number",
                    "description": "贷款利率（如 0.06 表示 6%）",
                    "default": 0.06,
                },
                "loan_tenor_years": {
                    "type": "integer",
                    "description": "贷款期限（年）",
                    "default": 10,
                },
                "operation_years": {
                    "type": "integer",
                    "description": "运营年限",
                    "default": 25,
                },
                "construction_years": {
                    "type": "integer",
                    "description": "建设期年数",
                    "default": 2,
                },
                "opex_fixed_per_kw_year": {
                    "type": "number",
                    "description": "固定运维成本（美元/kW/年）",
                    "default": 15,
                },
                "degradation_rate": {
                    "type": "number",
                    "description": "年衰减率",
                    "default": 0.005,
                },
                "tax_rate": {
                    "type": "number",
                    "description": "税率",
                    "default": 0.25,
                },
            },
            "required": [
                "project_name",
                "capacity_mw",
                "technology_type",
                "capex_total",
                "equivalent_hours",
                "ppa_price_per_kwh",
            ],
        },
    },
    {
        "name": "run_sensitivity",
        "description": "运行敏感性分析。输入项目参数，返回各关键变量对IRR的影响范围。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "项目名称",
                },
                "capacity_mw": {
                    "type": "number",
                    "description": "装机容量（MW）",
                },
                "technology_type": {
                    "type": "string",
                    "description": "技术类型",
                },
                "capex_total": {
                    "type": "number",
                    "description": "CAPEX总额（美元）",
                },
                "equivalent_hours": {
                    "type": "number",
                    "description": "年等效满发小时数",
                },
                "ppa_price_per_kwh": {
                    "type": "number",
                    "description": "PPA电价（美元/kWh）",
                },
                "discount_rate": {
                    "type": "number",
                    "description": "折现率",
                    "default": 0.10,
                },
                "debt_ratio": {
                    "type": "number",
                    "description": "债务比例",
                    "default": 0.70,
                },
                "interest_rate": {
                    "type": "number",
                    "description": "贷款利率",
                    "default": 0.06,
                },
                "loan_tenor_years": {
                    "type": "integer",
                    "description": "贷款期限",
                    "default": 10,
                },
                "operation_years": {
                    "type": "integer",
                    "description": "运营年限",
                    "default": 25,
                },
                "construction_years": {
                    "type": "integer",
                    "description": "建设期年数",
                    "default": 2,
                },
                "opex_fixed_per_kw_year": {
                    "type": "number",
                    "description": "固定运维成本",
                    "default": 15,
                },
                "degradation_rate": {
                    "type": "number",
                    "description": "年衰减率",
                    "default": 0.005,
                },
                "tax_rate": {
                    "type": "number",
                    "description": "税率",
                    "default": 0.25,
                },
            },
            "required": [
                "project_name",
                "capacity_mw",
                "technology_type",
                "capex_total",
                "equivalent_hours",
                "ppa_price_per_kwh",
            ],
        },
    },
    {
        "name": "assess_offtaker_risk",
        "description": "购电方风险评估。输入购电方信息，返回五维风险评估结果。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "revenue_model": {
                    "type": "string",
                    "description": "收入模式（ppa/market/hybrid）",
                    "enum": ["ppa", "market", "hybrid"],
                },
                "ppa_type": {
                    "type": "string",
                    "description": "PPA类型（corporate/government/utility）",
                },
                "ppa_tenor_years": {
                    "type": "integer",
                    "description": "PPA期限（年）",
                },
                "counterparty_name": {
                    "type": "string",
                    "description": "购电方名称",
                },
                "counterparty_industry": {
                    "type": "string",
                    "description": "购电方行业",
                },
                "credit_rating": {
                    "type": "string",
                    "description": "信用评级（如 AAA, AA, A, BBB）",
                },
                "is_listed": {
                    "type": "boolean",
                    "description": "是否上市公司",
                },
                "debt_to_asset_ratio": {
                    "type": "number",
                    "description": "资产负债率",
                },
                "interest_coverage_ratio": {
                    "type": "number",
                    "description": "利息覆盖倍数",
                },
                "annual_free_cashflow": {
                    "type": "number",
                    "description": "年自由现金流",
                },
                "annual_electricity_cost": {
                    "type": "number",
                    "description": "年电费支出",
                },
                "country_risk_level": {
                    "type": "string",
                    "description": "国家风险等级",
                    "default": "medium",
                },
                "ppa_currency": {
                    "type": "string",
                    "description": "PPA计价货币",
                    "default": "USD",
                },
            },
            "required": ["revenue_model"],
        },
    },
]


# ═══════════════════════════════════════════════════════════════
# 工具处理函数
# ═══════════════════════════════════════════════════════════════

def handle_calculate_npv(params: Dict[str, Any]) -> Dict[str, Any]:
    cashflows = params["cashflows"]
    discount_rate = params["discount_rate"]
    npv = _calculate_npv(cashflows, discount_rate)
    return {
        "npv": round(npv, 2),
        "cashflows": cashflows,
        "discount_rate": discount_rate,
        "interpretation": f"项目NPV为 ${npv:,.2f}。{'✅ 项目可行（NPV > 0）' if npv > 0 else '❌ 项目不可行（NPV < 0）' if npv < 0 else '⚠️ NPV = 0，盈亏平衡'}",
    }


def handle_calculate_irr(params: Dict[str, Any]) -> Dict[str, Any]:
    cashflows = params["cashflows"]
    guess = params.get("guess", 0.1)
    irr = _calculate_irr(cashflows, guess)
    if irr is None:
        return {
            "irr": None,
            "error": "无法计算IRR（现金流可能全部为正或全部为负）",
        }
    return {
        "irr": round(irr, 6),
        "irr_percentage": f"{irr * 100:.2f}%",
        "interpretation": f"项目IRR为 {irr * 100:.2f}%。{'✅ 高于典型折现率10%' if irr > 0.10 else '⚠️ 低于典型折现率10%' if irr > 0 else '❌ 负IRR'}",
    }


def handle_calculate_lcoe(params: Dict[str, Any]) -> Dict[str, Any]:
    # 构建简化的config和annual_data
    config = {
        "costs": {
            "capex_total": params["capex_total"],
        },
        "financing": {
            "discount_rate": params["discount_rate"],
        },
        "technical": {
            "construction_years": params["construction_years"],
        },
    }

    degradation_rate = params.get("degradation_rate", 0.005)
    annual_data = []
    for y in range(1, params["operation_years"] + 1):
        generation = params["annual_generation_kwh"] * (1 - degradation_rate) ** (y - 1)
        opex = params["annual_opex"] * (1 + 0.02) ** (y - 1)  # 2% escalation
        annual_data.append({
            "year": y,
            "generation_kwh": generation,
            "opex_total": opex,
            "insurance": 0,
        })

    lcoe = _calculate_lcoe(config, annual_data)
    return {
        "lcoe_per_kwh": round(lcoe, 6),
        "lcoe_per_mwh": round(lcoe * 1000, 2),
        "lcoe_cents_per_kwh": round(lcoe * 100, 2),
        "interpretation": f"LCOE为 ${lcoe * 1000:.2f}/MWh (${lcoe * 100:.2f}¢/kWh)",
    }


def handle_calculate_payback(params: Dict[str, Any]) -> Dict[str, Any]:
    cashflows = params["cashflows"]
    payback = _calculate_payback(cashflows)
    if payback is None:
        return {
            "payback_years": None,
            "error": "无法计算回收期（项目可能永远无法回收投资）",
        }
    return {
        "payback_years": round(payback, 2),
        "interpretation": f"投资回收期为 {payback:.2f} 年",
    }


def handle_calculate_loan_payment(params: Dict[str, Any]) -> Dict[str, Any]:
    principal = params["principal"]
    annual_rate = params["annual_rate"]
    years = params["years"]
    payment = _calculate_loan_payment(principal, annual_rate, years)
    total_payment = payment * years
    total_interest = total_payment - principal
    return {
        "annual_payment": round(payment, 2),
        "monthly_payment": round(payment / 12, 2),
        "total_payment": round(total_payment, 2),
        "total_interest": round(total_interest, 2),
        "interpretation": f"年还款额 ${payment:,.2f}，总还款额 ${total_payment:,.2f}，总利息 ${total_interest:,.2f}",
    }


def handle_run_financial_model(params: Dict[str, Any]) -> Dict[str, Any]:
    # 构建项目配置
    config = {
        "project": {
            "name": params["project_name"],
            "capacity_mw": params["capacity_mw"],
            "technology_type": params.get("technology_type", "solar"),
        },
        "technical": {
            "equivalent_hours": params["equivalent_hours"],
            "construction_years": params.get("construction_years", 2),
            "operation_years": params.get("operation_years", 25),
            "degradation_rate": params.get("degradation_rate", 0.005),
        },
        "costs": {
            "capex_total": params["capex_total"],
            "capex_per_watt": params["capex_total"] / (params["capacity_mw"] * 1_000_000),
            "opex_fixed_per_kw_year": params.get("opex_fixed_per_kw_year", 15),
            "opex_escalation_rate": 0.02,
            "insurance_rate": 0.005,
        },
        "revenue": {
            "ppa_price_per_kwh": params["ppa_price_per_kwh"],
        },
        "financing": {
            "debt_ratio": params.get("debt_ratio", 0.70),
            "interest_rate": params.get("interest_rate", 0.06),
            "loan_tenor_years": params.get("loan_tenor_years", 10),
            "discount_rate": params.get("discount_rate", 0.10),
            "tax_rate": params.get("tax_rate", 0.25),
            "depreciation_years": 15,
        },
    }

    result = _run_scenario(config)

    # 格式化输出
    output = {
        "project_name": params["project_name"],
        "capacity_mw": params["capacity_mw"],
        "technology_type": params.get("technology_type", "solar"),
        "financial_metrics": {
            "project_irr": {
                "value": result["project_irr"],
                "formatted": f"{result['project_irr'] * 100:.2f}%" if result["project_irr"] else "N/A",
            },
            "equity_irr": {
                "value": result["equity_irr"],
                "formatted": f"{result['equity_irr'] * 100:.2f}%" if result["equity_irr"] else "N/A",
            },
            "project_npv": {
                "value": result["project_npv"],
                "formatted": f"${result['project_npv']:,.0f}",
            },
            "equity_npv": {
                "value": result["equity_npv"],
                "formatted": f"${result['equity_npv']:,.0f}",
            },
            "payback_years": {
                "value": result["payback_years"],
                "formatted": f"{result['payback_years']:.1f} 年" if result["payback_years"] else "N/A",
            },
            "lcoe_per_kwh": {
                "value": result["lcoe_per_kwh"],
                "formatted": f"${result['lcoe_per_kwh'] * 1000:.2f}/MWh",
            },
            "avg_dscr": {
                "value": result["avg_dscr"],
                "formatted": f"{result['avg_dscr']:.2f}x",
            },
            "min_dscr": {
                "value": result["min_dscr"],
                "formatted": f"{result['min_dscr']:.2f}x",
            },
        },
        "summary": {
            "total_capex": result["summary"]["total_capex"],
            "debt_amount": result["summary"]["debt_amount"],
            "equity_amount": result["summary"]["equity_amount"],
            "annual_loan_payment": result["summary"]["annual_loan_payment"],
        },
    }

    # 添加购电方风险评估（如果有）
    if "offtaker_risk" in result:
        output["offtaker_risk"] = result["offtaker_risk"]

    return output


def handle_run_sensitivity(params: Dict[str, Any]) -> Dict[str, Any]:
    # 构建项目配置
    config = {
        "project": {
            "name": params["project_name"],
            "capacity_mw": params["capacity_mw"],
            "technology_type": params.get("technology_type", "solar"),
        },
        "technical": {
            "equivalent_hours": params["equivalent_hours"],
            "construction_years": params.get("construction_years", 2),
            "operation_years": params.get("operation_years", 25),
            "degradation_rate": params.get("degradation_rate", 0.005),
        },
        "costs": {
            "capex_total": params["capex_total"],
            "capex_per_watt": params["capex_total"] / (params["capacity_mw"] * 1_000_000),
            "opex_fixed_per_kw_year": params.get("opex_fixed_per_kw_year", 15),
            "opex_escalation_rate": 0.02,
            "insurance_rate": 0.005,
        },
        "revenue": {
            "ppa_price_per_kwh": params["ppa_price_per_kwh"],
        },
        "financing": {
            "debt_ratio": params.get("debt_ratio", 0.70),
            "interest_rate": params.get("interest_rate", 0.06),
            "loan_tenor_years": params.get("loan_tenor_years", 10),
            "discount_rate": params.get("discount_rate", 0.10),
            "tax_rate": params.get("tax_rate", 0.25),
            "depreciation_years": 15,
        },
    }

    results = _run_sensitivity(config)

    output = {
        "project_name": params["project_name"],
        "sensitivity_results": [],
    }

    for sr in results:
        output["sensitivity_results"].append({
            "param_name": sr["param_name"],
            "project_irr_range": {
                "min": f"{sr['project_irr_range'][0] * 100:.2f}%" if sr['project_irr_range'][0] else "N/A",
                "max": f"{sr['project_irr_range'][1] * 100:.2f}%" if sr['project_irr_range'][1] else "N/A",
                "spread": f"{(sr['project_irr_range'][1] - sr['project_irr_range'][0]) * 100:.2f}%",
            },
            "equity_irr_range": {
                "min": f"{sr['equity_irr_range'][0] * 100:.2f}%" if sr['equity_irr_range'][0] else "N/A",
                "max": f"{sr['equity_irr_range'][1] * 100:.2f}%" if sr['equity_irr_range'][1] else "N/A",
                "spread": f"{(sr['equity_irr_range'][1] - sr['equity_irr_range'][0]) * 100:.2f}%",
            },
        })

    return output


def handle_assess_offtaker_risk(params: Dict[str, Any]) -> Dict[str, Any]:
    # 构建offtaker配置
    config = {
        "offtaker": {
            "revenue_model": params["revenue_model"],
            "ppa_type": params.get("ppa_type", "corporate"),
            "ppa_tenor_years": params.get("ppa_tenor_years", 15),
            "counterparty": {
                "name": params.get("counterparty_name", "未指定"),
                "industry": params.get("counterparty_industry", "general"),
                "credit_rating": params.get("credit_rating"),
                "is_listed": params.get("is_listed", False),
                "debt_to_asset_ratio": params.get("debt_to_asset_ratio"),
                "interest_coverage_ratio": params.get("interest_coverage_ratio"),
                "annual_free_cashflow": params.get("annual_free_cashflow"),
                "annual_electricity_cost": params.get("annual_electricity_cost"),
            },
        },
        "country_risk_level": params.get("country_risk_level", "medium"),
        "ppa_currency": params.get("ppa_currency", "USD"),
    }

    result = _assess_offtaker_risk(config)

    return {
        "revenue_model": result["revenue_model"],
        "composite_score": result["composite_score"],
        "risk_level": result["risk_level"],
        "risk_premium": result["risk_premium"],
        "dimension_scores": result["dimension_scores"],
        "details": result["details"],
    }


# ═══════════════════════════════════════════════════════════════
# MCP 协议处理
# ═══════════════════════════════════════════════════════════════

HANDLERS = {
    "calculate_npv": handle_calculate_npv,
    "calculate_irr": handle_calculate_irr,
    "calculate_lcoe": handle_calculate_lcoe,
    "calculate_payback": handle_calculate_payback,
    "calculate_loan_payment": handle_calculate_loan_payment,
    "run_financial_model": handle_run_financial_model,
    "run_sensitivity": handle_run_sensitivity,
    "assess_offtaker_risk": handle_assess_offtaker_risk,
}


def handle_request(request: Dict[str, Any]) -> Dict[str, Any]:
    """处理 MCP JSON-RPC 请求"""
    method = request.get("method", "")
    request_id = request.get("id")

    if method == "mcp.listTools":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": TOOLS},
        }

    if method == "mcp.callTool":
        params = request.get("params", {})
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})

        if tool_name in HANDLERS:
            try:
                result = HANDLERS[tool_name](tool_args)
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(result, indent=2, ensure_ascii=False, default=str),
                            }
                        ],
                    },
                }
            except Exception as e:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32000,
                        "message": str(e),
                    },
                }
        else:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": f"未知工具: {tool_name}",
                },
            }

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": -32601,
            "message": f"未知方法: {method}",
        },
    }


def main():
    """MCP 服务器主循环 - 通过 stdio 接收 JSON-RPC 请求"""
    # 输出启动信息到 stderr（避免干扰 stdout 的 JSON-RPC 通信）
    sys.stderr.write("MCP Financial Calculator Server running on stdio\n")
    sys.stderr.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
            response = handle_request(request)
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
        except json.JSONDecodeError as e:
            sys.stderr.write(f"JSON 解析错误: {e}\n")
            sys.stderr.flush()
        except Exception as e:
            sys.stderr.write(f"处理请求时出错: {e}\n")
            sys.stderr.flush()


if __name__ == "__main__":
    main()
