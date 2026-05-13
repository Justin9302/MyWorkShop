"""
bess_strategy.py — BESS 交易策略

策略逻辑：
  - 逐时段（默认1h）模拟 BESS 充放电决策
  - 低电价时充电，高电价时放电
  - 考虑 round-trip efficiency
  - 负电价时从电网充电（负成本 = 收益）
  - 输出加权平均电价和年等效循环次数

决策规则（每个时段）：
  1. 如果电价 < charge_threshold → 充电（从电网）
  2. 如果电价 > discharge_threshold → 放电（到电网）
  3. 否则 → 待机

适用于：bess, battery
"""


def run_strategy(config):
    """
    运行 BESS 交易策略。

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
    capacity_mw = capacity_kw / 1000
    equivalent_hours = tech.get("equivalent_hours", rev.get("equivalent_hours", 0))
    degradation_rate = tech.get("degradation_rate", 0.02)

    # BESS 参数
    duration_hours = bess_config.get("duration_hours", 2)  # 储能时长
    rte = bess_config.get("round_trip_efficiency", 0.85)  # 充放电效率
    max_charge_rate = bess_config.get("max_charge_rate", 1.0)  # C-rate
    max_discharge_rate = bess_config.get("max_discharge_rate", 1.0)
    charge_threshold = bess_config.get("charge_price_threshold", 0.05)
    discharge_threshold = bess_config.get("discharge_price_threshold", 0.15)
    grid_charge_premium = bess_config.get("grid_charge_premium", 0.01)
    initial_soc = bess_config.get("initial_soc", 0.5)
    min_soc = bess_config.get("min_soc", 0.1)
    max_soc = bess_config.get("max_soc", 0.9)

    # BESS 容量
    energy_capacity_kwh = capacity_kw * duration_hours  # 总储能容量
    charge_power_kw = capacity_kw * max_charge_rate
    discharge_power_kw = capacity_kw * max_discharge_rate

    # 获取电价曲线
    price_curve = config.get("price_curve", None)
    if price_curve and "hours" in price_curve:
        hours = price_curve["hours"]
    else:
        # 如果没有电价曲线，使用 PPA 电价生成一个简单的峰谷曲线
        ppa_price = rev.get("ppa_price_per_kwh", 0.12)
        hours = _generate_default_price_curve(ppa_price)

    num_hours = len(hours)

    # 逐时段模拟
    soc = initial_soc  # 0.0 ~ 1.0
    total_charge_kwh = 0  # 从电网充电总量
    total_discharge_kwh = 0  # 放电到电网总量
    total_charge_cost = 0  # 充电总成本（负电价=负成本=收益）
    total_discharge_revenue = 0  # 放电总收入
    total_cycles = 0
    trading_log = []

    for t in range(num_hours):
        price = hours[t]
        action = "idle"
        energy_kwh = 0
        cost = 0
        revenue = 0

        # 决策：充电还是放电？
        if price <= charge_threshold:
            # 低电价或负电价 → 充电
            available_capacity = (max_soc - soc) * energy_capacity_kwh
            max_charge_energy = charge_power_kw * 1  # 1小时时段
            charge_energy = min(available_capacity, max_charge_energy)

            if charge_energy > 0:
                soc += charge_energy / energy_capacity_kwh
                total_charge_kwh += charge_energy
                # 充电成本 = 电价 × 充电量（负电价 = 负成本 = 赚钱）
                charge_cost = price * charge_energy
                total_charge_cost += charge_cost
                action = "charge"
                energy_kwh = charge_energy
                cost = charge_cost
                trading_log.append({
                    "hour": t,
                    "price": price,
                    "action": "charge",
                    "energy_kwh": charge_energy,
                    "soc": round(soc, 4),
                    "cost": round(charge_cost, 2),
                    "revenue": 0,
                })

        elif price >= discharge_threshold:
            # 高电价 → 放电
            available_energy = (soc - min_soc) * energy_capacity_kwh
            max_discharge_energy = discharge_power_kw * 1  # 1小时时段
            discharge_energy = min(available_energy, max_discharge_energy)

            if discharge_energy > 0:
                # 考虑效率：实际放电量 = 电池放电量 × 效率
                grid_energy = discharge_energy * rte
                soc -= discharge_energy / energy_capacity_kwh
                total_discharge_kwh += grid_energy
                discharge_revenue = price * grid_energy
                total_discharge_revenue += discharge_revenue
                total_cycles += discharge_energy / energy_capacity_kwh / 2
                action = "discharge"
                energy_kwh = grid_energy
                revenue = discharge_revenue
                trading_log.append({
                    "hour": t,
                    "price": price,
                    "action": "discharge",
                    "energy_kwh": grid_energy,
                    "soc": round(soc, 4),
                    "cost": 0,
                    "revenue": round(discharge_revenue, 2),
                })

        else:
            # 中等电价 → 待机
            trading_log.append({
                "hour": t,
                "price": price,
                "action": "idle",
                "energy_kwh": 0,
                "soc": round(soc, 4),
                "cost": 0,
                "revenue": 0,
            })

    # 年化：将典型日结果按 365 天扩展
    days_per_year = 365
    annual_net_revenue = (total_discharge_revenue + total_charge_cost) * days_per_year
    annual_net_energy = total_discharge_kwh * days_per_year
    annual_cycles = total_cycles * days_per_year
    annual_grid_charge = total_charge_kwh * days_per_year

    # 加权平均电价 = 净收入 / 净上网电量
    if annual_net_energy > 0:
        weighted_avg_price = annual_net_revenue / annual_net_energy
    else:
        weighted_avg_price = 0

    # 等效年利用小时数 = 年净上网电量 / 装机容量
    effective_hours = annual_net_energy / capacity_kw if capacity_kw > 0 else 0

    return {
        "weighted_avg_price": weighted_avg_price,
        "effective_hours": effective_hours,
        "annual_energy_kwh": annual_net_energy,
        "bess_cycles": annual_cycles,
        "curtailment_kwh": 0,
        "grid_charge_kwh": annual_grid_charge,
        "trading_log": trading_log,
        "degradation_rate": degradation_rate,
        "_bess_details": {
            "total_charge_kwh": total_charge_kwh * days_per_year,
            "total_discharge_kwh": total_discharge_kwh * days_per_year,
            "total_charge_cost": total_charge_cost * days_per_year,
            "total_discharge_revenue": total_discharge_revenue * days_per_year,
            "net_revenue": annual_net_revenue,
            "num_charge_events": sum(1 for l in trading_log if l["action"] == "charge"),
            "num_discharge_events": sum(1 for l in trading_log if l["action"] == "discharge"),
        },
    }


def _generate_default_price_curve(ppa_price):
    """
    如果没有提供电价曲线，生成一个默认的典型日曲线。
    包含峰谷平三段。
    """
    base = ppa_price
    # 24小时典型曲线（澳大利亚 NEM 风格）
    curve = [
        base * 0.3,   # 0:00 谷
        base * 0.25,  # 1:00
        base * 0.2,   # 2:00
        base * 0.15,  # 3:00 最低
        base * 0.2,   # 4:00
        base * 0.3,   # 5:00
        base * 0.5,   # 6:00
        base * 0.7,   # 7:00
        base * 0.9,   # 8:00
        base * 1.0,   # 9:00
        base * 1.1,   # 10:00
        base * 1.2,   # 11:00
        base * 1.3,   # 12:00 峰
        base * 1.2,   # 13:00
        base * 1.1,   # 14:00
        base * 1.0,   # 15:00
        base * 0.9,   # 16:00
        base * 0.8,   # 17:00
        base * 1.4,   # 18:00 晚峰
        base * 1.5,   # 19:00 最高
        base * 1.3,   # 20:00
        base * 1.0,   # 21:00
        base * 0.7,   # 22:00
        base * 0.5,   # 23:00
    ]
    return curve
