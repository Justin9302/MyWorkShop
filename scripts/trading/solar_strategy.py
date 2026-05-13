"""
solar_strategy.py — 光伏交易策略

策略逻辑：
  - 光伏满发上网，不弃光
  - 收入 = 年发电量 × 加权平均电价
  - 加权平均电价 = 电价曲线的算术平均（光伏发电时段）

适用于：solar, hydro
"""


def run_strategy(config):
    """
    运行光伏交易策略。

    参数：
        config (dict): 完整的 project_config.yaml 内容

    返回：
        dict: 引擎可消费的年度参数
    """
    proj = config.get("project", {})
    tech = config.get("technical", {})
    rev = config.get("revenue", {})

    capacity_kw = proj.get("capacity_kw", proj.get("capacity_mw", 0) * 1000)
    equivalent_hours = tech.get("equivalent_hours", rev.get("equivalent_hours", 0))
    ppa_price = rev.get("ppa_price_per_kwh", 0)
    degradation_rate = tech.get("degradation_rate", 0.005)

    # 光伏：满发上网，无弃光
    annual_generation = capacity_kw * equivalent_hours

    # 加权平均电价 = PPA电价（光伏发电时段）
    # 如果有电价曲线，计算光伏发电时段的加权平均电价
    price_curve = config.get("price_curve", None)
    if price_curve and "hours" in price_curve:
        # 光伏发电时段：6:00-18:00
        solar_hours = price_curve["hours"][6:19]  # 索引6到18（含）
        if solar_hours:
            weighted_avg_price = sum(solar_hours) / len(solar_hours)
        else:
            weighted_avg_price = ppa_price
    else:
        weighted_avg_price = ppa_price

    return {
        "weighted_avg_price": weighted_avg_price,
        "effective_hours": equivalent_hours,
        "annual_energy_kwh": annual_generation,
        "bess_cycles": 0,
        "curtailment_kwh": 0,
        "grid_charge_kwh": 0,
        "trading_log": [],
        "degradation_rate": degradation_rate,
    }
