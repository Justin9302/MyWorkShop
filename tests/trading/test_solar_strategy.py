"""
光伏交易策略测试

测试覆盖：
  1. 基本功能：满发上网，无弃光
  2. 电价曲线：有/无电价曲线
  3. 边界条件：零容量、零电价
  4. 一致性：多次运行结果一致
"""

import sys
import json
from pathlib import Path

# 将项目根目录加入 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.trading.solar_strategy import run_strategy


def test_basic_solar():
    """测试基本光伏策略：满发上网"""
    config = {
        "project": {"name": "Test", "technology_type": "solar", "capacity_mw": 100, "capacity_kw": 100000},
        "technical": {"equivalent_hours": 1600, "degradation_rate": 0.005},
        "revenue": {"ppa_price_per_kwh": 0.12, "equivalent_hours": 1600},
    }
    result = run_strategy(config)

    # 年上网电量 = 100MW × 1600h = 160GWh
    expected_energy = 100000 * 1600  # 160,000,000 kWh
    assert abs(result["annual_energy_kwh"] - expected_energy) < 1, \
        f"年上网电量错误: {result['annual_energy_kwh']} != {expected_energy}"

    # 加权平均电价 = PPA电价（无电价曲线时）
    assert abs(result["weighted_avg_price"] - 0.12) < 0.001, \
        f"加权平均电价错误: {result['weighted_avg_price']}"

    # 无BESS相关输出
    assert result["bess_cycles"] == 0
    assert result["curtailment_kwh"] == 0
    assert result["grid_charge_kwh"] == 0

    print("  ✅ test_basic_solar 通过")


def test_solar_with_price_curve():
    """测试有电价曲线时的加权平均电价计算"""
    config = {
        "project": {"name": "Test", "technology_type": "solar", "capacity_mw": 100, "capacity_kw": 100000},
        "technical": {"equivalent_hours": 1600, "degradation_rate": 0.005},
        "revenue": {"ppa_price_per_kwh": 0.12, "equivalent_hours": 1600},
        "price_curve": {
            "hours": [
                0.02, 0.02, 0.02, 0.02, 0.02, 0.02,  # 0-5: 低价
                0.08, 0.10, 0.12, 0.14, 0.15, 0.16,  # 6-11: 光伏时段
                0.17, 0.16, 0.15, 0.14, 0.12, 0.10,  # 12-17: 光伏时段
                0.20, 0.22, 0.20, 0.18, 0.15, 0.10,  # 18-23
            ],
        },
    }
    result = run_strategy(config)

    # 光伏时段 6:00-18:00（索引6到18）
    solar_hours = [0.08, 0.10, 0.12, 0.14, 0.15, 0.16, 0.17, 0.16, 0.15, 0.14, 0.12, 0.10, 0.20]
    expected_price = sum(solar_hours) / len(solar_hours)

    assert abs(result["weighted_avg_price"] - expected_price) < 0.001, \
        f"加权平均电价错误: {result['weighted_avg_price']} != {expected_price}"

    print(f"  ✅ test_solar_with_price_curve 通过 (电价: ${expected_price:.4f})")


def test_solar_zero_capacity():
    """测试零装机容量边界"""
    config = {
        "project": {"name": "Test", "technology_type": "solar", "capacity_mw": 0, "capacity_kw": 0},
        "technical": {"equivalent_hours": 1600, "degradation_rate": 0.005},
        "revenue": {"ppa_price_per_kwh": 0.12, "equivalent_hours": 1600},
    }
    result = run_strategy(config)

    assert result["annual_energy_kwh"] == 0, "零容量时年上网电量应为0"
    # solar_strategy 直接返回 equivalent_hours 作为 effective_hours
    # 零容量时发电量为0，但等效小时数仍为配置值
    assert result["effective_hours"] == 1600, \
        f"零容量时等效小时数应为配置值1600: {result['effective_hours']}"

    print("  ✅ test_solar_zero_capacity 通过")


def test_solar_zero_price():
    """测试零电价边界"""
    config = {
        "project": {"name": "Test", "technology_type": "solar", "capacity_mw": 100, "capacity_kw": 100000},
        "technical": {"equivalent_hours": 1600, "degradation_rate": 0.005},
        "revenue": {"ppa_price_per_kwh": 0.0, "equivalent_hours": 1600},
    }
    result = run_strategy(config)

    assert result["weighted_avg_price"] == 0, "零电价时加权平均电价应为0"
    assert result["annual_energy_kwh"] > 0, "零电价时发电量不应为0"

    print("  ✅ test_solar_zero_price 通过")


def test_solar_consistency():
    """测试多次运行结果一致性"""
    config = {
        "project": {"name": "Test", "technology_type": "solar", "capacity_mw": 100, "capacity_kw": 100000},
        "technical": {"equivalent_hours": 1600, "degradation_rate": 0.005},
        "revenue": {"ppa_price_per_kwh": 0.12, "equivalent_hours": 1600},
    }

    results = [run_strategy(config) for _ in range(5)]
    for i in range(1, len(results)):
        assert results[i]["annual_energy_kwh"] == results[0]["annual_energy_kwh"], \
            f"运行{i}与运行0结果不一致"
        assert results[i]["weighted_avg_price"] == results[0]["weighted_avg_price"], \
            f"运行{i}与运行0结果不一致"

    print("  ✅ test_solar_consistency 通过")


if __name__ == "__main__":
    print("=" * 50)
    print("光伏交易策略测试")
    print("=" * 50)
    test_basic_solar()
    test_solar_with_price_curve()
    test_solar_zero_capacity()
    test_solar_zero_price()
    test_solar_consistency()
    print("=" * 50)
    print("所有测试通过 ✅")
