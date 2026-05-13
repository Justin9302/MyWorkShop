"""
scripts/trading/ — 交易策略模块

交易策略层负责将 project_config.yaml 中的项目参数和电价曲线，
转化为 financial_model_engine.py 可消费的年度输入参数。

每个技术类型对应一个策略文件，策略文件输出：
  - weighted_avg_price: 加权平均电价（$/kWh）
  - effective_hours: 等效年利用小时数（h）
  - annual_energy_kwh: 年净上网电量（kWh）
  - bess_cycles: BESS 年循环次数（如有）
  - curtailment_kwh: 年弃电量（kWh）
  - grid_charge_kwh: 年电网购电量（kWh）
  - trading_log: 逐时段交易记录（可选）

策略文件命名规则：
  {technology_type}_strategy.py

当前支持的策略：
  - solar_strategy.py: 光伏满发上网
  - bess_strategy.py: BESS 低充高放套利
  - hybrid_strategy.py: 光储混合（负电价弃光+电网充电）
  - wind_strategy.py: 风电满发上网
"""

import importlib
import os


def get_strategy(technology_type):
    """
    根据技术类型加载对应的交易策略模块。

    参数：
        technology_type (str): 技术类型（solar / bess / hybrid / wind / ...）

    返回：
        module: 交易策略模块，包含 run_strategy(config) 函数

    异常：
        ValueError: 不支持的技术类型
    """
    strategy_map = {
        "solar": "solar_strategy",
        "bess": "bess_strategy",
        "battery": "bess_strategy",
        "hybrid": "hybrid_strategy",
        "wind": "wind_strategy",
        "wind_bess": "wind_bess_strategy",
        "hydro": "solar_strategy",  # 水电暂用光伏策略（满发上网）
    }

    module_name = strategy_map.get(technology_type)
    if module_name is None:
        raise ValueError(f"不支持的技术类型: {technology_type}")

    try:
        module = importlib.import_module(f"scripts.trading.{module_name}")
        return module
    except ImportError as e:
        raise ImportError(f"无法加载交易策略模块 {module_name}: {e}")


def run_strategy(config):
    """
    运行交易策略，返回引擎可消费的年度参数。

    参数：
        config (dict): 完整的 project_config.yaml 内容

    返回：
        dict: {
            "weighted_avg_price": float,  # 加权平均电价（$/kWh）
            "effective_hours": float,     # 等效年利用小时数（h）
            "annual_energy_kwh": float,   # 年净上网电量（kWh）
            "bess_cycles": float,         # BESS 年循环次数
            "curtailment_kwh": float,     # 年弃电量（kWh）
            "grid_charge_kwh": float,     # 年电网购电量（kWh）
            "trading_log": list,          # 逐时段交易记录
        }
    """
    tech_type = config.get("project", {}).get("technology_type", "solar")
    module = get_strategy(tech_type)
    return module.run_strategy(config)
