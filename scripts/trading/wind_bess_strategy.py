"""
wind_bess_strategy.py — 风储混合交易策略

策略逻辑：
  与 hybrid_strategy 类似，但光伏替换为风电。
  风电全天24h都有出力，但波动性大。

  每个时段 t 的运营决策：
  1. 负电价 → 风电弃风，从电网充电
  2. 低电价 → 比较从电网充电 vs 用风电充电的成本
  3. 中等电价 → 风电满发上网，BESS待机
  4. 高电价 → 风电满发上网，BESS放电

适用于：wind_bess
"""


def run_strategy(config):
    """
    运行风储混合交易策略。

    参数：
        config (dict): 完整的 project_config.yaml 内容

    返回：
        dict: 引擎可消费的年度参数
    """
    proj = config.get("project", {})
    tech = config.get("technical", {})
    rev = config.get("revenue", {})
    bess_config = config.get("bess", {})

    capacity_kw = proj.get("capacity_kw", proj.get("capacity_mw", 0) * 1000)
    equivalent_hours = tech.get("equivalent_hours", rev.get("equivalent_hours", 0))
    ppa_price = rev.get("ppa_price_per_kwh", 0)
    degradation_rate = tech.get("degradation_rate", 0.003)

    # 风电参数
    wind_capacity_kw = bess_config.get("wind_capacity_kw", capacity_kw)
    wind_equivalent_hours = bess_config.get("wind_equivalent_hours", equivalent_hours)

    # BESS 参数
    bess_capacity_kw = bess_config.get("bess_capacity_kw", capacity_kw * 0.3)
    duration_hours = bess_config.get("duration_hours", 2)
    rte = bess_config.get("round_trip_efficiency", 0.85)
    max_charge_rate = bess_config.get("max_charge_rate", 1.0)
    max_discharge_rate = bess_config.get("max_discharge_rate", 1.0)
    charge_threshold = bess_config.get("charge_price_threshold", 0.05)
    discharge_threshold = bess_config.get("discharge_price_threshold", 0.15)
    grid_charge_premium = bess_config.get("grid_charge_premium", 0.01)
    initial_soc = bess_config.get("initial_soc", 0.5)
    min_soc = bess_config.get("min_soc", 0.1)
    max_soc = bess_config.get("max_soc", 0.9)

    energy_capacity_kwh = bess_capacity_kw * duration_hours
    charge_power_kw = bess_capacity_kw * max_charge_rate
    discharge_power_kw = bess_capacity_kw * max_discharge_rate

    # 获取电价曲线
    price_curve = config.get("price_curve", None)
    if price_curve and "hours" in price_curve:
        hours = price_curve["hours"]
    else:
        hours = _generate_default_price_curve(ppa_price)

    num_hours = len(hours)

    # 风电逐时段出力曲线（假设夜间出力大，白天小）
    wind_profile = _generate_wind_profile(num_hours)

    # 逐时段模拟
    soc = initial_soc
    total_wind_generation = 0
    total_wind_to_grid = 0
    total_wind_curtailed = 0
    total_wind_to_bess = 0
    total_grid_charge_kwh = 0
    total_discharge_kwh = 0
    total_grid_charge_cost = 0
    total_wind_revenue = 0
    total_discharge_revenue = 0
    total_cycles = 0
    trading_log = []

    for t in range(num_hours):
        price = hours[t]
        wind_power_ratio = wind_profile[t % len(wind_profile)]
        wind_generation = wind_capacity_kw * wind_power_ratio
        total_wind_generation += wind_generation

        action = "idle"
        wind_to_grid = 0
        wind_curtailed = 0
        wind_to_bess = 0
        grid_charge = 0
        discharge_to_grid = 0
        cost = 0
        revenue = 0

        if price < 0:
            # 负电价 → 弃风，从电网充电
            wind_curtailed = wind_generation
            total_wind_curtailed += wind_curtailed

            available_capacity = (max_soc - soc) * energy_capacity_kwh
            max_charge_energy = charge_power_kw * 1
            charge_energy = min(available_capacity, max_charge_energy)

            if charge_energy > 0:
                soc += charge_energy / energy_capacity_kwh
                total_grid_charge_kwh += charge_energy
                charge_cost = price * charge_energy
                total_grid_charge_cost += charge_cost
                grid_charge = charge_energy
                cost = charge_cost
                action = "grid_charge"

        elif price <= charge_threshold:
            # 低电价 → 比较成本
            grid_cost = price + grid_charge_premium
            wind_opportunity_cost = price

            if grid_cost < wind_opportunity_cost:
                wind_curtailed = wind_generation
                total_wind_curtailed += wind_curtailed

                available_capacity = (max_soc - soc) * energy_capacity_kwh
                max_charge_energy = charge_power_kw * 1
                charge_energy = min(available_capacity, max_charge_energy)

                if charge_energy > 0:
                    soc += charge_energy / energy_capacity_kwh
                    total_grid_charge_kwh += charge_energy
                    charge_cost = price * charge_energy
                    total_grid_charge_cost += charge_cost
                    grid_charge = charge_energy
                    cost = charge_cost
                    action = "grid_charge"
            else:
                available_capacity = (max_soc - soc) * energy_capacity_kwh
                max_charge_energy = charge_power_kw * 1
                charge_from_wind = min(wind_generation, available_capacity, max_charge_energy)

                if charge_from_wind > 0:
                    soc += charge_from_wind / energy_capacity_kwh
                    total_wind_to_bess += charge_from_wind
                    wind_to_bess = charge_from_wind

                remaining = wind_generation - charge_from_wind
                if remaining > 0:
                    total_wind_to_grid += remaining
                    wind_to_grid = remaining
                    wind_rev = price * remaining
                    total_wind_revenue += wind_rev
                    revenue += wind_rev

                action = "wind_charge"

        elif price >= discharge_threshold:
            # 高电价
            total_wind_to_grid += wind_generation
            wind_to_grid = wind_generation
            wind_rev = price * wind_generation
            total_wind_revenue += wind_rev
            revenue += wind_rev

            available_energy = (soc - min_soc) * energy_capacity_kwh
            max_discharge_energy = discharge_power_kw * 1
            discharge_energy = min(available_energy, max_discharge_energy)

            if discharge_energy > 0:
                grid_energy = discharge_energy * rte
                soc -= discharge_energy / energy_capacity_kwh
                total_discharge_kwh += grid_energy
                discharge_rev = price * grid_energy
                total_discharge_revenue += discharge_rev
                revenue += discharge_rev
                discharge_to_grid = grid_energy
                total_cycles += discharge_energy / energy_capacity_kwh / 2
                action = "discharge"
            else:
                action = "wind_only"

        else:
            # 中等电价
            total_wind_to_grid += wind_generation
            wind_to_grid = wind_generation
            wind_rev = price * wind_generation
            total_wind_revenue += wind_rev
            revenue += wind_rev
            action = "wind_only"

        trading_log.append({
            "hour": t,
            "price": price,
            "action": action,
            "wind_generation": wind_generation,
            "wind_to_grid": wind_to_grid,
            "wind_curtailed": wind_curtailed,
            "wind_to_bess": wind_to_bess,
            "grid_charge": grid_charge,
            "discharge_to_grid": discharge_to_grid,
            "soc": round(soc, 4),
            "cost": round(cost, 2),
            "revenue": round(revenue, 2),
        })

    # 年化：将典型日结果按 365 天扩展
    days_per_year = 365
    annual_wind_to_grid = total_wind_to_grid * days_per_year
    annual_discharge_kwh = total_discharge_kwh * days_per_year
    annual_wind_curtailed = total_wind_curtailed * days_per_year
    annual_grid_charge = total_grid_charge_kwh * days_per_year
    annual_wind_revenue = total_wind_revenue * days_per_year
    annual_discharge_revenue = total_discharge_revenue * days_per_year
    annual_grid_charge_cost = total_grid_charge_cost * days_per_year
    annual_cycles = total_cycles * days_per_year
    annual_wind_generation = total_wind_generation * days_per_year

    total_energy_to_grid = annual_wind_to_grid + annual_discharge_kwh
    total_revenue = annual_wind_revenue + annual_discharge_revenue + annual_grid_charge_cost

    weighted_avg_price = total_revenue / total_energy_to_grid if total_energy_to_grid > 0 else 0
    effective_hours = total_energy_to_grid / capacity_kw if capacity_kw > 0 else 0

    return {
        "weighted_avg_price": weighted_avg_price,
        "effective_hours": effective_hours,
        "annual_energy_kwh": total_energy_to_grid,
        "bess_cycles": annual_cycles,
        "curtailment_kwh": annual_wind_curtailed,
        "grid_charge_kwh": annual_grid_charge,
        "trading_log": trading_log,
        "degradation_rate": degradation_rate,
        "_wind_bess_details": {
            "total_wind_generation": annual_wind_generation,
            "total_wind_to_grid": annual_wind_to_grid,
            "total_wind_to_bess": total_wind_to_bess * days_per_year,
            "total_wind_curtailed": annual_wind_curtailed,
            "total_grid_charge_kwh": annual_grid_charge,
            "total_discharge_kwh": annual_discharge_kwh,
            "total_wind_revenue": annual_wind_revenue,
            "total_discharge_revenue": annual_discharge_revenue,
            "total_grid_charge_cost": annual_grid_charge_cost,
            "total_revenue": total_revenue,
            "curtailment_rate": annual_wind_curtailed / annual_wind_generation if annual_wind_generation > 0 else 0,
        },
    }


def _generate_default_price_curve(ppa_price):
    """生成默认的典型日电价曲线。"""
    base = ppa_price
    return [
        base * 0.3, base * 0.25, base * 0.2, base * 0.15,
        base * 0.2, base * 0.3, base * 0.5, base * 0.7,
        base * 0.9, base * 1.0, base * 1.1, base * 1.2,
        base * 1.3, base * 1.2, base * 1.1, base * 1.0,
        base * 0.9, base * 0.8, base * 1.4, base * 1.5,
        base * 1.3, base * 1.0, base * 0.7, base * 0.5,
    ]


def _generate_wind_profile(num_hours):
    """生成风电逐时段出力曲线（夜间出力大）。"""
    profile = [0.0] * 24
    profile[0] = 0.8
    profile[1] = 0.85
    profile[2] = 0.9
    profile[3] = 0.85
    profile[4] = 0.8
    profile[5] = 0.7
    profile[6] = 0.6
    profile[7] = 0.5
    profile[8] = 0.4
    profile[9] = 0.35
    profile[10] = 0.3
    profile[11] = 0.3
    profile[12] = 0.35
    profile[13] = 0.4
    profile[14] = 0.45
    profile[15] = 0.5
    profile[16] = 0.55
    profile[17] = 0.6
    profile[18] = 0.65
    profile[19] = 0.7
    profile[20] = 0.75
    profile[21] = 0.8
    profile[22] = 0.85
    profile[23] = 0.85
    return profile
