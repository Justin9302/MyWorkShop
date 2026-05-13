"""
wind_strategy.py — 风电交易策略

策略逻辑：
  - 风电满发上网，不弃光
  - 收入 = 年发电量 × 加权平均电价
  - 加权平均电价 = 全天24h电价曲线的算术平均

适用于：wind
"""


def run_strategy(config):
    """
    运行风电交易策略。

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
    degradation_rate = tech.get("degradation_rate", 0.003)

    annual_generation = capacity_kw * equivalent_hours

    # 风电：全天发电，取24h平均电价
    price_curve = config.get("price_curve", None)
    if price_curve and "hours" in price_curve:
        hours = price_curve["hours"]
        if hours:
            weighted_avg_price = sum(hours) / len(hours)
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
