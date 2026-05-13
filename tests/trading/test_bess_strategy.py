"""
BESS 交易策略测试

测试覆盖：
  1. 基本功能：低充高放套利
  2. 负电价场景：负电价时充电（负成本=收益）
  3. 效率影响：RTE 对净放电量的影响
  4. SOC 边界：min_soc / max_soc 限制
  5. 无套利空间：电价始终在阈值之间
  6. 一致性：多次运行结果一致
  7. 年化验证：典型日 × 365 = 年化结果
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.trading.bess_strategy import run_strategy


def _make_config(price_curve=None, **overrides):
    """创建标准 BESS 测试配置"""
    config = {
        "project": {"name": "Test BESS", "technology_type": "bess", "capacity_mw": 100, "capacity_kw": 100000},
        "technical": {"equivalent_hours": 1460, "degradation_rate": 0.02},
        "revenue": {"ppa_price_per_kwh": 0.12, "equivalent_hours": 1460},
        "bess": {
            "duration_hours": 2,
            "round_trip_efficiency": 0.85,
            "charge_price_threshold": 0.05,
            "discharge_price_threshold": 0.15,
            "max_charge_rate": 1.0,
            "max_discharge_rate": 1.0,
            "initial_soc": 0.5,
            "min_soc": 0.1,
            "max_soc": 0.9,
        },
    }
    if price_curve:
        config["price_curve"] = {"hours": price_curve}
    config.update(overrides)
    return config


def test_basic_arbitrage():
    """测试基本套利：低充高放"""
    # 简单峰谷曲线：前12h低价，后12h高价
    price_curve = [0.03] * 12 + [0.20] * 12
    config = _make_config(price_curve)
    result = run_strategy(config)

    # 应该有充放电活动
    assert result["bess_cycles"] > 0, "应有循环次数"
    assert result["annual_energy_kwh"] > 0, "应有上网电量"
    assert result["grid_charge_kwh"] > 0, "应有充电量"

    # 加权平均电价应高于充电电价
    assert result["weighted_avg_price"] > 0.05, \
        f"加权平均电价应高于充电阈值: {result['weighted_avg_price']}"

    # 净收入应为正
    assert result["_bess_details"]["net_revenue"] > 0, "套利应有正净收入"

    print(f"  ✅ test_basic_arbitrage 通过 (循环: {result['bess_cycles']:.0f}, 收入: ${result['_bess_details']['net_revenue']/1e6:.2f}M)")


def test_negative_price():
    """测试负电价场景：负电价时充电（负成本=收益）"""
    # 前6h负电价，后6h高电价
    price_curve = [-0.03, -0.02, -0.01, -0.02, -0.03, -0.01] + [0.20] * 18
    config = _make_config(price_curve)
    result = run_strategy(config)

    # 应有充电活动（负电价时）
    assert result["grid_charge_kwh"] > 0, "负电价时应有充电"

    # 充电成本应为负（即收益）
    charge_cost = result["_bess_details"]["total_charge_cost"]
    assert charge_cost < 0, f"负电价时充电成本应为负: {charge_cost}"

    # 净收入应为正
    assert result["_bess_details"]["net_revenue"] > 0, "负电价套利应有正净收入"

    print(f"  ✅ test_negative_price 通过 (充电成本: ${charge_cost/1e6:.2f}M, 净收入: ${result['_bess_details']['net_revenue']/1e6:.2f}M)")


def test_rte_impact():
    """测试充放电效率对结果的影响"""
    # 相同电价曲线，不同 RTE
    price_curve = [0.03] * 12 + [0.20] * 12

    config_85 = _make_config(price_curve)
    config_85["bess"]["round_trip_efficiency"] = 0.85
    result_85 = run_strategy(config_85)

    config_95 = _make_config(price_curve)
    config_95["bess"]["round_trip_efficiency"] = 0.95
    result_95 = run_strategy(config_95)

    # 高效率应产生更多净上网电量
    assert result_95["annual_energy_kwh"] > result_85["annual_energy_kwh"], \
        f"RTE 95% ({result_95['annual_energy_kwh']}) 应 > RTE 85% ({result_85['annual_energy_kwh']})"

    # 高效率应产生更多净收入
    assert result_95["_bess_details"]["net_revenue"] > result_85["_bess_details"]["net_revenue"], \
        "高效率应产生更多净收入"

    print(f"  ✅ test_rte_impact 通过 (RTE 85%: {result_85['annual_energy_kwh']/1e6:.2f}GWh, RTE 95%: {result_95['annual_energy_kwh']/1e6:.2f}GWh)")


def test_soc_bounds():
    """测试 SOC 边界限制"""
    # 长时间低价后长时间高价，验证 SOC 不会超出 [min_soc, max_soc]
    price_curve = [0.03] * 24 + [0.20] * 24  # 48小时
    config = _make_config(price_curve)
    result = run_strategy(config)

    # 检查 trading_log 中的 SOC 范围
    soc_values = [log["soc"] for log in result["trading_log"]]
    min_soc_observed = min(soc_values)
    max_soc_observed = max(soc_values)

    assert min_soc_observed >= 0.09, f"SOC 低于 min_soc: {min_soc_observed}"
    assert max_soc_observed <= 0.91, f"SOC 高于 max_soc: {max_soc_observed}"

    print(f"  ✅ test_soc_bounds 通过 (SOC范围: {min_soc_observed:.2f} ~ {max_soc_observed:.2f})")


def test_no_arbitrage():
    """测试无套利空间：电价始终在阈值之间"""
    price_curve = [0.10] * 24  # 始终在 0.05~0.15 之间
    config = _make_config(price_curve)
    result = run_strategy(config)

    # 不应有充放电活动
    assert result["bess_cycles"] == 0, "无套利空间时循环次数应为0"
    assert result["annual_energy_kwh"] == 0, "无套利空间时上网电量应为0"
    assert result["grid_charge_kwh"] == 0, "无套利空间时充电量应为0"

    print("  ✅ test_no_arbitrage 通过")


def test_annualization():
    """验证年化逻辑：典型日 × 365 = 年化结果"""
    price_curve = [0.03] * 12 + [0.20] * 12
    config = _make_config(price_curve)
    result = run_strategy(config)

    # 检查年化倍数关系
    details = result["_bess_details"]
    days = 365

    # 年化充电量 = 典型日充电量 × 365
    assert abs(details["total_charge_kwh"] - result["grid_charge_kwh"]) < 1, \
        "年化充电量不一致"

    # 年化循环次数 = 典型日循环次数 × 365
    # 注意：trading_log 是典型日的，所以 total_cycles 是典型日的
    # 但 result["bess_cycles"] 已经是年化的
    daily_cycles = sum(
        log["action"] == "discharge" for log in result["trading_log"]
    ) / 2  # 每次放电算半次循环
    expected_annual_cycles = daily_cycles * days
    assert abs(result["bess_cycles"] - expected_annual_cycles) < days, \
        f"年化循环次数不一致: {result['bess_cycles']} != {expected_annual_cycles}"

    print(f"  ✅ test_annualization 通过 (日循环: {daily_cycles:.1f}, 年循环: {result['bess_cycles']:.0f})")


def test_consistency():
    """测试多次运行结果一致性"""
    price_curve = [0.03] * 12 + [0.20] * 12
    config = _make_config(price_curve)

    results = [run_strategy(config) for _ in range(5)]
    for i in range(1, len(results)):
        assert results[i]["annual_energy_kwh"] == results[0]["annual_energy_kwh"], \
            f"运行{i}与运行0结果不一致"
        assert results[i]["bess_cycles"] == results[0]["bess_cycles"], \
            f"运行{i}与运行0结果不一致"

    print("  ✅ test_consistency 通过")


def test_duration_impact():
    """测试储能时长对结果的影响"""
    price_curve = [0.03] * 12 + [0.20] * 12

    config_2h = _make_config(price_curve)
    config_2h["bess"]["duration_hours"] = 2
    result_2h = run_strategy(config_2h)

    config_4h = _make_config(price_curve)
    config_4h["bess"]["duration_hours"] = 4
    result_4h = run_strategy(config_4h)

    # 4h 储能应有更多上网电量
    assert result_4h["annual_energy_kwh"] > result_2h["annual_energy_kwh"], \
        "4h储能应产生更多上网电量"

    # 4h 储能应有更多净收入
    assert result_4h["_bess_details"]["net_revenue"] > result_2h["_bess_details"]["net_revenue"], \
        "4h储能应产生更多净收入"

    print(f"  ✅ test_duration_impact 通过 (2h: {result_2h['annual_energy_kwh']/1e6:.2f}GWh, 4h: {result_4h['annual_energy_kwh']/1e6:.2f}GWh)")


if __name__ == "__main__":
    print("=" * 50)
    print("BESS 交易策略测试")
    print("=" * 50)
    test_basic_arbitrage()
    test_negative_price()
    test_rte_impact()
    test_soc_bounds()
    test_no_arbitrage()
    test_annualization()
    test_consistency()
    test_duration_impact()
    print("=" * 50)
    print("所有测试通过 ✅")
