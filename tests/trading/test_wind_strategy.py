"""
风电交易策略测试

测试覆盖：
  1. 基本功能：满发上网
  2. 边界条件：零容量
  3. 一致性：多次运行结果一致
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.trading.wind_strategy import run_strategy


def test_basic_wind():
    """测试基本风电策略：满发上网"""
    config = {
        "project": {"name": "Test", "technology_type": "wind", "capacity_mw": 200, "capacity_kw": 200000},
        "technical": {"equivalent_hours": 2800, "degradation_rate": 0.003},
        "revenue": {"ppa_price_per_kwh": 0.10, "equivalent_hours": 2800},
    }
    result = run_strategy(config)

    expected_energy = 200000 * 2800  # 560,000,000 kWh
    assert abs(result["annual_energy_kwh"] - expected_energy) < 1, \
        f"年上网电量错误: {result['annual_energy_kwh']} != {expected_energy}"
    assert abs(result["weighted_avg_price"] - 0.10) < 0.001, \
        f"加权平均电价错误: {result['weighted_avg_price']}"

    print(f"  ✅ test_basic_wind 通过 ({result['annual_energy_kwh']/1e6:.2f}GWh)")


def test_wind_zero_capacity():
    """测试零装机容量边界"""
    config = {
        "project": {"name": "Test", "technology_type": "wind", "capacity_mw": 0, "capacity_kw": 0},
        "technical": {"equivalent_hours": 2800, "degradation_rate": 0.003},
        "revenue": {"ppa_price_per_kwh": 0.10, "equivalent_hours": 2800},
    }
    result = run_strategy(config)
    assert result["annual_energy_kwh"] == 0, "零容量时年上网电量应为0"
    print("  ✅ test_wind_zero_capacity 通过")


def test_wind_consistency():
    """测试多次运行结果一致性"""
    config = {
        "project": {"name": "Test", "technology_type": "wind", "capacity_mw": 200, "capacity_kw": 200000},
        "technical": {"equivalent_hours": 2800, "degradation_rate": 0.003},
        "revenue": {"ppa_price_per_kwh": 0.10, "equivalent_hours": 2800},
    }
    results = [run_strategy(config) for _ in range(5)]
    for i in range(1, len(results)):
        assert results[i]["annual_energy_kwh"] == results[0]["annual_energy_kwh"]
    print("  ✅ test_wind_consistency 通过")


if __name__ == "__main__":
    print("=" * 50)
    print("风电交易策略测试")
    print("=" * 50)
    test_basic_wind()
    test_wind_zero_capacity()
    test_wind_consistency()
    print("=" * 50)
    print("所有测试通过 ✅")
