"""
风储混合交易策略测试

测试覆盖：
  1. 基本功能：风电满发 + BESS 套利
  2. 负电价场景：负电价时弃风 + 从电网充电
  3. 高电价场景：风电满发 + BESS 放电
  4. 年化验证
  5. 一致性
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.trading.wind_bess_strategy import run_strategy


def _make_config(price_curve=None, **overrides):
    config = {
        "project": {"name": "Test Wind+BESS", "technology_type": "wind_bess", "capacity_mw": 200, "capacity_kw": 200000},
        "technical": {"equivalent_hours": 2800, "degradation_rate": 0.003},
        "revenue": {"ppa_price_per_kwh": 0.10, "equivalent_hours": 2800},
        "bess": {
            "wind_capacity_kw": 200000,
            "bess_capacity_kw": 60000,
            "duration_hours": 2,
            "round_trip_efficiency": 0.85,
            "charge_price_threshold": 0.05,
            "discharge_price_threshold": 0.15,
            "grid_charge_premium": 0.01,
            "initial_soc": 0.5,
            "min_soc": 0.1,
            "max_soc": 0.9,
        },
    }
    if price_curve:
        config["price_curve"] = {"hours": price_curve}
    config.update(overrides)
    return config


def test_basic_wind_bess():
    """测试基本风储混合"""
    price_curve = [0.03] * 12 + [0.20] * 12
    config = _make_config(price_curve)
    result = run_strategy(config)

    assert result["annual_energy_kwh"] > 0, "应有上网电量"
    assert result["bess_cycles"] > 0, "应有BESS循环"
    assert result["_wind_bess_details"]["total_wind_to_grid"] > 0, "应有风电上网"

    print(f"  ✅ test_basic_wind_bess 通过 (风电上网: {result['_wind_bess_details']['total_wind_to_grid']/1e6:.2f}GWh, BESS循环: {result['bess_cycles']:.0f})")


def test_negative_price_curtailment():
    """测试负电价时弃风"""
    price_curve = [-0.03, -0.02, -0.01, -0.02, -0.03, -0.01] + [0.10] * 6 + [0.20] * 6 + [0.10] * 6
    config = _make_config(price_curve)
    result = run_strategy(config)

    assert result["curtailment_kwh"] > 0, "负电价时应有弃风"
    assert result["grid_charge_kwh"] > 0, "负电价时应有从电网充电"

    print(f"  ✅ test_negative_price_curtailment 通过 (弃风: {result['curtailment_kwh']/1e6:.2f}GWh)")


def test_high_price_discharge():
    """测试高电价时风电满发 + BESS放电"""
    price_curve = [0.20] * 24
    config = _make_config(price_curve)
    result = run_strategy(config)

    assert result["_wind_bess_details"]["total_wind_to_grid"] > 0, "高电价时风电应上网"
    assert result["bess_cycles"] > 0, "高电价时BESS应放电"
    assert result["curtailment_kwh"] == 0, "高电价时不应弃风"

    print(f"  ✅ test_high_price_discharge 通过 (BESS循环: {result['bess_cycles']:.0f})")


def test_annualization():
    """验证年化逻辑"""
    price_curve = [0.03] * 12 + [0.20] * 12
    config = _make_config(price_curve)
    result = run_strategy(config)

    days = 365
    daily_wind_to_grid = sum(log["wind_to_grid"] for log in result["trading_log"])
    expected_annual = daily_wind_to_grid * days
    assert abs(result["_wind_bess_details"]["total_wind_to_grid"] - expected_annual) < days

    print(f"  ✅ test_annualization 通过 (日风电上网: {daily_wind_to_grid/1e3:.1f}MWh)")


def test_consistency():
    """测试多次运行结果一致性"""
    price_curve = [0.03] * 12 + [0.20] * 12
    config = _make_config(price_curve)
    results = [run_strategy(config) for _ in range(5)]
    for i in range(1, len(results)):
        assert results[i]["annual_energy_kwh"] == results[0]["annual_energy_kwh"]
    print("  ✅ test_consistency 通过")


if __name__ == "__main__":
    print("=" * 50)
    print("风储混合交易策略测试")
    print("=" * 50)
    test_basic_wind_bess()
    test_negative_price_curtailment()
    test_high_price_discharge()
    test_annualization()
    test_consistency()
    print("=" * 50)
    print("所有测试通过 ✅")
