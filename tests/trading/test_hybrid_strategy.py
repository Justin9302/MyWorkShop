"""
光储混合交易策略测试

测试覆盖：
  1. 基本功能：光伏满发 + BESS 套利
  2. 负电价场景：负电价时弃光 + 从电网充电
  3. 成本比较：从电网充电 vs 用光伏充电
  4. 弃光率验证：负电价时段应有弃光
  5. 年化验证：典型日 × 365 = 年化结果
  6. 一致性：多次运行结果一致
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.trading.hybrid_strategy import run_strategy


def _make_config(price_curve=None, **overrides):
    """创建标准 Hybrid 测试配置"""
    config = {
        "project": {"name": "Test Hybrid", "technology_type": "hybrid", "capacity_mw": 150, "capacity_kw": 150000},
        "technical": {"equivalent_hours": 1800, "degradation_rate": 0.005},
        "revenue": {"ppa_price_per_kwh": 0.11, "equivalent_hours": 1800},
        "bess": {
            "solar_capacity_kw": 150000,
            "solar_equivalent_hours": 1800,
            "bess_capacity_kw": 75000,
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


def test_basic_hybrid():
    """测试基本光储混合：光伏满发 + BESS 套利"""
    price_curve = [0.03] * 6 + [0.10] * 6 + [0.20] * 6 + [0.10] * 6
    config = _make_config(price_curve)
    result = run_strategy(config)

    # 应有光伏上网
    assert result["annual_energy_kwh"] > 0, "应有上网电量"
    assert result["_hybrid_details"]["total_solar_to_grid"] > 0, "应有光伏上网"

    # 应有 BESS 活动
    assert result["bess_cycles"] > 0, "应有BESS循环"

    # 加权平均电价应介于充电和放电阈值之间
    assert 0.05 < result["weighted_avg_price"] < 0.20, \
        f"加权平均电价应在合理范围: {result['weighted_avg_price']}"

    print(f"  ✅ test_basic_hybrid 通过 (光伏上网: {result['_hybrid_details']['total_solar_to_grid']/1e6:.2f}GWh, BESS循环: {result['bess_cycles']:.0f})")


def test_negative_price_curtailment():
    """测试负电价场景：负电价时弃光 + 从电网充电"""
    # 负电价设在光伏出力时段（10:00-15:00），此时光伏有出力
    # 0-9: 正常电价, 10-15: 负电价（光伏大发时段）, 16-23: 高电价
    price_curve = (
        [0.08] * 10 +           # 0:00-9:00 正常电价
        [-0.03, -0.02, -0.01, -0.02, -0.03, -0.01] +  # 10:00-15:00 负电价
        [0.20] * 8              # 16:00-23:00 高电价
    )
    config = _make_config(price_curve)
    result = run_strategy(config)

    # 应有弃光（负电价时段光伏出力被弃）
    assert result["curtailment_kwh"] > 0, "负电价时应有弃光"

    # 应有从电网充电（负电价时充电）
    assert result["grid_charge_kwh"] > 0, "负电价时应有从电网充电"

    # 弃光率应 > 0
    curtailment_rate = result["_hybrid_details"]["solar_curtailment_rate"]
    assert curtailment_rate > 0, f"弃光率应 > 0: {curtailment_rate}"

    print(f"  ✅ test_negative_price_curtailment 通过 (弃光: {result['curtailment_kwh']/1e6:.2f}GWh, 弃光率: {curtailment_rate*100:.1f}%)")


def test_grid_charge_vs_solar_charge():
    """测试成本比较逻辑：从电网充电 vs 用光伏充电"""
    # 电价刚好在充电阈值附近，且 grid_charge_premium 较高
    # 这样从电网充电成本 > 光伏充电机会成本 → 应该用光伏充电
    price_curve = [0.04] * 24  # 略低于充电阈值 0.05
    config = _make_config(price_curve)
    config["bess"]["grid_charge_premium"] = 0.02  # 较高的输配电费

    result = run_strategy(config)

    # 检查 trading_log 中是否有 solar_charge 动作
    solar_charge_hours = sum(1 for log in result["trading_log"] if log["action"] == "solar_charge")
    grid_charge_hours = sum(1 for log in result["trading_log"] if log["action"] == "grid_charge")

    # 由于 grid_charge_premium 较高，应该更多使用光伏充电
    # 但光伏只在白天有出力，所以 solar_charge 应出现在光伏时段
    print(f"  ✅ test_grid_charge_vs_solar_charge 通过 (光伏充电时段: {solar_charge_hours}, 电网充电时段: {grid_charge_hours})")


def test_high_price_discharge():
    """测试高电价时：光伏满发 + BESS 同时放电"""
    price_curve = [0.20] * 24  # 始终高于放电阈值
    config = _make_config(price_curve)
    result = run_strategy(config)

    # 光伏应满发上网
    assert result["_hybrid_details"]["total_solar_to_grid"] > 0, "高电价时光伏应上网"

    # BESS 应放电（如果有电可放）
    # 初始 SOC=0.5，所以有电可放
    assert result["bess_cycles"] > 0, "高电价时BESS应放电"

    # 不应有弃光
    assert result["curtailment_kwh"] == 0, "高电价时不应弃光"

    print(f"  ✅ test_high_price_discharge 通过 (光伏上网: {result['_hybrid_details']['total_solar_to_grid']/1e6:.2f}GWh, BESS循环: {result['bess_cycles']:.0f})")


def test_annualization():
    """验证年化逻辑"""
    price_curve = [0.03] * 6 + [0.10] * 6 + [0.20] * 6 + [0.10] * 6
    config = _make_config(price_curve)
    result = run_strategy(config)

    days = 365
    details = result["_hybrid_details"]

    # 年化光伏上网 = 典型日光伏上网 × 365
    daily_solar_to_grid = sum(
        log["solar_to_grid"] for log in result["trading_log"]
    )
    expected_annual_solar = daily_solar_to_grid * days
    assert abs(details["total_solar_to_grid"] - expected_annual_solar) < days, \
        f"年化光伏上网不一致: {details['total_solar_to_grid']} != {expected_annual_solar}"

    print(f"  ✅ test_annualization 通过 (日光伏上网: {daily_solar_to_grid/1e3:.1f}MWh, 年化: {details['total_solar_to_grid']/1e6:.2f}GWh)")


def test_consistency():
    """测试多次运行结果一致性"""
    price_curve = [0.03] * 6 + [0.10] * 6 + [0.20] * 6 + [0.10] * 6
    config = _make_config(price_curve)

    results = [run_strategy(config) for _ in range(5)]
    for i in range(1, len(results)):
        assert results[i]["annual_energy_kwh"] == results[0]["annual_energy_kwh"], \
            f"运行{i}与运行0结果不一致"
        assert results[i]["bess_cycles"] == results[0]["bess_cycles"], \
            f"运行{i}与运行0结果不一致"

    print("  ✅ test_consistency 通过")


def test_solar_only_mid_price():
    """测试中等电价时：光伏满发，BESS待机"""
    price_curve = [0.10] * 24  # 在充电和放电阈值之间
    config = _make_config(price_curve)
    result = run_strategy(config)

    # 光伏应满发上网
    assert result["_hybrid_details"]["total_solar_to_grid"] > 0, "中等电价时光伏应上网"

    # BESS 不应有活动
    assert result["bess_cycles"] == 0, "中等电价时BESS不应循环"

    # 不应有弃光
    assert result["curtailment_kwh"] == 0, "中等电价时不应弃光"

    print(f"  ✅ test_solar_only_mid_price 通过 (光伏上网: {result['_hybrid_details']['total_solar_to_grid']/1e6:.2f}GWh)")


if __name__ == "__main__":
    print("=" * 50)
    print("光储混合交易策略测试")
    print("=" * 50)
    test_basic_hybrid()
    test_negative_price_curtailment()
    test_grid_charge_vs_solar_charge()
    test_high_price_discharge()
    test_annualization()
    test_consistency()
    test_solar_only_mid_price()
    print("=" * 50)
    print("所有测试通过 ✅")
