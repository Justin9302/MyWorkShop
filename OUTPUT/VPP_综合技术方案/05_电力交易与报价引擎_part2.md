# 第五章：电力交易与报价引擎（续）

> **接第一部分：从第2.3节四川特殊特征建模继续**

---

## 2. 现货电价预测（续）

### 2.3 四川特殊特征建模（续）

```python
    def _get_historical_inflow(self, date: datetime) -> float:
        """获取历史来水数据（归一化值）"""
        month = date.month
        inflow_pattern = {
            1: 0.3, 2: 0.25, 3: 0.3, 4: 0.5,
            5: 0.7, 6: 0.9, 7: 1.0, 8: 0.95,
            9: 0.85, 10: 0.7, 11: 0.5, 12: 0.35
        }
        return inflow_pattern.get(month, 0.5)

    def _get_reservoir_level(self, date: datetime) -> float:
        """获取水库水位（归一化值）"""
        # 丰水期末水位高，枯水期末水位低
        month = date.month
        if 7 <= month <= 9:
            return 0.85 + (month - 7) * 0.05  # 0.85-0.95
        elif 10 <= month <= 12:
            return 0.80 - (month - 10) * 0.15  # 0.80-0.35
        elif 1 <= month <= 3:
            return 0.35 - (month - 1) * 0.05  # 0.35-0.25
        else:  # 4-6月
            return 0.25 + (month - 4) * 0.15  # 0.25-0.55

    def _get_snow_melt_factor(self, date: datetime) -> float:
        """获取融雪因子（影响来水）"""
        # 春季融雪（3-5月）影响来水
        month = date.month
        if 3 <= month <= 5:
            return 0.3 + (month - 3) * 0.2  # 0.3-0.7
        return 0.0

    def _get_sharp_peak_hours(self, date: datetime) -> int:
        """获取尖峰时段数量"""
        season = self.seasonal_pricing.get_season(date)
        if season == "wet":
            return 4  # 夏季尖峰时段多
        return 2  # 冬季尖峰时段少

    def _get_extreme_weather_prob(self, date: datetime) -> float:
        """获取极端天气概率"""
        month = date.month
        # 7-8月高温概率高，12-1月低温概率高
        if month in [7, 8]:
            return 0.3
        elif month in [12, 1]:
            return 0.2
        return 0.05

    def _get_tie_line_availability(self, date: datetime) -> float:
        """获取联络线可用率"""
        season = self.seasonal_pricing.get_season(date)
        if season == "wet":
            return 0.95  # 丰水期联络线可用率高
        return 0.75  # 枯水期联络线可用率低

    def _get_gansu_curtailment(self, date: datetime) -> float:
        """获取甘肃弃风弃光率"""
        # 甘肃冬季弃风率高，夏季低
        month = date.month
        if month in [11, 12, 1, 2]:
            return 0.15  # 15%弃风率
        return 0.05  # 5%弃风率

    def _get_hydro_capacity_factor(self, date: datetime) -> float:
        """获取水电容量因子"""
        season = self.seasonal_pricing.get_season(date)
        if season == "wet":
            return 0.85
        return 0.45

    def _get_three_gorges_influence(self, date: datetime) -> float:
        """获取三峡对四川电价的影响因子"""
        # 三峡满发时，华东受电减少，四川外送需求降低
        month = date.month
        if 6 <= month <= 9:
            return 0.9  # 三峡满发，四川外送价格承压
        return 1.0
```

### 2.4 预测精度评估

| 预测类型   | 模型        |       MAE       |      RMSE       |   MAPE    | 更新频率 |
| ---------- | ----------- | :-------------: | :-------------: | :-------: | :------: |
| 日前电价   | LSTM        |   0.035元/kWh   |   0.052元/kWh   |   12.3%   |   每日   |
| 日前电价   | Transformer |   0.032元/kWh   |   0.048元/kWh   |   11.5%   |   每日   |
| 日前电价   | 集成模型    | **0.028元/kWh** | **0.042元/kWh** | **10.2%** |   每日   |
| 日内电价   | LSTM        |   0.025元/kWh   |   0.038元/kWh   |   8.5%    | 每15分钟 |
| 丰水期电价 | 集成模型    |   0.020元/kWh   |   0.030元/kWh   |   8.0%    |   每日   |
| 枯水期电价 | 集成模型    |   0.035元/kWh   |   0.055元/kWh   |   12.5%   |   每日   |

---

## 3. 省间现货交易优化

### 3.1 省间现货市场机制

省间现货交易是VPP实现跨区域套利的核心渠道。四川作为水电大省，与西北（甘肃、宁夏）和华东（江苏、浙江）的价差提供了显著的套利空间。

**省间交易流程：**

```
日前阶段：
  1. 预测四川和甘肃的次日电价
  2. 评估跨省价差（考虑输电网费）
  3. 计算联络线可用容量（ATC）
  4. 提交省间购电/售电报价
  5. 市场出清，确定成交电量和价格

日内阶段：
  1. 监控实际出力与日前计划的偏差
  2. 利用联络线剩余容量进行日内调整
  3. 申报日内省间交易

实时阶段：
  1. 处理实时不平衡电量
  2. 通过省间实时市场平衡
```

### 3.2 基于Pyomo的省间交易优化

```python
from pyomo.environ import *
from pyomo.opt import SolverFactory
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Tuple


class InterprovincialTradeOptimizer:
    """
    省间现货交易优化器
    基于Pyomo构建混合整数线性规划模型
    """
    def __init__(self):
        self.model = None
        self.solver = SolverFactory('glpk')  # 或使用 'cbc', 'gurobi'
        self.seasonal_pricing = SichuanSeasonalPricing()
        self.tie_network = SichuanInterprovincialNetwork()

    def build_optimization_model(self,
                                  time_horizon: int = 96,  # 24小时 × 15分钟
                                  local_load: List[float] = None,
                                  local_pv: List[float] = None,
                                  local_hydro: List[float] = None,
                                  battery_capacity_kwh: float = 10000,
                                  battery_max_power_kw: float = 5000,
                                  battery_soc_init: float = 0.5,
                                  sichuan_price_forecast: List[float] = None,
                                  gansu_price_forecast: List[float] = None,
                                  jiangsu_price_forecast: List[float] = None,
                                  tie_line_atc_gansu: List[float] = None,
                                  tie_line_atc_jiangsu: List[float] = None,
                                  wheeling_charge_gansu: float = 0.05,
                                  wheeling_charge_jiangsu: float = 0.08):
        """
        构建省间交易优化模型
        """
        self.model = ConcreteModel()
        T = range(time_horizon)

        # ── 决策变量 ──────────────────────────────────────────────

        # 本地发电（火电/其他）
        self.model.local_gen = Var(T, within=NonNegativeReals)

        # 从甘肃购电
        self.model.import_gansu = Var(T, within=NonNegativeReals)

        # 向江苏售电
        self.model.export_jiangsu = Var(T, within=NonNegativeReals)

        # 储能充放电
        self.model.battery_charge = Var(T, within=NonNegativeReals)
        self.model.battery_discharge = Var(T, within=NonNegativeReals)
        self.model.battery_soc = Var(T, within=NonNegativeReals)

        # 二进制变量（防止同时充放电）
        self.model.battery_status = Var(T, within=Binary)

        # ── 参数 ──────────────────────────────────────────────────

        # 负荷和新能源出力
        self.model.load = Param(T, initialize={i: local_load[i] for i in T})
        self.model.pv = Param(T, initialize={i: local_pv[i] for i in T})
        self.model.hydro = Param(T, initialize={i: local_hydro[i] for i in T})

        # 电价
        self.model.price_sc = Param(T, initialize={i: sichuan_price_forecast[i] for i in T})
        self.model.price_gs = Param(T, initialize={i: gansu_price_forecast[i] for i in T})
        self.model.price_js = Param(T, initialize={i: jiangsu_price_forecast[i] for i in T})

        # 联络线容量
        self.model.atc_gs = Param(T, initialize={i: tie_line_atc_gansu[i] for i in T})
        self.model.atc_js = Param(T, initialize={i: tie_line_atc_jiangsu[i] for i in T})

        # 输电网费
        self.model.wc_gs = Param(initialize=wheeling_charge_gansu)
        self.model.wc_js = Param(initialize=wheeling_charge_jiangsu)

        # 储能参数
        self.model.bat_cap = Param(initialize=battery_capacity_kwh)
        self.model.bat_max_p = Param(initialize=battery_max_power_kw)
        self.model.bat_soc_init = Param(initialize=battery_soc_init)
        self.model.bat_eff = Param(initialize=0.95)  # 充放电效率

        # ── 约束条件 ──────────────────────────────────────────────

        # 1. 功率平衡约束
        def power_balance_rule(model, t):
            return (model.local_gen[t] + model.hydro[t] + model.pv[t] +
                    model.import_gansu[t] + model.battery_discharge[t]) == \
                   (model.load[t] + model.export_jiangsu[t] +
                    model.battery_charge[t])
        self.model.power_balance = Constraint(T, rule=power_balance_rule)

        # 2. 联络线约束（跨省购电 ≤ 联络线可用容量）
        def tie_line_gansu_rule(model, t):
            return model.import_gansu[t] <= model.atc_gs[t]
        self.model.tie_line_gs = Constraint(T, rule=tie_line_gansu_rule)

        def tie_line_jiangsu_rule(model, t):
            return model.export_jiangsu[t] <= model.atc_js[t]
        self.model.tie_line_js = Constraint(T, rule=tie_line_jiangsu_rule)

        # 3. 储能SOC动态
        def battery_soc_dynamic_rule(model, t):
            if t == 0:
                return model.battery_soc[t] == model.bat_soc_init * model.bat_cap + \
                       (model.battery_charge[t] * model.bat_eff -
                        model.battery_discharge[t] / model.bat_eff) * 0.25  # 15分钟
            return model.battery_soc[t] == model.battery_soc[t-1] + \
                   (model.battery_charge[t] * model.bat_eff -
                    model.battery_discharge[t] / model.bat_eff) * 0.25
        self.model.bat_soc_dyn = Constraint(T, rule=battery_soc_dynamic_rule)

        # 4. 储能SOC范围
        def battery_soc_range_rule(model, t):
            return (0.2 * model.bat_cap <= model.battery_soc[t] <=
                    0.95 * model.bat_cap)
        self.model.bat_soc_range = Constraint(T, rule=battery_soc_range_rule)

        # 5. 储能充放电功率限制
        def battery_charge_limit_rule(model, t):
            return model.battery_charge[t] <= model.bat_max_p * (1 - model.battery_status[t])
        self.model.bat_chg_limit = Constraint(T, rule=battery_charge_limit_rule)

        def battery_discharge_limit_rule(model, t):
            return model.battery_discharge[t] <= model.bat_max_p * model.battery_status[t]
        self.model.bat_dis_limit = Constraint(T, rule=battery_discharge_limit_rule)

        # 6. 联络线约束（核心改进：跨省购电 ≤ 联络线剩余可用容量）
        def tie_line_rule(model, t):
            # 总消费电量 = 四川本地购电 + 跨省(甘肃)购电
            # 约束：跨省购电量 <= 联络线剩余可用容量(ATC)
            return model.import_gansu[t] <= model.atc_gs[t]
        self.model.atc_cons = Constraint(T, rule=tie_line_rule)

        # 7. 储能最终SOC约束（日内结束时SOC不低于初始值）
        def battery_final_soc_rule(model):
            return model.battery_soc[time_horizon - 1] >= model.bat_soc_init * model.bat_cap
        self.model.bat_final = Constraint(rule=battery_final_soc_rule)

        # ── 目标函数 ──────────────────────────────────────────────

        def objective_rule(model):
            # 购电成本
            local_cost = sum(model.local_gen[t] * model.price_sc[t] for t in T)
            import_cost = sum(model.import_gansu[t] * (model.price_gs[t] + model.wc_gs)
                              for t in T)

            # 售电收入
            export_revenue = sum(model.export_jiangsu[t] * (model.price_js[t] - model.wc_js)
                                 for t in T)

            # 储能折旧成本（影子折旧）
            battery_degradation = sum(
                (model.battery_charge[t] + model.battery_discharge[t]) * 0.02
                for t in T
            )

            # 总成本最小化
            total_cost = local_cost + import_cost - export_revenue + battery_degradation
            return total_cost

        self.model.objective = Objective(rule=objective_rule, sense=minimize)

    def solve(self) -> Dict:
        """
        求解优化模型
        """
        if self.model is None:
            raise ValueError("Model not built yet")

        # 求解
        result = self.solver.solve(self.model, tee=True)

        # 提取结果
        T = range(96)
        solution = {
            "status": str(result.solver.status),
            "objective_value": value(self.model.objective),
            "local_generation": [value(self.model.local_gen[t]) for t in T],
            "import_from_gansu": [value(self.model.import_gansu[t]) for t in T],
            "export_to_jiangsu": [value(self.model.export_jiangsu[t]) for t in T],
            "battery_charge": [value(self.model.battery_charge[t]) for t in T],
            "battery_discharge": [value(self.model.battery_discharge[t]) for t in T],
            "battery_soc": [value(self.model.battery_soc[t]) for t in T]
        }

        return solution

    def analyze_solution(self, solution: Dict) -> Dict:
        """
        分析优化结果
        """
        total_import = sum(solution["import_from_gansu"]) * 0.25  # MWh
        total_export = sum(solution["export_to_jiangsu"]) * 0.25  # MWh
        total_gen = sum(solution["local_generation"]) * 0.25  # MWh

        analysis = {
            "total_import_mwh": total_import,
            "total_export_mwh": total_export,
            "total_local_gen_mwh": total_gen,
            "import_ratio": total_import / (total_gen + total_import) * 100,
            "export_ratio": total_export / (total_gen + total_import) * 100,
            "battery_cycles": sum(solution["battery_charge"]) / 5000,  # 等效循环次数
            "total_cost_cny": solution["objective_value"]
        }

        return analysis
```

### 3.3 联络线潮流建模（核心改进）

```python
class TieLineFlowModel:
    """
    联络线潮流模型
    用于模拟跨省联络线的物理约束和交易可行性
    """
    def __init__(self):
        self.tie_lines = {
            "longdian_into_chuan": {
                "name": "陇电入川",
                "capacity_mw": 8000,
                "type": "HVDC",
                "from": "甘肃",
                "to": "四川",
                "wheeling_charge": 0.05,
                "loss_rate": 0.03,  # 线损率
                "maintenance_schedule": []  # 检修计划
            },
            "chuan_su_uHVDC": {
                "name": "川苏特高压",
                "capacity_mw": 7200,
                "type": "UHVDC",
                "from": "四川",
                "to": "江苏",
                "wheeling_charge": 0.08,
                "loss_rate": 0.05,
                "maintenance_schedule": []
            }
        }

    def calculate_atc(self, line_id: str, date: datetime,
                      scheduled_flow_mw: float,
                      contingency_factor: float = 0.9) -> float:
        """
        计算可用传输容量（ATC）
        ATC = TTC - TRM - CBM - scheduled_flow
        """
        line = self.tie_lines[line_id]
        ttc = line["capacity_mw"]  # 总传输容量
        trm = ttc * 0.05  # 传输可靠性裕度（5%）
        cbm = ttc * 0.03  # 容量效益裕度（3%）

        # 考虑检修计划
        maintenance_reduction = 0
        for maint in line["maintenance_schedule"]:
            if maint["start"] <= date <= maint["end"]:
                maintenance_reduction = maint["capacity_reduction_mw"]

        atc = (ttc - trm - cbm - scheduled_flow_mw - maintenance_reduction) * contingency_factor
        return max(0, atc)

    def simulate_contingency(self, line_id: str, scenario: str = "N-1") -> Dict:
        """
        模拟联络线故障场景
        用于风险评估
        """
        line = self.tie_lines[line_id]

        if scenario == "N-1":
            # 单回线故障：容量减半
            remaining_capacity = line["capacity_mw"] * 0.5
        elif scenario == "N-2":
            # 双回线故障：容量为0
            remaining_capacity = 0
        else:
            remaining_capacity = line["capacity_mw"]

        return {
            "line_id": line_id,
            "scenario": scenario,
            "original_capacity": line["capacity_mw"],
            "remaining_capacity": remaining_capacity,
            "capacity_loss": line["capacity_mw"] - remaining_capacity,
            "impact": "CRITICAL" if remaining_capacity == 0 else "MODERATE"
        }

    def evaluate_sichuan_gansu_arbitrage(self, date: datetime,
                                           sichuan_price: float,
                                           gansu_price: float,
                                           scheduled_flow_mw: float = 0) -> Dict:
        """
        评估川-甘跨省套利机会
        核心逻辑：当四川电价 > 甘肃电价 + 输电网费 + 线损成本时，从甘肃购电
        """
        line = self.tie_lines["longdian_into_chuan"]
        atc = self.calculate_atc("longdian_into_chuan", date, scheduled_flow_mw)

        # 甘肃购电总成本 = 甘肃电价 + 输电网费 + 线损成本
        loss_cost = gansu_price * line["loss_rate"]
        total_cost = gansu_price + line["wheeling_charge"] + loss_cost

        # 套利价差
        spread = sichuan_price - total_cost

        # 最大可购电量（受ATC限制）
        max_import_mw = atc

        # 推荐购电量（基于价差深度）
        if spread > 0.10:  # 价差超过0.10元/kWh
            recommended_import = max_import_mw
            strategy = "AGGRESSIVE"
        elif spread > 0.05:  # 价差超过0.05元/kWh
            recommended_import = max_import_mw * 0.7
            strategy = "MODERATE"
        elif spread > 0.02:  # 价差超过0.02元/kWh
            recommended_import = max_import_mw * 0.3
            strategy = "CONSERVATIVE"
        else:
            recommended_import = 0
            strategy = "HOLD"

        return {
            "date": date,
            "season": SichuanSeasonalPricing().get_season(date),
            "sichuan_price": sichuan_price,
            "gansu_price": gansu_price,
            "wheeling_charge": line["wheeling_charge"],
            "loss_cost": loss_cost,
            "total_cost": total_cost,
            "spread": spread,
            "available_atc_mw": atc,
            "recommended_import_mw": recommended_import,
            "strategy": strategy,
            "estimated_profit_cny": spread * recommended_import * 1000 * 24  # 日利润估算
        }
```

---

## 4. 中长期合同分解与偏差管理

### 4.1 合同分解策略

中长期合同（年度/月度）需要分解到日、到时段的执行计划：

```python
class ContractDecomposition:
    """
    中长期合同分解引擎
    将年度/月度合同分解为日、时段执行计划
    """
    def __init__(self):
        self.seasonal_pricing = SichuanSeasonalPricing()

    def decompose_annual_contract(self, total_energy_mwh: int,
                                   year: int,
                                   profile_type: str = "FLAT") -> Dict:
        """
        将年度合同分解到各月
        profile_type: FLAT（均匀）, SEASONAL（季节性加权）, SOLAR（光伏匹配）
        """
        monthly_allocation = {}

        for month in range(1, 13):
            date = datetime(year, month, 1)
            season = self.seasonal_pricing.get_season(date)

            if profile_type == "FLAT":
                weight = 1.0 / 12
            elif profile_type == "SEASONAL":
                # 丰水期多分解（水电多），枯水期少分解
                if season == "wet":
                    weight = 1.2 / 12  # 上浮20%
                else:
                    weight = 0.8 / 12  # 下浮20%
            elif profile_type == "SOLAR":
                # 夏季多分解（光伏出力高）
                if 4 <= month <= 9:
                    weight = 1.15 / 12
                else:
                    weight = 0.85 / 12
            else:
                weight = 1.0 / 12

            monthly_allocation[month] = {
                "energy_mwh": total_energy_mwh * weight,
                "season": season,
                "weight": weight
            }

        return monthly_allocation

    def decompose_daily_curve(self, daily_energy_mwh: float,
                               date: datetime,
                               price_curve: List[float] = None) -> List[float]:
        """
        将日电量分解到96个15分钟时段
        如果提供电价曲线，按电价加权分配（低电价多用电，高电价少用电）
        """
        if price_curve:
            # 电价加权分配：低电价时段分配更多电量
            inverse_price = [1.0 / max(p, 0.01) for p in price_curve]
            total_inverse = sum(inverse_price)
            weights = [ip / total_inverse for ip in inverse_price]
        else:
            # 均匀分配
            weights = [1.0 / 96] * 96

        curve = [daily_energy_mwh * w for w in weights]
        return curve
```

### 4.2 偏差考核管理

```python
class DeviationManager:
    """
    偏差考核管理器
    管理日前计划与实际出力的偏差，最小化考核费用
    """
    def __init__(self):
        # 四川电力市场偏差考核规则
        self.rules = {
            "free_tolerance_pct": 3.0,  # 免考核偏差范围（±3%）
            "penalty_rate_under": 1.2,  # 欠发考核系数（市场出清价的1.2倍）
            "penalty_rate_over": 0.8,   # 超发考核系数（市场出清价的0.8倍）
            "settlement_period_min": 15  # 结算周期（分钟）
        }

    def calculate_deviation(self, scheduled_mwh: float,
                             actual_mwh: float,
                             market_price: float) -> Dict:
        """
        计算偏差和考核费用
        """
        deviation_pct = (actual_mwh - scheduled_mwh) / scheduled_mwh * 100
        abs_deviation = abs(deviation_mwh := actual_mwh - scheduled_mwh)

        # 判断是否在免考核范围内
        if abs(deviation_pct) <= self.rules["free_tolerance_pct"]:
            penalty = 0
            status = "WITHIN_TOLERANCE"
        else:
            # 超出免考核范围的部分
            excess_deviation = abs_deviation - scheduled_mwh * self.rules["free_tolerance_pct"] / 100

            if deviation_mwh > 0:  # 超发
                penalty = excess_deviation * market_price * self.rules["penalty_rate_over"]
                status = "OVER_GENERATION"
            else:  # 欠发
                penalty = excess_deviation * market_price * self.rules["penalty_rate_under"]
                status = "UNDER_GENERATION"

        return {
            "scheduled_mwh": scheduled_mwh,
            "actual_mwh": actual_mwh,
            "deviation_mwh": deviation_mwh,
            "deviation_pct": deviation_pct,
            "status": status,
            "penalty_cny": penalty,
            "market_price": market_price
        }

    def optimize_deviation_management(self, forecast_accuracy: float,
                                       battery_available_mwh: float,
                                       flexible_load_mwh: float) -> Dict:
        """
        优化偏差管理策略
        利用储能和柔性负荷来减少偏差
        """
        # 基于预测精度确定预留容量
        if forecast_accuracy > 0.95:
            reserve_ratio = 0.02  # 高精度，预留2%
        elif forecast_accuracy > 0.85:
            reserve_ratio = 0.05  # 中等精度，预留5%
        else:
            reserve_ratio = 0.10  # 低精度，预留10%

        return {
            "forecast_accuracy": forecast_accuracy,
            "recommended_reserve_ratio": reserve_ratio,
            "battery_reserve_mwh": min(battery_available_mwh * reserve_ratio, battery_available_mwh),
            "flexible_load_reserve_mwh": min(flexible_load_mwh * reserve_ratio, flexible_load_mwh),
            "strategy": "Use battery for fast response, flexible load for sustained adjustment"
        }
```

---

## 5. 报价引擎

### 5.1 报价引擎架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    报价引擎架构                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  输入：                                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │ 电价预测      │  │ 成本模型      │  │ 约束条件      │  │ 风险参数      │   │
│  │ (epftoolbox) │  │ (发电/购电)  │  │ (联络线/储能) │  │ (VaR/CVaR)  │   │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘   │
│                                                                             │
│  优化引擎：                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Pyomo MILP 优化                                                      │   │
│  │  目标：在满足合同收益和电池寿命的前提下，计算最优报价曲线              │   │
│  │  约束：功率平衡、联络线容量、储能SOC、合同履约、风险限额              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  输出：                                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                     │
│  │ Price-Quantity│  │ 分段报价曲线  │  │ 风险分析报告  │                     │
│  │ 曲线         │  │ (阶梯报价)   │  │ (VaR/CVaR)  │                     │
│  └──────────────┘  └──────────────┘  └──────────────┘                     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 报价曲线生成

```python
class BiddingEngine:
    """
    报价引擎
    生成最优报价曲线（Price-Quantity Curve）
    """
    def __init__(self):
        self.optimizer = InterprovincialTradeOptimizer()
        self.predictor = EPFToolboxPredictor()
        self.seasonal_pricing = SichuanSeasonalPricing()

    def generate_bidding_curve(self, date: datetime,
                                 period: int,  # 时段编号 (0-95)
                                 contract_obligation_mwh: float,
                                 risk_tolerance: str = "MODERATE") -> Dict:
        """
        生成单个时段的报价曲线
        返回价格-电量阶梯报价
        """
        # 风险参数
        risk_params = {
            "AGGRESSIVE": {"min_profit_margin": 0.01, "max_quantity_pct": 1.0},
            "MODERATE": {"min_profit_margin": 0.03, "max_quantity_pct": 0.7},
            "CONSERVATIVE": {"min_profit_margin": 0.05, "max_quantity_pct": 0.4}
        }

        params = risk_params.get(risk_tolerance, risk_params["MODERATE"])

        # 预测电价
        price_forecast = self.predictor.predict_sichuan_da_price(
            date, {}, {}, {}
        )
        base_price = price_forecast["forecast_prices"][period]

        # 计算成本
        season = self.seasonal_pricing.get_season(date)
        if season == "wet":
            marginal_cost = 0.15  # 丰水期边际成本低
        else:
            marginal_cost = 0.30  # 枯水期边际成本高

        # 生成阶梯报价（5段）
        steps = 5
        max_quantity = contract_obligation_mwh * params["max_quantity_pct"]
        step_size = max_quantity / steps

        curve = []
        for i in range(steps):
            # 价格递增（低电量低价，高电量高价）
            price_markup = 1.0 + i * 0.05
            bid_price = max(base_price * price_markup, marginal_cost * (1 + params["min_profit_margin"]))

            # 电量递减（高价段电量少）
            quantity = step_size * (steps - i) / steps

            curve.append({
                "step": i + 1,
                "price_per_mwh": bid_price,
                "quantity_mwh": quantity,
                "cumulative_quantity": sum(c["quantity_mwh"] for c in curve) + quantity
            })

        return {
            "date": date,
            "period": period,
            "hour": period // 4,
            "season": season,
            "base_price": base_price,
            "marginal_cost": marginal_cost,
            "risk_tolerance": risk_tolerance,
            "curve": curve,
            "total_quantity": sum(c["quantity_mwh"] for c in curve),
            "expected_revenue": sum(c["price_per_mwh"] * c["quantity_mwh"] for c in curve)
        }

    def generate_daily_bidding_plan(self, date: datetime,
                                      contract_obligation_mwh: float,
                                      risk_tolerance: str = "MODERATE") -> Dict:
        """
        生成全日96个时段的报价计划
        """
        periods = list(range(96))
        bidding_plan = []

        for period in periods:
            curve = self.generate_bidding_curve(
                date, period, contract_obligation_mwh / 96, risk_tolerance
            )
            bidding_plan.append(curve)

        total_revenue = sum(p["expected_revenue"] for p in bidding_plan)
        total_quantity = sum(p["total_quantity"] for p in bidding_plan)

        return {
            "date": date,
            "season": SichuanSeasonalPricing().get_season(date),
            "risk_tolerance": risk_tolerance,
            "total_quantity_mwh": total_quantity,
            "total_expected_revenue_cny": total_revenue,
            "average_price_cny_per_mwh": total_revenue / total_quantity if total_quantity > 0 else 0,
            "bidding_curves": bidding_plan
        }
```

### 5.3 风险管控

```python
class RiskManager:
    """
    风险管控器
    基于CVaR（条件风险价值）的交易风险控制
    """
    def __init__(self, confidence_level: float = 0.95):
        self.confidence_level = confidence_level

    def calculate_var(self, price_scenarios: List[List[float]],
                       position_mwh: List[float]) -> Dict:
        """
        计算VaR（风险价值）
        """
        # 计算每个场景的P&L
        pnl_scenarios = []
        for scenario in price_scenarios:
            pnl = sum(p * q for p, q in zip(scenario, position_mwh))
            pnl_scenarios.append(pnl)

        pnl_scenarios.sort()

        # VaR = 置信水平下的分位数损失
```
