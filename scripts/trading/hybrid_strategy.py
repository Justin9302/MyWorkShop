"""
hybrid_strategy.py — 光储混合交易策略

策略逻辑（核心：综合成本最优）：
  每个时段 t 的运营决策：

  1. 获取当前电网电价 P_grid(t)
  2. 获取光伏即时出力 P_solar(t)
  3. 获取 BESS 当前 SOC

  4. 如果 P_grid(t) < 0（负电价）：
     → 光伏弃光（或限功率）
     → 从电网充电（负成本 = 收益）
     → 充电功率 = min(BESS剩余容量, 最大充电功率)

  5. 如果 0 < P_grid(t) < charge_threshold（低电价）：
     → 比较：从电网充电 vs 用光伏充电
     → 从电网充电的综合成本 = P_grid(t) + grid_charge_premium
     → 用光伏充电的机会成本 = 光伏上网电价（弃光损失）
     → 如果 从电网充电成本 < 光伏充电机会成本 → 从电网充电，光伏弃光
     → 否则 → 光伏给 BESS 充电

  6. 如果 charge_threshold ≤ P_grid(t) ≤ discharge_threshold（中等电价）：
     → 光伏满发上网
     → BESS 不充不放（待机）

  7. 如果 P_grid(t) > discharge_threshold（高电价）：
     → 光伏满发上网
     → BESS 放电（高电价套利）

适用于：hybrid（光储一体）
"""


def run_strategy(config):
    """
    运行光储混合交易策略。

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
    degradation_rate = tech.get("degradation_rate", 0.005)

    # 光伏参数
    solar_capacity_kw = bess_config.get("solar_capacity_kw", capacity_kw)
    solar_equivalent_hours = bess_config.get("solar_equivalent_hours", equivalent_hours)

    # BESS 参数
    bess_capacity_kw = bess_config.get("bess_capacity_kw", capacity_kw * 0.5)
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

    # BESS 容量
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

    # 光伏逐时段出力曲线（假设正午最大，早晚低）
    solar_profile = _generate_solar_profile(num_hours)

    # 逐时段模拟
    soc = initial_soc
    total_solar_generation = 0  # 光伏总发电量
    total_solar_to_grid = 0  # 光伏上网电量
    total_solar_curtailed = 0  # 光伏弃电量
    total_solar_to_bess = 0  # 光伏给BESS充电量
    total_grid_charge_kwh = 0  # 从电网充电量
    total_discharge_kwh = 0  # BESS放电到电网量
    total_grid_charge_cost = 0  # 从电网充电成本
    total_solar_revenue = 0  # 光伏上网收入
    total_discharge_revenue = 0  # BESS放电收入
    total_cycles = 0
    trading_log = []

    for t in range(num_hours):
        price = hours[t]
        solar_power_ratio = solar_profile[t % len(solar_profile)]
        solar_generation = solar_capacity_kw * solar_power_ratio  # 当前时段光伏出力(kW)
        total_solar_generation += solar_generation

        action = "idle"
        solar_to_grid = 0
        solar_curtailed = 0
        solar_to_bess = 0
        grid_charge = 0
        discharge_to_grid = 0
        cost = 0
        revenue = 0

        # ── 决策逻辑 ──

        if price < 0:
            # 场景1: 负电价
            # 光伏弃光（或限功率）
            solar_curtailed = solar_generation
            total_solar_curtailed += solar_curtailed

            # 从电网充电（负电价 = 负成本 = 收益）
            available_capacity = (max_soc - soc) * energy_capacity_kwh
            max_charge_energy = charge_power_kw * 1
            charge_energy = min(available_capacity, max_charge_energy)

            if charge_energy > 0:
                soc += charge_energy / energy_capacity_kwh
                total_grid_charge_kwh += charge_energy
                charge_cost = price * charge_energy  # 负电价 → 负成本 → 收益
                total_grid_charge_cost += charge_cost
                grid_charge = charge_energy
                cost = charge_cost
                action = "grid_charge"

        elif price <= charge_threshold:
            # 场景2: 低电价（但 > 0）
            # 比较：从电网充电 vs 用光伏充电
            grid_charge_cost_per_kwh = price + grid_charge_premium
            solar_charge_opportunity_cost = price  # 弃光损失 = 本来可以卖电的收入

            if grid_charge_cost_per_kwh < solar_charge_opportunity_cost:
                # 从电网充电更便宜 → 光伏弃光，从电网充电
                solar_curtailed = solar_generation
                total_solar_curtailed += solar_curtailed

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
                # 用光伏充电更划算 → 光伏给BESS充电，余电上网
                available_capacity = (max_soc - soc) * energy_capacity_kwh
                max_charge_energy = charge_power_kw * 1
                charge_from_solar = min(solar_generation, available_capacity, max_charge_energy)

                if charge_from_solar > 0:
                    soc += charge_from_solar / energy_capacity_kwh
                    total_solar_to_bess += charge_from_solar
                    solar_to_bess = charge_from_solar

                # 余电上网
                remaining_solar = solar_generation - charge_from_solar
                if remaining_solar > 0:
                    total_solar_to_grid += remaining_solar
                    solar_to_grid = remaining_solar
                    solar_rev = price * remaining_solar
                    total_solar_revenue += solar_rev
                    revenue += solar_rev

                action = "solar_charge"

        elif price >= discharge_threshold:
            # 场景3: 高电价
            # 光伏满发上网
            total_solar_to_grid += solar_generation
            solar_to_grid = solar_generation
            solar_rev = price * solar_generation
            total_solar_revenue += solar_rev
            revenue += solar_rev

            # BESS 放电
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
                action = "solar_only"

        else:
            # 场景4: 中等电价
            # 光伏满发上网
            total_solar_to_grid += solar_generation
            solar_to_grid = solar_generation
            solar_rev = price * solar_generation
            total_solar_revenue += solar_rev
            revenue += solar_rev
            action = "solar_only"

        trading_log.append({
            "hour": t,
            "price": price,
            "action": action,
            "solar_generation": solar_generation,
            "solar_to_grid": solar_to_grid,
            "solar_curtailed": solar_curtailed,
            "solar_to_bess": solar_to_bess,
            "grid_charge": grid_charge,
            "discharge_to_grid": discharge_to_grid,
            "soc": round(soc, 4),
            "cost": round(cost, 2),
            "revenue": round(revenue, 2),
        })

    # 年化：将典型日结果按 365 天扩展
    days_per_year = 365
    annual_solar_to_grid = total_solar_to_grid * days_per_year
    annual_discharge_kwh = total_discharge_kwh * days_per_year
    annual_solar_curtailed = total_solar_curtailed * days_per_year
    annual_grid_charge = total_grid_charge_kwh * days_per_year
    annual_solar_revenue = total_solar_revenue * days_per_year
    annual_discharge_revenue = total_discharge_revenue * days_per_year
    annual_grid_charge_cost = total_grid_charge_cost * days_per_year
    annual_cycles = total_cycles * days_per_year
    annual_solar_generation = total_solar_generation * days_per_year

    total_energy_to_grid = annual_solar_to_grid + annual_discharge_kwh
    total_revenue = annual_solar_revenue + annual_discharge_revenue + annual_grid_charge_cost

    # 加权平均电价
    if total_energy_to_grid > 0:
        weighted_avg_price = total_revenue / total_energy_to_grid
    else:
        weighted_avg_price = 0

    # 等效年利用小时数（基于总上网电量）
    effective_hours = total_energy_to_grid / capacity_kw if capacity_kw > 0 else 0

    return {
        "weighted_avg_price": weighted_avg_price,
        "effective_hours": effective_hours,
        "annual_energy_kwh": total_energy_to_grid,
        "bess_cycles": annual_cycles,
        "curtailment_kwh": annual_solar_curtailed,
        "grid_charge_kwh": annual_grid_charge,
        "trading_log": trading_log,
        "degradation_rate": degradation_rate,
        "_hybrid_details": {
            "total_solar_generation": annual_solar_generation,
            "total_solar_to_grid": annual_solar_to_grid,
            "total_solar_to_bess": total_solar_to_bess * days_per_year,
            "total_solar_curtailed": annual_solar_curtailed,
            "total_grid_charge_kwh": annual_grid_charge,
            "total_discharge_kwh": annual_discharge_kwh,
            "total_solar_revenue": annual_solar_revenue,
            "total_discharge_revenue": annual_discharge_revenue,
            "total_grid_charge_cost": annual_grid_charge_cost,
            "total_revenue": total_revenue,
            "solar_curtailment_rate": annual_solar_curtailed / annual_solar_generation if annual_solar_generation > 0 else 0,
        },
    }


def _generate_default_price_curve(ppa_price):
    """生成默认的典型日电价曲线（含负电价示例）。"""
    base = ppa_price
    curve = [
        -0.01,   # 0:00 负电价
        -0.02,   # 1:00 负电价
        -0.03,   # 2:00 负电价（最低）
        -0.02,   # 3:00
        -0.01,   # 4:00
        base * 0.2,   # 5:00
        base * 0.4,   # 6:00
        base * 0.6,   # 7:00
        base * 0.8,   # 8:00
        base * 0.9,   # 9:00
        base * 1.0,   # 10:00
        base * 0.8,   # 11:00（光伏大发，电价下降）
        base * 0.5,   # 12:00（光伏大发，电价低）
        base * 0.4,   # 13:00（光伏大发，电价低）
        base * 0.5,   # 14:00
        base * 0.7,   # 15:00
        base * 0.9,   # 16:00
        base * 1.2,   # 17:00
        base * 1.5,   # 18:00 晚峰
        base * 1.8,   # 19:00 最高
        base * 1.5,   # 20:00
        base * 1.2,   # 21:00
        base * 0.8,   # 22:00
        base * 0.3,   # 23:00
    ]
    return curve


def _generate_solar_profile(num_hours):
    """
    生成光伏逐时段出力曲线。
    返回 24 个时段的出力比例（0.0 ~ 1.0）。
    """
    profile = [0.0] * 24
    # 6:00 开始出力
    profile[6] = 0.1
    profile[7] = 0.3
    profile[8] = 0.6
    profile[9] = 0.8
    profile[10] = 0.95
    profile[11] = 1.0   # 正午最大
    profile[12] = 1.0
    profile[13] = 0.95
    profile[14] = 0.85
    profile[15] = 0.7
    profile[16] = 0.5
    profile[17] = 0.25
    profile[18] = 0.05
    # 19:00-5:00 无出力
    return profile
