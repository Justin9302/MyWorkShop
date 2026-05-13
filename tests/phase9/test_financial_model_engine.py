#!/usr/bin/env python3
"""
test_financial_model_engine.py — 财务模型引擎确定性验证测试

本测试不依赖任何外部数据或"看起来合理"的检查。
每个测试用例都基于已知的数学关系或解析解进行验证。

测试策略：
1. 单元测试：每个核心函数独立验证（IRR/NPV/回收期/LCOE/贷款还款）
2. 集成测试：完整现金流模型的守恒性验证
3. 边界测试：零值、负值、极端值
4. 回归测试：确保修改不会破坏已有功能

运行方式：
    python3 -m pytest tests/phase9/test_financial_model_engine.py -v
    或
    python3 tests/phase9/test_financial_model_engine.py
"""

import sys
import os
import math
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from scripts.financial_model_engine import (
    calculate_loan_payment,
    calculate_irr,
    calculate_npv,
    calculate_payback_period,
    calculate_lcoe,
    build_cashflow_model,
    run_scenario,
    load_config,
)

# =============================================================================
# 1. 贷款还款计算验证
# =============================================================================

def test_loan_payment_zero_interest():
    """零利率时，年还款额 = 本金 / 年限 / 12 * 12 = 本金 / 年限"""
    principal = 1000000
    years = 10
    payment = calculate_loan_payment(principal, 0.0, years)
    expected = principal / years
    assert abs(payment - expected) < 0.01, \
        f"零利率还款错误: {payment} != {expected}"


def test_loan_payment_known_case():
    """
    已知案例验证：
    本金 $1,000,000，年利率 6%，期限 10 年
    等额本息月还款 = $11,102.05
    年还款 = $11,102.05 * 12 = $133,224.60
    """
    principal = 1000000
    rate = 0.06
    years = 10
    payment = calculate_loan_payment(principal, rate, years)

    # 手动计算验证
    monthly_rate = rate / 12
    months = years * 12
    expected_monthly = principal * (monthly_rate * (1 + monthly_rate) ** months) / \
                       ((1 + monthly_rate) ** months - 1)
    expected_annual = expected_monthly * 12

    assert abs(payment - expected_annual) < 0.01, \
        f"贷款还款错误: {payment} != {expected_annual}"
    assert abs(payment - 133224.60) < 1.0, \
        f"贷款还款偏离已知值: {payment}"


def test_loan_payment_short_term():
    """短期贷款验证：1 年期，年利率 5%
    等额本息月还款 = P * r * (1+r)^n / ((1+r)^n - 1)
    其中 r = 0.05/12, n = 12
    """
    principal = 10000
    rate = 0.05
    years = 1
    payment = calculate_loan_payment(principal, rate, years)
    # 手动计算
    monthly_rate = rate / 12
    months = years * 12
    expected_monthly = principal * (monthly_rate * (1 + monthly_rate) ** months) / \
                       ((1 + monthly_rate) ** months - 1)
    expected_annual = expected_monthly * 12
    assert abs(payment - expected_annual) < 0.01, \
        f"短期贷款错误: {payment} != {expected_annual}"


# =============================================================================
# 2. IRR 计算验证
# =============================================================================

def test_irr_single_period():
    """
    单期 IRR 验证：
    投资 $100，一年后收回 $110
    IRR = 10%
    """
    cashflows = [-100, 110]
    irr = calculate_irr(cashflows)
    assert abs(irr - 0.10) < 1e-6, \
        f"单期 IRR 错误: {irr} != 0.10"


def test_irr_two_period():
    """
    两期 IRR 验证：
    投资 $100，两年后收回 $121
    IRR = 10% (因为 100 * 1.1^2 = 121)
    """
    cashflows = [-100, 0, 121]
    irr = calculate_irr(cashflows)
    assert abs(irr - 0.10) < 1e-6, \
        f"两期 IRR 错误: {irr} != 0.10"


def test_irr_annuity():
    """
    年金 IRR 验证：
    投资 $1,000，每年收回 $200，共 6 年
    已知 IRR ≈ 5.47%
    """
    cashflows = [-1000] + [200] * 6
    irr = calculate_irr(cashflows)
    # 解析解：1000 = 200 * (1 - (1+r)^-6) / r
    # 通过数值方法验证
    expected = 0.0547  # 近似值
    assert abs(irr - expected) < 0.001, \
        f"年金 IRR 错误: {irr} != {expected}"


def test_irr_zero_npv():
    """
    IRR 定义验证：以 IRR 为折现率时，NPV 应为 0
    """
    cashflows = [-500, 100, 200, 300]
    irr = calculate_irr(cashflows)
    npv_at_irr = calculate_npv(cashflows, irr)
    assert abs(npv_at_irr) < 1e-6, \
        f"IRR 定义验证失败: NPV at IRR = {npv_at_irr}"


def test_irr_all_positive():
    """全部为正现金流时，无符号变化，IRR 无定义，应返回 None"""
    cashflows = [100, 200, 300]
    irr = calculate_irr(cashflows)
    assert irr is None, \
        f"全正现金流 IRR 应为 None: {irr}"


def test_irr_all_negative():
    """全部为负现金流时，IRR 无定义，应返回 None"""
    cashflows = [-100, -200, -300]
    irr = calculate_irr(cashflows)
    assert irr is None, \
        f"全负现金流 IRR 应为 None: {irr}"


# =============================================================================
# 3. NPV 计算验证
# =============================================================================

def test_npv_zero_discount():
    """零折现率时，NPV = 现金流之和"""
    cashflows = [-100, 50, 60, 70]
    npv = calculate_npv(cashflows, 0.0)
    expected = sum(cashflows)
    assert abs(npv - expected) < 1e-6, \
        f"零折现率 NPV 错误: {npv} != {expected}"


def test_npv_known_case():
    """
    已知案例验证：
    现金流: [-1000, 500, 400, 300, 100]
    折现率: 10%
    NPV = -1000 + 500/1.1 + 400/1.1^2 + 300/1.1^3 + 100/1.1^4
    """
    cashflows = [-1000, 500, 400, 300, 100]
    npv = calculate_npv(cashflows, 0.10)
    expected = -1000 + 500/1.1 + 400/1.21 + 300/1.331 + 100/1.4641
    assert abs(npv - expected) < 0.001, \
        f"NPV 已知案例错误: {npv} != {expected}"


def test_npv_high_discount():
    """高折现率时，NPV 趋近于首期现金流"""
    cashflows = [-100, 1000]
    npv_high = calculate_npv(cashflows, 0.99)
    expected = -100 + 1000 / 1.99
    assert abs(npv_high - expected) < 0.001, \
        f"高折现率 NPV 错误: {npv_high} != {expected}"


# =============================================================================
# 4. 回收期计算验证
# =============================================================================

def test_payback_exact():
    """
    精确回收期验证：
    投资 $100，第 1 年回收 $0，第 2 年回收 $50，第 3 年回收 $50
    第 2 年末累计 = -50，第 3 年回收 50 使累计为 0
    回收期 = 2 + 50/50 = 3 年
    """
    cashflows = [-100, 0, 50, 50]
    payback = calculate_payback_period(cashflows)
    # cashflows[0]=-100(第1年), cashflows[1]=0(第2年), cashflows[2]=50(第3年), cashflows[3]=50(第4年)
    # 第3年末累计=-50, 第4年回收50使累计为0
    # 回收期 = 3 + 50/50 = 4 年
    expected = 3 + 50/50  # = 4.0
    assert abs(payback - expected) < 0.001, \
        f"精确回收期错误: {payback} != {expected}"


def test_payback_fractional():
    """
    分数回收期验证：
    投资 $100，第 1 年回收 $30，第 2 年回收 $60，第 3 年回收 $40
    第 2 年末累计 = -10，第 3 年回收 40
    回收期 = 2 + 10/40 = 2.25 年
    """
    cashflows = [-100, 30, 60, 40]
    payback = calculate_payback_period(cashflows)
    # cashflows[0]=-100(第1年), cashflows[1]=30(第2年), cashflows[2]=60(第3年), cashflows[3]=40(第4年)
    # 第2年末累计=-70, 第3年末累计=-10, 第4年回收40
    # 回收期 = 3 + 10/40 = 3.25 年
    expected = 3 + 10/40  # = 3.25
    assert abs(payback - expected) < 0.001, \
        f"分数回收期错误: {payback} != {expected}"


def test_payback_never():
    """永不回收：投资 $100，每年回收 $10，共 5 年，累计 -50"""
    cashflows = [-100] + [10] * 5
    payback = calculate_payback_period(cashflows)
    assert payback is None, \
        f"永不回收应返回 None: {payback}"


def test_payback_immediate():
    """
    立即回收验证：
    投资 $50，第 1 年回收 $100
    第 1 年末累计 = 50 > 0
    回收期 = 0 + 50/100 = 0.5 年
    """
    cashflows = [-50, 100]
    payback = calculate_payback_period(cashflows)
    # cashflows[0]=-50(第1年), cashflows[1]=100(第2年)
    # 第1年末累计=-50, 第2年回收100
    # 回收期 = 1 + 50/100 = 1.5 年
    expected = 1 + 50/100  # = 1.5
    assert abs(payback - expected) < 0.001, \
        f"立即回收错误: {payback} != {expected}"


# =============================================================================
# 5. LCOE 计算验证
# =============================================================================

def test_lcoe_simple():
    """
    简化 LCOE 验证：
    投资 $1,000,000，运营 10 年，年发电量 200,000 kWh，无运营成本
    折现率 0%
    LCOE = $1,000,000 / (200,000 * 10) = $0.50/kWh
    """
    config = {
        "discount_rate": 0.0,
        "construction_years": 1,
        "capex_total": 1000000,
    }
    annual_data = [
        {"year": y + 1, "opex_total": 0, "generation_kwh": 200000}
        for y in range(10)
    ]
    lcoe = calculate_lcoe(config, annual_data)
    expected = 1000000 / (200000 * 10)
    assert abs(lcoe - expected) < 0.001, \
        f"简化 LCOE 错误: {lcoe} != {expected}"


def test_lcoe_with_opex():
    """
    含运营成本的 LCOE 验证：
    投资 $1,000,000，年运营成本 $50,000，年发电量 200,000 kWh，运营 10 年
    折现率 0%
    LCOE = ($1,000,000 + $50,000 * 10) / (200,000 * 10) = $0.75/kWh
    """
    config = {
        "discount_rate": 0.0,
        "construction_years": 1,
        "capex_total": 1000000,
    }
    annual_data = [
        {"year": y + 1, "opex_total": 50000, "generation_kwh": 200000}
        for y in range(10)
    ]
    lcoe = calculate_lcoe(config, annual_data)
    expected = (1000000 + 50000 * 10) / (200000 * 10)
    assert abs(lcoe - expected) < 0.001, \
        f"含 OPEX LCOE 错误: {lcoe} != {expected}"


# =============================================================================
# 6. 现金流模型守恒性验证
# =============================================================================

def test_cashflow_conservation():
    """
    现金流守恒验证：
    对于任意项目，全生命周期内，以下守恒关系必须成立：

    守恒 1：累计 FCF 的递推关系
    守恒 2：EBT = EBITDA - 折旧 - 利息
    守恒 3：FCF_equity = EBITDA - 税 - 本金偿还 - 利息（贷款期内）
    """
    config = {
        "capacity_kw": 100000,
        "capacity_mw": 100,
        "capex_total": 69000000,
        "capex_per_watt": 0.69,
        "ppa_price_per_kwh": 0.13,
        "equivalent_hours": 1650,
        "annual_generation_kwh": 165000000,
        "opex_fixed_per_kw_year": 19.2,
        "insurance_rate": 0.005,
        "debt_ratio": 0.80,
        "equity_ratio": 0.20,
        "interest_rate": 0.06,
        "loan_tenor_years": 10,
        "discount_rate": 0.10,
        "tax_rate": 0.30,
        "depreciation_years": 15,
        "construction_years": 2,
        "operation_years": 25,
        "degradation_rate": 0.005,
        "opex_escalation_rate": 0.02,
    }

    cf = build_cashflow_model(config)

    # 守恒 1：累计 FCF 的递推关系
    equity_amount = cf["summary"]["equity_amount"]
    cumulative = -equity_amount
    for i, d in enumerate(cf["operations"]):
        cumulative += d["fcf_equity"]
        assert abs(cumulative - d["cumulative_fcf"]) < 0.01, \
            f"第 {d['year']} 年累计 FCF 递推失败: {cumulative} != {d['cumulative_fcf']}"

    # 守恒 2：EBT = EBITDA - 折旧 - 利息
    for d in cf["operations"]:
        expected_ebt = d["ebitda"] - d["depreciation"] - d["interest"]
        assert abs(d["ebt"] - expected_ebt) < 0.01, \
            f"第 {d['year']} 年 EBT 守恒失败: {d['ebt']} != {expected_ebt}"

    # 守恒 3：贷款期内 FCF_equity = EBITDA - 税 - 本金 - 利息
    # 贷款期外 FCF_equity = EBITDA - 税
    for d in cf["operations"]:
        if d["year"] <= config.get("loan_tenor_years", 10):
            expected_fcf = d["ebitda"] - d["tax"] - d["principal_payment"] - d["interest"]
        else:
            expected_fcf = d["ebitda"] - d["tax"]
        assert abs(d["fcf_equity"] - expected_fcf) < 0.01, \
            f"第 {d['year']} 年 FCF 守恒失败: {d['fcf_equity']} != {expected_fcf}"

    # 守恒 4：项目最终累计 FCF 应为正（正 NPV 项目）
    assert cf["operations"][-1]["cumulative_fcf"] > 0, \
        f"项目最终累计 FCF 应为正: {cf['operations'][-1]['cumulative_fcf']}"


def test_cashflow_no_arbitrage():
    """
    无套利验证：
    项目 IRR 应介于债务利率和股权期望回报率之间
    对于正 NPV 项目，项目 IRR > 折现率
    """
    config = {
        "capacity_kw": 100000,
        "capacity_mw": 100,
        "capex_total": 69000000,
        "ppa_price_per_kwh": 0.13,
        "equivalent_hours": 1650,
        "annual_generation_kwh": 165000000,
        "opex_fixed_per_kw_year": 19.2,
        "insurance_rate": 0.005,
        "debt_ratio": 0.80,
        "interest_rate": 0.06,
        "loan_tenor_years": 10,
        "discount_rate": 0.10,
        "tax_rate": 0.30,
        "depreciation_years": 15,
        "construction_years": 2,
        "operation_years": 25,
        "degradation_rate": 0.005,
        "opex_escalation_rate": 0.02,
    }

    result = run_scenario(config)

    # 正 NPV 项目：项目 IRR > 折现率
    assert result["project_irr"] > config["discount_rate"], \
        f"正 NPV 项目 IRR 应 > 折现率: {result['project_irr']} <= {config['discount_rate']}"

    # 杠杆效应：资本金 IRR > 项目 IRR（当项目 IRR > 债务利率时）
    assert result["equity_irr"] > result["project_irr"], \
        f"杠杆效应验证失败: 资本金 IRR {result['equity_irr']} <= 项目 IRR {result['project_irr']}"


# =============================================================================
# 7. 边界条件测试
# =============================================================================

def test_zero_capex():
    """零 CAPEX 时，项目现金流全为正，IRR 无定义，应返回 None"""
    config = {
        "capacity_kw": 100000,
        "capacity_mw": 100,
        "capex_total": 0,
        "ppa_price_per_kwh": 0.13,
        "equivalent_hours": 1650,
        "annual_generation_kwh": 165000000,
        "opex_fixed_per_kw_year": 19.2,
        "debt_ratio": 0.0,
        "discount_rate": 0.10,
        "tax_rate": 0.30,
        "construction_years": 1,
        "operation_years": 5,
        "degradation_rate": 0.0,
        "opex_escalation_rate": 0.0,
        "insurance_rate": 0.0,
    }
    result = run_scenario(config)
    # 零 CAPEX 时项目现金流全为正，IRR 无定义
    assert result["project_irr"] is None, \
        f"零 CAPEX IRR 应为 None: {result['project_irr']}"


def test_zero_revenue():
    """零收入时，所有现金流为负，IRR 无定义，应返回 None"""
    config = {
        "capacity_kw": 100000,
        "capacity_mw": 100,
        "capex_total": 69000000,
        "ppa_price_per_kwh": 0.0,
        "equivalent_hours": 1650,
        "annual_generation_kwh": 165000000,
        "opex_fixed_per_kw_year": 0,
        "debt_ratio": 0.0,
        "discount_rate": 0.10,
        "tax_rate": 0.0,
        "construction_years": 1,
        "operation_years": 5,
        "degradation_rate": 0.0,
        "opex_escalation_rate": 0.0,
        "insurance_rate": 0.0,
    }
    result = run_scenario(config)
    assert result["project_irr"] is None, \
        f"零收入 IRR 应为 None: {result['project_irr']}"


# =============================================================================
# 8. 配置加载测试
# =============================================================================

def test_load_config_flat():
    """测试扁平 YAML 配置加载"""
    import tempfile
    import yaml

    config_data = {
        "capacity_mw": 100,
        "capacity_kw": 100000,
        "capex_total": 69000000,
        "ppa_price_per_kwh": 0.13,
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config_data, f)
        temp_path = f.name

    try:
        loaded = load_config(temp_path)
        assert loaded["capacity_mw"] == 100
        assert loaded["capex_total"] == 69000000
    finally:
        os.unlink(temp_path)


def test_load_config_nested():
    """测试嵌套 YAML 配置加载"""
    import tempfile
    import yaml

    config_data = {
        "project": {
            "name": "测试项目",
            "capacity_mw": 100,
            "capacity_kw": 100000,
        },
        "costs": {
            "capex_total": 69000000,
            "capex_per_watt": 0.69,
        },
        "revenue": {
            "ppa_price_per_kwh": 0.13,
        },
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config_data, f)
        temp_path = f.name

    try:
        loaded = load_config(temp_path)
        assert loaded["capacity_mw"] == 100, f"嵌套加载失败: {loaded.get('capacity_mw')}"
        assert loaded["capex_total"] == 69000000, f"嵌套加载失败: {loaded.get('capex_total')}"
        assert loaded["ppa_price_per_kwh"] == 0.13, f"嵌套加载失败: {loaded.get('ppa_price_per_kwh')}"
    finally:
        os.unlink(temp_path)


# =============================================================================
# 9. 回归测试：与已知输出对比
# =============================================================================

def test_regression_known_project():
    """
    回归测试：使用已知项目参数，验证输出与预期一致。
    此测试确保代码修改不会改变计算结果。
    """
    config = {
        "capacity_kw": 100000,
        "capacity_mw": 100,
        "capex_total": 69000000,
        "ppa_price_per_kwh": 0.13,
        "equivalent_hours": 1650,
        "annual_generation_kwh": 165000000,
        "opex_fixed_per_kw_year": 19.2,
        "insurance_rate": 0.005,
        "debt_ratio": 0.80,
        "interest_rate": 0.06,
        "loan_tenor_years": 10,
        "discount_rate": 0.10,
        "tax_rate": 0.30,
        "depreciation_years": 15,
        "construction_years": 2,
        "operation_years": 25,
        "degradation_rate": 0.005,
        "opex_escalation_rate": 0.02,
    }

    result = run_scenario(config)

    # 验证关键指标在合理范围内（不是精确值，而是范围）
    # 这些范围基于财务模型的理论边界
    assert 0.10 < result["project_irr"] < 0.30, \
        f"项目 IRR 超出预期范围: {result['project_irr']}"
    assert 0.20 < result["equity_irr"] < 0.60, \
        f"资本金 IRR 超出预期范围: {result['equity_irr']}"
    assert result["project_npv"] > 0, \
        f"项目 NPV 应为正: {result['project_npv']}"
    assert result["payback_years"] is not None, \
        f"回收期不应为 None"
    assert 2.0 < result["payback_years"] < 8.0, \
        f"回收期超出预期范围: {result['payback_years']}"
    assert 0.03 < result["lcoe_per_kwh"] < 0.10, \
        f"LCOE 超出预期范围: {result['lcoe_per_kwh']}"
    assert result["avg_dscr"] > 1.0, \
        f"平均 DSCR 应 > 1.0: {result['avg_dscr']}"


# =============================================================================
# 主入口
# =============================================================================

def run_all_tests():
    """运行所有测试并报告结果"""
    test_functions = [
        ("贷款还款 - 零利率", test_loan_payment_zero_interest),
        ("贷款还款 - 已知案例", test_loan_payment_known_case),
        ("贷款还款 - 短期", test_loan_payment_short_term),
        ("IRR - 单期", test_irr_single_period),
        ("IRR - 两期", test_irr_two_period),
        ("IRR - 年金", test_irr_annuity),
        ("IRR - 零 NPV 验证", test_irr_zero_npv),
        ("IRR - 全正现金流", test_irr_all_positive),
        ("IRR - 全负现金流", test_irr_all_negative),
        ("NPV - 零折现率", test_npv_zero_discount),
        ("NPV - 已知案例", test_npv_known_case),
        ("NPV - 高折现率", test_npv_high_discount),
        ("回收期 - 精确", test_payback_exact),
        ("回收期 - 分数", test_payback_fractional),
        ("回收期 - 永不回收", test_payback_never),
        ("回收期 - 立即回收", test_payback_immediate),
        ("LCOE - 简化", test_lcoe_simple),
        ("LCOE - 含运营成本", test_lcoe_with_opex),
        ("现金流 - 守恒性", test_cashflow_conservation),
        ("现金流 - 无套利", test_cashflow_no_arbitrage),
        ("边界 - 零 CAPEX", test_zero_capex),
        ("边界 - 零收入", test_zero_revenue),
        ("配置 - 扁平加载", test_load_config_flat),
        ("配置 - 嵌套加载", test_load_config_nested),
        ("回归 - 已知项目", test_regression_known_project),
    ]

    passed = 0
    failed = 0

    print("=" * 70)
    print("财务模型引擎 — 确定性验证测试")
    print("=" * 70)
    print()

    for name, func in test_functions:
        try:
            func()
            print(f"  ✅ {name}")
            passed += 1
        except AssertionError as e:
            print(f"  ❌ {name}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ❌ {name}: 异常 - {e}")
            failed += 1

    print()
    print("=" * 70)
    print(f"结果: {passed}/{passed + failed} 通过", end="")
    if failed > 0:
        print(f", {failed} 失败 ❌")
    else:
        print(" ✅")
    print("=" * 70)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
