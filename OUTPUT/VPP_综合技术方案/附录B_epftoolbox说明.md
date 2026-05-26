# 附录B：epftoolbox 电价预测工具包说明

> **本文档是对《第一章：总体架构与设计理念》中"epftoolbox"的详细说明**
> **关联文档：** `01_总体架构与设计理念.md`（§2.3 GB/T 38755-2020 合规映射、§3.1 核心架构图、§6.2 Phase 1 核心交付物、§7.1 核心组件选型、§7.3 开源组件成熟度评估、§11.1 核心团队技能要求）
> **关联文档：** `05_电力交易与报价引擎.md`（§2.2 基于epftoolbox的电价预测）
> **关联文档：** `附录_技术选型与关键代码.md`（§1.1 技术栈选型清单、§2.3 电价预测代码示例）

---

## 1. 概述

**epftoolbox** 是一个专注于电力市场电价预测（Electricity Price Forecasting）的开源 Python 工具包，由 Jesús Lago 等人开发维护。它提供了从数据预处理、特征工程到模型训练、预测评估的完整工作流，支持多种深度学习模型和传统统计方法，是电力市场交易和 VPP 报价优化的核心预测组件。

| 项目                 | 内容                                                             |
| -------------------- | ---------------------------------------------------------------- |
| **项目名称**         | epftoolbox                                                       |
| **许可证**           | Apache 2.0                                                       |
| **GitHub**           | https://github.com/jeslago/epftoolbox                            |
| **成熟度**           | 学术级（GitHub Stars 300+）                                      |
| **语言**             | Python 3.7+                                                      |
| **核心用途**         | 电力现货市场日前/日内电价预测                                    |
| **在本方案中的角色** | 交易层 - 报价引擎的核心预测组件，为 Pyomo 优化求解器提供电价输入 |

---

## 2. 为什么选择 epftoolbox？

### 2.1 选型对比

| 维度             | epftoolbox                        | Prophet (Meta)          | 自研 LSTM/Transformer |
| ---------------- | --------------------------------- | ----------------------- | --------------------- |
| **专注领域**     | ✅ 电力市场电价预测               | ❌ 通用时序预测         | ⚠️ 需自行实现电力特征 |
| **内置模型**     | CNN、LSTM、CNN+LSTM、RNN、Naive   | 趋势+季节+节假日分解    | 需自行构建            |
| **数据接口**     | ✅ 内置 EPEX/ENTSO-E/PJM 数据读取 | ❌ 需自行准备           | ❌ 需自行准备         |
| **预测模式**     | 日前预测、在线预测、滚动预测      | 通用预测                | 需自行实现            |
| **评估指标**     | ✅ 内置 MAE/sMAPE/MASE/RMSE       | ❌ 需自行计算           | ❌ 需自行实现         |
| **四川市场适配** | ⚠️ 需自定义数据接口               | ❌ 需完全定制           | ✅ 可完全定制         |
| **社区活跃度**   | ⭐⭐（学术维护）                  | ⭐⭐⭐⭐⭐（Meta 维护） | -                     |
| **学习成本**     | 低（专注电力市场，API 简洁）      | 低                      | 高                    |

### 2.2 在本方案中的定位

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  交易层 - 报价引擎                                                           │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  epftoolbox（电价预测层）                                              │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │  │
│  │  │ 日前电价预测  │  │ 日内电价预测  │  │ 省间价差预测  │              │  │
│  │  │ (D-1, 96点)  │  │ (滚动更新)   │  │ (川-甘/川-苏)│              │  │
│  │  └──────────────┘  └──────────────┘  └──────────────┘              │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                    │                                         │
│                                    ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  Pyomo（优化求解层）                                                  │  │
│  │  输入：epftoolbox 输出的电价预测曲线                                   │  │
│  │  输出：最优报价曲线（Price-Quantity Curve）                            │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                    │                                         │
│                                    ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  聚合层调度执行                                                        │  │
│  │  FlexMeasures / 自研聚合引擎接收报价曲线并分解为设备级调度指令          │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 核心功能

### 3.1 内置预测模型

epftoolbox 提供了多种预实现的电价预测模型，覆盖从简单基准到深度学习的完整谱系：

| 模型                | 类型         | 说明                                               | 在本方案中的用途     |
| ------------------- | ------------ | -------------------------------------------------- | -------------------- |
| **Naive**           | 基准模型     | 简单重复前一天电价作为预测，作为性能下界参考       | Phase 1 基线对比     |
| **ARIMA**           | 统计模型     | 自回归移动平均模型，适合平稳时序                   | Phase 1 快速原型     |
| **CNN**             | 深度学习     | 一维卷积神经网络，捕捉局部电价模式                 | Phase 2 主力模型     |
| **LSTM**            | 深度学习     | 长短期记忆网络，捕捉长程时序依赖                   | Phase 2 主力模型     |
| **CNN+LSTM**        | 混合模型     | CNN 提取局部特征 + LSTM 建模时序依赖，综合性能最优 | **Phase 3 推荐模型** |
| **RNN**             | 深度学习     | 循环神经网络，基础时序建模                         | 备选模型             |
| **Ensemble**        | 集成模型     | 多个模型的加权集成，提升预测稳定性和鲁棒性         | Phase 3 生产环境     |
| **Online Learning** | 在线学习模式 | 模型随新数据持续更新，适应市场变化                 | 生产环境持续运行     |

### 3.2 数据接口

epftoolbox 内置了多个电力市场的数据读取接口，方便快速获取历史电价数据：

| 数据源         | 市场区域               | 粒度         | 在本方案中的可用性              |
| -------------- | ---------------------- | ------------ | ------------------------------- |
| **EPEX**       | 欧洲电力市场           | 1小时/15分钟 | ❌ 不直接适用，但可参考数据格式 |
| **ENTSO-E**    | 欧洲输电系统           | 1小时        | ❌ 不直接适用                   |
| **PJM**        | 美国宾州-新泽西-马里兰 | 1小时        | ❌ 不直接适用                   |
| **自定义接口** | 四川电力市场           | 15分钟       | ✅ 需自行实现数据适配层         |

> **⚠️ 四川市场适配说明**：epftoolbox 内置的数据接口主要面向欧美电力市场。在四川 VPP 项目中，需要实现自定义数据适配层，将四川电力交易中心的历史电价数据转换为 epftoolbox 可用的 DataFrame 格式。详见 §5.1。

### 3.3 预测模式

| 模式         | 说明                                          | 在本方案中的应用场景                    |
| ------------ | --------------------------------------------- | --------------------------------------- |
| **日前预测** | 预测未来 24 小时电价（96 个 15 分钟时段）     | 日前市场报价（每日 15:00 前提交）       |
| **日内预测** | 滚动预测未来 4-6 小时电价，每 15 分钟更新一次 | 日内市场调整、储能实时调度              |
| **在线预测** | 模型随新数据持续更新，无需全量重训练          | 生产环境持续运行，适应市场变化          |
| **滚动预测** | 固定窗口滚动训练+预测，定期更新模型参数       | 丰枯水期切换时的模型自适应              |
| **多步预测** | 直接预测未来多个时段（而非递归单步预测）      | 省间交易优化（需 24-72 小时预测窗口）   |
| **概率预测** | 输出预测分布（分位数），而非单一点预测        | 风险管控（VaR/CVaR 计算）、报价策略优化 |

### 3.4 评估指标

epftoolbox 内置了电力市场预测的标准评估指标：

| 指标      | 全称                                     | 说明                   | 本方案目标值 |
| --------- | ---------------------------------------- | ---------------------- | :----------: |
| **MAE**   | Mean Absolute Error                      | 平均绝对误差（元/kWh） |    < 0.03    |
| **sMAPE** | Symmetric Mean Absolute Percentage Error | 对称平均绝对百分比误差 |    < 15%     |
| **MASE**  | Mean Absolute Scaled Error               | 平均绝对缩放误差       |    < 1.0     |
| **RMSE**  | Root Mean Square Error                   | 均方根误差（元/kWh）   |    < 0.05    |

---

## 4. 在本方案中的集成方式

### 4.1 架构集成

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  epftoolbox 集成架构                                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  数据层：                                                                    │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  四川电力交易中心历史电价数据（CSV/API）                               │  │
│  │  → 自定义数据适配层 → epftoolbox DataFrame 格式                       │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                    │                                         │
│  模型层：                                                                    │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  epftoolbox 模型训练与预测                                              │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │  │
│  │  │ CNN+LSTM     │  │ LightGBM     │  │ 模型集成      │              │  │
│  │  │ (epftoolbox) │  │ (自研扩展)   │  │ (加权融合)   │              │  │
│  │  └──────────────┘  └──────────────┘  └──────────────┘              │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                    │                                         │
│  输出层：                                                                    │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  电价预测结果 → Pyomo 报价优化引擎                                    │  │
│  │  - 日前电价曲线（96 点）                                              │  │
│  │  - 日内电价更新（滚动）                                              │  │
│  │  - 省间价差预测（川-甘/川-苏）                                      │  │
│  │  - 预测不确定性（分位数区间）                                        │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                    │                                         │
│  反馈层：                                                                    │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  实际电价反馈 → 模型在线更新                                          │  │
│  │  - 每日自动重训练（增量学习）                                        │  │
│  │  - 丰枯水期切换时全量重训练                                          │  │
│  │  - 预测误差监控告警（MAE > 0.05 触发人工审查）                       │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 与 Pyomo 的协作流程

```
epftoolbox 电价预测                          Pyomo 报价优化
─────────────────────                       ──────────────
     │                                              │
     │  输出：日前电价曲线 P(t)                       │
     │  [0.25, 0.28, 0.35, ..., 0.55]               │
     │──────────────────────────────────────────────→│
     │                                               │
     │                         输入：P(t) + 资产参数  │
     │                         约束：SOC/功率/联络线  │
     │                         目标：max 收益         │
     │                                               │
     │  ←────────────────────────────────────────────│
     │  输出：最优报价曲线 Q(P)                       │
     │  [(0.25, 500), (0.30, 400), ..., (0.55, -200)]│
     │                                               │
```

### 4.3 与四川环境建模的集成

epftoolbox 的预测能力与四川特殊环境建模（§8 四川环境建模）深度集成：

| 四川特性             | epftoolbox 集成方式                                            | 实现要点                                  |
| -------------------- | -------------------------------------------------------------- | ----------------------------------------- |
| **丰枯水期差异电价** | 自定义特征工程：添加 season_wet/dry 特征，丰枯水期分别训练模型 | 丰水期/枯水期模型独立训练，切换时自动加载 |
| **尖峰时段动态调整** | 预测后处理：叠加尖峰时段动态调整系数（夏季×1.3，冬季×1.2）     | 基于天气预报的尖峰电价修正                |
| **陇电入川联络线**   | 省间价差预测：epftoolbox 分别预测川/甘电价，计算价差           | 价差预测 + 联络线 ATC 约束 → 跨省交易决策 |
| **基本电费消减**     | 需量管理策略：epftoolbox 预测高电价时段，储能放电消减需量      | 预测结果输入需量管理模块                  |
| **保供电预警**       | 异常模式检测：epftoolbox 预测偏差 > 阈值时触发保供模式切换     | 预测误差监控 → 模式切换信号               |

---

## 5. 四川市场适配

### 5.1 自定义数据适配层

由于 epftoolbox 内置数据接口主要面向欧美市场，在四川 VPP 项目中需要实现自定义数据适配层：

```python
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from epftoolbox.data import read_data  # 仅用于参考数据格式


class SichuanDataAdapter:
    """
    四川电力市场数据适配器
    将四川电力交易中心的历史电价数据转换为 epftoolbox 可用的格式
    """
    def __init__(self):
        self.market = "SICHUAN"
        self.data_path = "/data/sichuan_electricity/"
        self.required_columns = [
            "date", "hour", "period", "price",
            "load", "hydro_output", "tie_line_flow"
        ]

    def load_historical_data(self, years: int = 2) -> pd.DataFrame:
        """
        加载四川历史电价数据
        从本地数据库或CSV文件读取
        """
        # 实际实现中从 PostgreSQL/TimescaleDB 读取
        # 此处为示意代码
        df = pd.read_csv(f"{self.data_path}sichuan_prices.csv")

        # 数据清洗
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        df = df.dropna(subset=['price'])

        # 转换为 epftoolbox 兼容格式
        df = df.set_index('date')
        df = df.resample('15T').ffill()  # 填充到15分钟粒度

        return df

    def add_sichuan_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        添加四川特殊特征
        """
        # 丰枯水期特征
        df['season_wet'] = df.index.month.isin([6, 7, 8, 9, 10]).astype(int)
        df['season_dry'] = df.index.month.isin([11, 12, 1, 2, 3, 4, 5]).astype(int)

        # 尖峰时段特征
        df['is_sharp_peak'] = df.index.hour.isin([12, 13]).astype(int)

        # 来水特征（从水文数据库获取）
        df['inflow_factor'] = self._get_inflow_factor(df.index)

        # 联络线特征
        df['tie_line_available'] = self._get_tie_line_atc(df.index)

        return df

    def _get_inflow_factor(self, dates: pd.DatetimeIndex) -> pd.Series:
        """获取来水系数（归一化值）"""
        # 实际实现中从水文数据库查询
        month_factors = {
            1: 0.3, 2: 0.25, 3: 0.3, 4: 0.5,
            5: 0.7, 6: 0.9, 7: 1.0, 8: 0.95,
            9: 0.85, 10: 0.6, 11: 0.4, 12: 0.3
        }
        return pd.Series(dates.month.map(month_factors), index=dates)

    def _get_tie_line_atc(self, dates: pd.DatetimeIndex) -> pd.Series:
        """获取联络线可用传输容量"""
        # 实际实现中从电网调度系统获取
        # 丰水期外送容量大，枯水期外送容量小
        base_atc = 8000  # 陇电入川额定容量 MW
        season_factor = dates.month.isin([6, 7, 8, 9, 10]).astype(float) * 0.3 + 0.7
        return pd.Series(base_atc * season_factor, index=dates)
```

### 5.2 丰枯水期模型切换策略

```python
class SeasonalModelManager:
    """
    丰枯水期模型切换管理器
    根据季节自动切换电价预测模型
    """
    def __init__(self):
        self.wet_season_model = None   # 丰水期模型
        self.dry_season_model = None   # 枯水期模型
        self.current_model = None
        self.current_season = None

    def train_seasonal_models(self, historical_data: pd.DataFrame):
        """
        分别训练丰水期和枯水期模型
        """
        # 分离数据
        wet_data = historical_data[
            historical_data.index.month.isin([6, 7, 8, 9, 10])
        ]
        dry_data = historical_data[
            historical_data.index.month.isin([11, 12, 1, 2, 3, 4, 5])
        ]

        # 训练丰水期模型
        print("Training wet season model...")
        self.wet_season_model = self._train_model(wet_data)

        # 训练枯水期模型
        print("Training dry season model...")
        self.dry_season_model = self._train_model(dry_data)

    def switch_model(self, date: datetime):
        """
        根据日期切换模型
        """
        from epftoolbox.data import read_data

        season = "wet" if date.month in [6, 7, 8, 9, 10] else "dry"

        if season != self.current_season:
            self.current_season = season
            if season == "wet":
                self.current_model = self.wet_season_model
            else:
                self.current_model = self.dry_season_model
            print(f"Switched to {season} season model")

    def predict(self, date: datetime, input_data: pd.DataFrame) -> np.ndarray:
        """
        使用当前季节模型进行预测
        """
        self.switch_model(date)
        return self.current_model.predict(input_data)

    def _train_model(self, data: pd.DataFrame):
        """
        训练单个季节模型
        使用 epftoolbox 的 CNN+LSTM 模型
        """
        from epftoolbox.models import CNNLSTM

        model = CNNLSTM()
        model.fit(data)
        return model
```

### 5.3 预测性能目标

| 指标             | Phase 1（单站） | Phase 2（区域） | Phase 3（全省） |
| ---------------- | :-------------: | :-------------: | :-------------: |
| **MAE**          |  < 0.05 元/kWh  |  < 0.04 元/kWh  |  < 0.03 元/kWh  |
| **sMAPE**        |      < 20%      |      < 18%      |      < 15%      |
| **预测延迟**     |    < 5 秒/次    |   < 10 秒/次    |   < 30 秒/次    |
| **模型更新频率** |      每周       |      每日       |  在线持续更新   |

---

## 6. 使用示例

### 6.1 基础电价预测

```python
from epftoolbox.models import CNNLSTM
from epftoolbox.data import read_data
import pandas as pd
import numpy as np

# 加载历史数据（四川市场需使用自定义适配器）
# df = read_data(dataset="SICHUAN", years=2)  # 标准接口
df = SichuanDataAdapter().load_historical_data(years=2)  # 四川适配器

# 训练 CNN+LSTM 模型
model = CNNLSTM()
model.fit(df)

# 预测未来 24 小时电价（96 个 15 分钟时段）
forecast = model.predict_online(df, date="2026-06-01")

# 输出预测结果
print(f"预测日期：2026-06-01（丰水期）")
print(f"预测电价范围：{forecast.min():.3f} - {forecast.max():.3f} 元/kWh")
print(f"平均电价：{forecast.mean():.3f} 元/kWh")
```

### 6.2 省间价差预测

```python
# 分别预测四川和甘肃的电价
sichuan_forecast = predict_da_price("SICHUAN", "2026-06-01")
gansu_forecast = predict_da_price("GANSU", "2026-06-01")

# 计算价差
price_spread = sichuan_forecast - gansu_forecast

# 输出套利机会
max_spread = price_spread.max()
max_spread_hour = price_spread.argmax() // 4
print(f"最大价差：{max_spread:.3f} 元/kWh（发生在 {max_spread_hour}:00）")
print(f"建议：{'从甘肃购电' if max_spread > 0.02 else '不进行跨省交易'}")
```

### 6.3 概率预测（用于风险管控）

```python
# 使用 MC Dropout 生成预测分布
predictions = []
for _ in range(100):
    pred = model.predict_online(df, date="2026-06-01", dropout=True)
    predictions.append(pred)

predictions = np.array(predictions)

# 计算分位数
p10 = np.percentile(predictions, 10, axis=0)
p50 = np.percentile(predictions, 50, axis=0)
p90 = np.percentile(predictions, 90, axis=0)

# 输出用于 CVaR 计算
price_risk = {
    "expected_price": p50,
    "worst_case_10%": p10,
    "best_case_90%": p90,
    "price_volatility": np.std(predictions, axis=0).mean()
}
```

---

## 7. 局限性与风险

### 7.1 已知局限性

| 局限性                 | 说明                                                          | 缓解措施                                                        |
| ---------------------- | ------------------------------------------------------------- | --------------------------------------------------------------- |
| **欧美市场数据接口**   | 内置数据接口主要面向 EPEX/ENTSO-E/PJM，不直接支持中国电力市场 | 实现自定义数据适配层（§5.1）                                    |
| **学术维护模式**       | 社区活跃度 ⭐⭐，更新频率较低                                 | 核心功能稳定，可作为基础预测层；上层叠加自研 LightGBM/LSTM 模型 |
| **四川特殊特征缺失**   | 不支持丰枯水期、联络线 ATC 等四川特有特征                     | 通过自定义特征工程扩展（§5.1）                                  |
| **大规模部署经验不足** | 主要面向学术研究和单站预测                                    | Phase 1 单站验证，Phase 2-3 逐步扩展                            |
| **无内置概率预测**     | 标准接口仅输出点预测                                          | 通过 MC Dropout 或分位数回归扩展（§6.3）                        |

### 7.2 风险等级评估

| 风险项             | 风险等级 | 影响                                               | 应对策略                                                 |
| ------------------ | :------: | -------------------------------------------------- | -------------------------------------------------------- |
| **四川市场适配**   |  🟡 中   | 需额外开发数据适配层，增加 Phase 1 工作量约 2 人周 | Phase 1 优先完成数据适配，确保 Phase 2 可用              |
| **预测精度不达标** |  🟡 中   | 四川丰枯水期电价波动大，预测精度可能低于欧美市场   | 丰枯水期分别训练模型 + 集成多个模型（CNN+LSTM+LightGBM） |
| **模型更新滞后**   |  🟢 低   | 电力市场规则变化可能导致模型失效                   | 在线学习模式 + 预测误差监控告警                          |
| **许可证合规**     |  🟢 低   | Apache 2.0 许可证，商用友好                        | 无需额外处理                                             |

---

## 8. 总结

**epftoolbox** 作为本 VPP 方案交易层的核心电价预测组件，提供了从模型训练到预测评估的完整工作流。其内置的 CNN、LSTM、CNN+LSTM 等深度学习模型，结合四川市场自定义特征工程，能够为报价引擎提供准确的电价预测输入。

在本方案的三阶段实施中，epftoolbox 的集成路径如下：

| 阶段    | epftoolbox 集成状态 | 关键任务                                                     |
| ------- | ------------------- | ------------------------------------------------------------ |
| Phase 1 | ✅ 基础部署         | 自定义数据适配层 + CNN/LSTM 基础模型 + 单站日前预测          |
| Phase 2 | ✅ 功能扩展         | 丰枯水期模型切换 + 省间价差预测 + 日内滚动预测               |
| Phase 3 | ✅ 生产优化         | 模型集成（Ensemble）+ 在线学习 + 概率预测 + 预测误差监控告警 |

> **与自研模型的关系**：epftoolbox 提供开箱即用的电价预测能力，是本方案的**基础预测层**。在 Phase 2-3，将在 epftoolbox 基础上叠加自研的 LightGBM/LSTM 模型，形成模型集成（Ensemble），进一步提升预测精度和鲁棒性。

---

## 版本历史

| 版本 | 日期       | 修改内容                                                                                 |
| :--: | ---------- | ---------------------------------------------------------------------------------------- |
| v1.0 | 2026-05-25 | 初始版本，基于《第一章：总体架构与设计理念》和《第五章：电力交易与报价引擎》相关内容整理 |
