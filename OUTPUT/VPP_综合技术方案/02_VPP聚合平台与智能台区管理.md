# 第二章：VPP聚合平台与智能台区管理

> **基于FlexMeasures的资源聚合与台区级智能管理**
> **融合拓扑发现、带宽协商、风险管控与联络线潮流建模**

---

## 文档信息

| 项目     | 内容                                                |
| -------- | --------------------------------------------------- |
| 文档编号 | VPP-AGG-2026-002                                    |
| 版本号   | v1.0                                                |
| 制定日期 | 2026-05-10                                          |
| 基于框架 | FlexMeasures + OpenEMS + 能源交换机范式             |
| 适用领域 | VPP资源聚合、智能台区管理、风险管控、联络线潮流建模 |

---

## 目录

1. [VPP聚合引擎设计](#1-vpp聚合引擎设计)
2. [智能台区管理](#2-智能台区管理)
3. [风险管控层](#3-风险管控层)
4. [联络线潮流建模](#4-联络线潮流建模)
5. [时序底座升级](#5-时序底座升级)
6. [多站点协同调度](#6-多站点协同调度)
7. [灵活性聚合与上报](#7-灵活性聚合与上报)

---

## 1. VPP聚合引擎设计

### 1.1 基于FlexMeasures的聚合架构

FlexMeasures是一个开源的灵活性能源管理平台，提供灵活性建模（Flexibility Modeling）能力。本方案利用FlexMeasures将多站点的SOC和功率余量聚合为单一资产。

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    VPP聚合引擎架构                                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    聚合资产层 (Aggregated Assets)                     │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │   │
│  │  │ 聚合储能资产  │  │ 聚合光伏资产  │  │ 聚合充电桩资产│              │   │
│  │  │ (虚拟储能池)  │  │ (虚拟光伏场)  │  │ (虚拟充电站)  │              │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                  FlexMeasures 灵活性建模引擎                          │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │   │
│  │  │ 灵活性预测    │  │ 灵活性优化    │  │ 灵活性验证    │              │   │
│  │  │ (Flex Forecast)│  │ (Flex Opt)   │  │ (Flex Verify)│              │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    设备接入层 (Device Layer)                          │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │   │
│  │  │ 储能站点1 │ │ 储能站点2 │ │ 光伏站点1 │ │ 充电站A  │ │ 充电站B  │  │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 灵活性建模

FlexMeasures的核心能力是将单个设备的灵活性约束聚合为统一的灵活性模型：

```python
class FlexibilityModel:
    """
    灵活性建模引擎
    将多站点的灵活性约束聚合为单一资产模型
    """
    def __init__(self):
        self.assets = {}  # {asset_id: AssetInfo}
        self.aggregated_model = None

    def register_asset(self, asset_id, asset_type, capacity_kwh,
                       max_charge_kw, max_discharge_kw,
                       min_soc, max_soc, efficiency):
        """
        注册单个资产
        """
        self.assets[asset_id] = {
            "type": asset_type,  # "battery" | "ev" | "hvac"
            "capacity": capacity_kwh,
            "max_charge": max_charge_kw,
            "max_discharge": max_discharge_kw,
            "min_soc": min_soc,
            "max_soc": max_soc,
            "efficiency": efficiency,
            "current_soc": 50.0,
            "online": True
        }

    def aggregate_flexibility(self, time_horizon_hours=24, resolution_min=15):
        """
        聚合所有资产的灵活性
        输出：聚合后的灵活性模型
        """
        n_periods = int(time_horizon_hours * 60 / resolution_min)

        # 聚合约束
        total_capacity = sum(a["capacity"] for a in self.assets.values() if a["online"])
        total_max_charge = sum(a["max_charge"] for a in self.assets.values() if a["online"])
        total_max_discharge = sum(a["max_discharge"] for a in self.assets.values() if a["online"])

        # 加权平均SOC
        weighted_soc = sum(
            a["capacity"] * a["current_soc"]
            for a in self.assets.values() if a["online"]
        ) / total_capacity if total_capacity > 0 else 50

        self.aggregated_model = {
            "total_capacity_kwh": total_capacity,
            "total_max_charge_kw": total_max_charge,
            "total_max_discharge_kw": total_max_discharge,
            "current_soc": weighted_soc,
            "min_soc": min(a["min_soc"] for a in self.assets.values() if a["online"]),
            "max_soc": max(a["max_soc"] for a in self.assets.values() if a["online"]),
            "n_assets": sum(1 for a in self.assets.values() if a["online"]),
            "n_offline": sum(1 for a in self.assets.values() if not a["online"])
        }

        return self.aggregated_model

    def calculate_flexibility_range(self, pv_forecast, load_forecast):
        """
        计算灵活性范围（可上调/可下调容量）
        """
        agg = self.aggregated_model
        if not agg:
            return None

        # 可上调容量（放电/减载）：当前可提供的上调功率
        flex_up = agg["total_max_discharge"]

        # 可下调容量（充电/增载）：当前可吸收的下调功率
        flex_down = agg["total_max_charge"]

        return {
            "flex_up_kw": flex_up,
            "flex_down_kw": flex_down,
            "flex_up_duration_h": self._calculate_duration("up"),
            "flex_down_duration_h": self._calculate_duration("down")
        }

    def _calculate_duration(self, direction):
        """计算灵活性持续时间"""
        agg = self.aggregated_model
        if direction == "up":
            # 放电持续时间 = 可用能量 / 放电功率
            available_energy = agg["total_capacity_kwh"] * (agg["current_soc"] - agg["min_soc"]) / 100
            return available_energy / agg["total_max_discharge"] if agg["total_max_discharge"] > 0 else 0
        else:
            # 充电持续时间 = 可用容量 / 充电功率
            available_capacity = agg["total_capacity_kwh"] * (agg["max_soc"] - agg["current_soc"]) / 100
            return available_capacity / agg["total_max_charge"] if agg["total_max_charge"] > 0 else 0
```

### 1.3 多类型资源聚合

VPP聚合引擎支持多种类型的分布式资源：

| 资源类型       | 聚合方式                     | 灵活性特性               | 响应时间 |
| -------------- | ---------------------------- | ------------------------ | -------- |
| **储能系统**   | 虚拟储能池（SOC加权平均）    | 双向调节，响应快         | <1秒     |
| **光伏系统**   | 虚拟光伏场（出力总和）       | 单向调节（限功率），间歇 | <5秒     |
| **充电桩**     | 虚拟充电站（功率总和）       | 单向/双向（V2G），可延时 | <5秒     |
| **空调负荷**   | 虚拟温控负荷（温度偏移聚合） | 单向减载，有热惯性       | 5-15分钟 |
| **可中断负荷** | 虚拟可中断负荷（功率总和）   | 单向切断，无惯性         | <1秒     |

### 1.4 聚合资产调度算法

```python
class AggregatedAssetScheduler:
    """
    聚合资产调度器
    将聚合后的调度指令分解到各站点
    """
    def __init__(self, flexibility_model):
        self.flex_model = flexibility_model

    def dispatch_aggregated_power(self, target_power_kw, duration_min):
        """
        将聚合目标功率分解到各站点
        """
        # 1. 计算各站点的分配比例（基于可用容量和信用权重）
        total_available = sum(
            a["max_discharge"] * self._get_credit_weight(aid)
            for aid, a in self.flex_model.assets.items() if a["online"]
        )

        # 2. 按比例分配
        dispatch_plan = {}
        for aid, asset in self.flex_model.assets.items():
            if not asset["online"]:
                continue

            weight = self._get_credit_weight(aid)
            proportion = (asset["max_discharge"] * weight) / total_available
            assigned_power = target_power_kw * proportion

            # 3. 检查站点级约束
            constrained_power = self._apply_local_constraints(
                aid, assigned_power, duration_min
            )

            dispatch_plan[aid] = constrained_power

        return dispatch_plan

    def _get_credit_weight(self, asset_id):
        """获取站点信用权重"""
        # 基于历史响应表现动态计算
        return 0.85  # 简化示例

    def _apply_local_constraints(self, asset_id, power_kw, duration_min):
        """应用本地约束"""
        asset = self.flex_model.assets[asset_id]

        # SOC约束
        energy_needed = power_kw * duration_min / 60  # kWh
        if power_kw > 0:  # 放电
            available_energy = asset["capacity"] * (asset["current_soc"] - asset["min_soc"]) / 100
            if energy_needed > available_energy:
                # 限制功率
                power_kw = available_energy / (duration_min / 60)

        return min(power_kw, asset["max_discharge"])
```

---

## 2. 智能台区管理

### 2.1 台区管理架构

智能台区管理是VPP聚合的基础单元，负责台区内的拓扑发现、带宽管理和协同调度：

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    智能台区管理系统                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    台区拓扑管理层                                      │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │   │
│  │  │ 拓扑发现引擎  │  │ 路由表维护    │  │ 版本号管理    │              │   │
│  │  │ (电压相关+    │  │ (本地+云端)   │  │ (冲突仲裁)   │              │   │
│  │  │  NILM对账)    │  │              │  │              │              │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    带宽管理层                                          │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │   │
│  │  │ 带宽配额计算  │  │ 带宽预借管理  │  │ 信用权重管理  │              │   │
│  │  │ (WFQ算法)    │  │ (邻居协商)   │  │ (动态计算)   │              │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    协同调度层                                          │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │   │
│  │  │ 协同减载引擎  │  │ 功率平衡控制  │  │ 应急保供模式  │              │   │
│  │  │ (多节点协商)  │  │ (实时闭环)   │  │ (孤岛运行)   │              │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 拓扑发现机制

#### 2.2.1 电压相关性分析

物理位置越近的家庭，其电网接入点的电压波动相关性越高：

```python
class VoltageCorrelationDiscovery:
    """
    基于电压相关性的拓扑发现
    """
    def __init__(self, correlation_threshold=0.85):
        self.threshold = correlation_threshold
        self.voltage_fingerprints = {}  # {node_id: [delta_v_samples]}
        self.neighbor_table = {}  # {node_id: correlation}

    def record_voltage_sample(self, node_id, voltage_v, timestamp_ms):
        """
        记录电压采样值
        """
        if node_id not in self.voltage_fingerprints:
            self.voltage_fingerprints[node_id] = []

        self.voltage_fingerprints[node_id].append({
            "timestamp": timestamp_ms,
            "voltage": voltage_v
        })

        # 保持最近300秒的数据（1秒分辨率）
        cutoff = timestamp_ms - 300_000
        self.voltage_fingerprints[node_id] = [
            s for s in self.voltage_fingerprints[node_id]
            if s["timestamp"] > cutoff
        ]

    def generate_fingerprint(self, node_id):
        """
        生成电压波动指纹（过去5分钟的ΔV曲线）
        """
        samples = self.voltage_fingerprints.get(node_id, [])
        if len(samples) < 2:
            return None

        # 计算ΔV
        delta_v = []
        for i in range(1, len(samples)):
            delta_v.append(samples[i]["voltage"] - samples[i-1]["voltage"])

        return {
            "node_id": node_id,
            "timestamp_ms": samples[-1]["timestamp"],
            "delta_v_samples": delta_v,
            "base_voltage_v": samples[-1]["voltage"]
        }

    def calculate_correlation(self, fingerprint_a, fingerprint_b):
        """
        计算两个节点的电压波动相关性
        返回Pearson相关系数
        """
        import numpy as np

        va = np.array(fingerprint_a["delta_v_samples"])
        vb = np.array(fingerprint_b["delta_v_samples"])

        # 对齐长度
        min_len = min(len(va), len(vb))
        va = va[:min_len]
        vb = vb[:min_len]

        if min_len < 10:
            return 0.0

        correlation = np.corrcoef(va, vb)[0, 1]
        return correlation

    def update_neighbor(self, node_id, correlation):
        """
        更新邻居表
        """
        if correlation > self.threshold:
            self.neighbor_table[node_id] = correlation
            return True
        return False

    def get_physically_near_nodes(self):
        """
        获取物理邻近节点列表
        """
        return [
            {"node_id": nid, "correlation": corr}
            for nid, corr in self.neighbor_table.items()
            if corr > self.threshold
        ]
```

#### 2.2.2 NILM事件对账

当某个节点内有大功率设备启停时，会在同一台区下的其他节点电网中产生可检测的电压/电流扰动：

```python
class NILMEventReconciliation:
    """
    NILM事件对账机制
    通过比对事件时间戳和特征，确认物理连接关系
    """
    def __init__(self, time_window_ms=100, feature_threshold=0.9):
        self.time_window = time_window_ms  # 时间戳偏差阈值
        self.feature_threshold = feature_threshold  # 特征匹配阈值
        self.local_events = []  # 本地事件队列
        self.remote_events = []  # 远程事件队列

    def record_local_event(self, event):
        """
        记录本地NILM事件
        """
        self.local_events.append({
            "timestamp_ms": event["timestamp"],
            "power_delta_w": event["power_delta"],
            "harmonic_signature": event["harmonic_signature"],
            "event_type": event["event_type"]
        })
        # 保持最近1分钟的事件
        self._cleanup_old_events()

    def record_remote_event(self, node_id, event):
        """
        记录远程节点广播的NILM事件
        """
        self.remote_events.append({
            "node_id": node_id,
            "timestamp_ms": event["timestamp"],
            "power_delta_w": event["power_delta"],
            "harmonic_signature": event["harmonic_signature"],
            "event_type": event["event_type"]
        })
        self._cleanup_old_events()

    def match_events(self):
        """
        尝试匹配本地和远程事件
        返回匹配结果列表
        """
        matches = []
        for local in self.local_events:
            for remote in self.remote_events:
                # 时间戳匹配
                time_diff = abs(local["timestamp_ms"] - remote["timestamp_ms"])
                if time_diff > self.time_window:
                    continue

                # 特征匹配（谐波特征相似度）
                feature_similarity = self._calculate_similarity(
                    local["harmonic_signature"],
                    remote["harmonic_signature"]
                )
                if feature_similarity < self.feature_threshold:
                    continue

                # 匹配成功
                matches.append({
                    "local_event": local,
                    "remote_node": remote["node_id"],
                    "remote_event": remote,
                    "time_diff_ms": time_diff,
                    "feature_similarity": feature_similarity,
                    "electrical_distance": self._estimate_distance(
                        local["power_delta_w"],
                        remote["power_delta_w"]
                    )
                })

        return matches

    def _calculate_similarity(self, sig_a, sig_b):
        """计算谐波特征相似度"""
        if not sig_a or not sig_b:
            return 0.0

        import numpy as np
        a = np.array(sig_a)
        b = np.array(sig_b)

        # 余弦相似度
        dot_product = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot_product / (norm_a * norm_b)

    def _estimate_distance(self, local_delta, remote_delta):
        """
        基于扰动衰减程度估算电气距离
        扰动衰减越大，电气距离越远
        """
        if local_delta == 0:
            return 1.0
        attenuation = abs(remote_delta) / abs(local_delta)
        # 衰减越小（接近1），距离越近
        return 1.0 - min(attenuation, 1.0)

    def _cleanup_old_events(self):
        """清理过期事件（保留最近1分钟）"""
        cutoff = int(time.time() * 1000) - 60_000
        self.local_events = [e for e in self.local_events if e["timestamp_ms"] > cutoff]
        self.remote_events = [e for e in self.remote_events if e["timestamp_ms"] > cutoff]
```

#### 2.2.3 拓扑版本号管理

```python
class TopologyVersionManager:
    """
    拓扑版本号管理器
    确保多节点拓扑一致性
    """
    def __init__(self, node_id):
        self.node_id = node_id
        self.version = 0
        self.neighbor_versions = {}  # {node_id: version}
        self.change_history = []  # 变更历史

    def increment_version(self, reason):
        """
        拓扑变更时递增版本号
        """
        self.version += 1
        self.change_history.append({
            "timestamp_ms": int(time.time() * 1000),
            "new_version": self.version,
            "reason": reason,
            "initiator": self.node_id
        })
        return self.version

    def sync_with_neighbor(self, neighbor_id, neighbor_version):
        """
        与邻居节点同步版本号
        返回是否需要更新
        """
        self.neighbor_versions[neighbor_id] = neighbor_version

        if neighbor_version > self.version:
            # 邻居版本更高，需要同步
            return "NEED_UPDATE"
        elif neighbor_version < self.version:
            # 本地版本更高，通知邻居
            return "NOTIFY_NEIGHBOR"
        else:
            return "SYNCED"

    def resolve_conflict(self, conflict_node_id, local_version, remote_version):
        """
        解决版本号冲突
        以较高版本号为准
        """
        if remote_version > local_version:
            self.version = remote_version
            self.change_history.append({
                "timestamp_ms": int(time.time() * 1000),
                "new_version": self.version,
                "reason": f"CONFLICT_RESOLVED from {conflict_node_id}",
                "initiator": conflict_node_id
            })
            return "UPDATED_FROM_REMOTE"
        else:
            return "LOCAL_IS_CURRENT"

    def get_version_summary(self):
        """
        获取版本号摘要
        """
        return {
            "node_id": self.node_id,
            "current_version": self.version,
            "neighbor_count": len(self.neighbor_versions),
            "neighbor_versions": self.neighbor_versions,
            "last_change": self.change_history[-1] if self.change_history else None
        }
```

### 2.3 带宽管理

#### 2.3.1 带宽配额计算

```python
class BandwidthManager:
    """
    台区带宽管理器
    基于加权公平队列（WFQ）算法分配带宽
    """
    def __init__(self, transformer_rated_va=315000):
        self.transformer_rated = transformer_rated_va
        self.seasonal_factor = 1.0  # 季节修正系数
        self.ports = {}  # {port_id: PortInfo}
        self.reserved_critical_va = 0

    def set_seasonal_factor(self, temperature_c):
        """
        根据环境温度设置季节修正系数
        """
        if temperature_c <= 25:
            self.seasonal_factor = 1.0
        elif temperature_c <= 35:
            self.seasonal_factor = 1.0 - 0.01 * (temperature_c - 25)
        elif temperature_c <= 40:
            self.seasonal_factor = 0.90 - 0.02 * (temperature_c - 35)
        else:
            self.seasonal_factor = 0.80

    def register_port(self, port_id, rated_power_va, priority_tag, credit_weight=0.5):
        """
        注册端口
        """
        self.ports[port_id] = {
            "rated_power": rated_power_va,
            "priority": priority_tag,  # "L1" | "L2" | "L3" | "L4"
            "credit_weight": credit_weight,
            "current_power": 0,
            "allocated_bandwidth": 0
        }

        # 更新L1预留带宽
        if priority_tag == "L1":
            self.reserved_critical_va += rated_power_va

    def calculate_available_bandwidth(self):
        """
        计算可用带宽
        """
        total_bandwidth = self.transformer_rated * self.seasonal_factor
        # 预留10%安全裕度
        safe_bandwidth = total_bandwidth * 0.9
        # 减去L1预留
        available = safe_bandwidth - self.reserved_critical_va
        return max(0, available)

    def allocate_bandwidth(self):
        """
        按WFQ算法分配带宽
        """
        available = self.calculate_available_bandwidth()

        # 权重定义
        weights = {"L2": 0.5, "L3": 0.3, "L4": 0.2}

        # 按优先级分组
        groups = {"L2": [], "L3": [], "L4": []}
        for pid, port in self.ports.items():
            if port["priority"] in groups:
                groups[port["priority"]].append(pid)

        # 计算各优先级总权重
        total_weight = sum(
            weights[tag] * sum(
                self.ports[pid]["credit_weight"]
                for pid in groups[tag]
            )
            for tag in weights
            if groups[tag]
        )

        # 分配带宽
        allocations = {}
        for tag in ["L2", "L3", "L4"]:
            if not groups[tag]:
                continue

            # 该优先级总权重
            tag_weight = weights[tag] * sum(
                self.ports[pid]["credit_weight"]
                for pid in groups[tag]
            )

            # 该优先级总带宽
            tag_bandwidth = available * (tag_weight / total_weight) if total_weight > 0 else 0

            # 在该优先级内按信用权重分配
            tag_credit_sum = sum(
                self.ports[pid]["credit_weight"]
                for pid in groups[tag]
            )

            for pid in groups[tag]:
                port = self.ports[pid]
                proportion = port["credit_weight"] / tag_credit_sum if tag_credit_sum > 0 else 0
                allocated = tag_bandwidth * proportion
                port["allocated_bandwidth"] = min(allocated, port["rated_power"])
                allocations[pid] = port["allocated_bandwidth"]

        return allocations

    def update_port_power(self, port_id, current_power_va):
        """
        更新端口当前功率
        """
        if port_id in self.ports:
            self.ports[port_id]["current_power"] = current_power_va

    def check_overload(self):
        """
        检查是否过载
        """
        total_current = sum(
            p["current_power"] for p in self.ports.values()
        )
        max_allowed = self.transformer_rated * self.seasonal_factor * 0.9

        return {
            "total_current_va": total_current,
            "max_allowed_va": max_allowed,
            "is_overloaded": total_current > max_allowed,
            "overload_pct": (total_current / max_allowed - 1) * 100 if total_current > max_allowed else 0
        }
```

#### 2.3.2 带宽预借机制

```python
class BandwidthLoanManager:
    """
    带宽预借管理器
    节点间临时带宽借用
    """
    def __init__(self, node_id):
        self.node_id = node_id
        self.active_loans = {}  # {loan_id: LoanInfo}
        self.pending_requests = {}  # {request_id: RequestInfo}

    def request_loan(self, target_node_id, power_w, duration_ms, credit_weight):
        """
        发起带宽预借请求
        """
        request_id = f"loan_req_{self.node_id}_{int(time.time()*1000)}"

        request = {
            "request_id": request_id,
            "requester": self.node_id,
            "target": target_node_id,
            "power_w": power_w,
            "duration_ms": duration_ms,
            "credit_weight": credit_weight,
            "timestamp_ms": int(time.time() * 1000),
            "status": "PENDING"
        }

        self.pending_requests[request_id] = request
        return request

    def approve_loan(self, request_id, available_power_w):
        """
        批准带宽预借
        """
        request = self.pending_requests.get(request_id)
        if not request:
            return None

        loan_id = f"loan_{request_id}"
        loan_power = min(request["power_w"], available_power_w)

        loan = {
            "loan_id": loan_id,
            "requester": request["requester"],
            "lender": self.node_id,
            "power_w": loan_power,
            "duration_ms": request["duration_ms"],
            "start_time_ms": int(time.time() * 1000),
            "status": "ACTIVE"
        }

        self.active_loans[loan_id] = loan
        request["status"] = "APPROVED"

        return loan

    def recall_loan(self, loan_id):
        """
        收回带宽预借（当本地负荷突增时）
        """
        loan = self.active_loans.get(loan_id)
        if not loan:
            return None

        loan["status"] = "RECALLED"
        loan["recall_time_ms"] = int(time.time() * 1000)

        return loan

    def check_expired_loans(self):
        """
        检查过期贷款
        """
        now = int(time.time() * 1000)
        expired = []

        for loan_id, loan in self.active_loans.items():
            if loan["status"] != "ACTIVE":
                continue
            if now - loan["start_time_ms"] > loan["duration_ms"]:
                loan["status"] = "EXPIRED"
                expired.append(loan)

        return expired
```

### 2.4 协同减载协议

#### 2.4.1 减载触发与仲裁

```python
class CoordinatedShedding:
    """
    协同减载管理器
    多节点协同减载的触发、仲裁和执行
    """
    def __init__(self, node_id, bandwidth_manager):
        self.node_id = node_id
        self.bandwidth = bandwidth_manager
        self.shed_requests = {}  # {request_id: ShedRequest}
        self.active_sheds = {}  # {shed_id: ActiveShed}

    def check_and_trigger_shed(self):
        """
        检查是否需要触发减载
        """
        overload = self.bandwidth.check_overload()
        if overload["is_overloaded"]:
            return self._initiate_shed(overload["overload_pct"])
        return None

    def _initiate_shed(self, overload_pct):
        """
        发起减载请求
        """
        required_shed_w = overload_pct / 100 * self.bandwidth.transformer_rated

        request_id = f"shed_{self.node_id}_{int(time.time()*1000)}"
        request = {
            "request_id": request_id,
            "initiator": self.node_id,
            "required_shed_w": required_shed_w,
            "urgency": "HIGH" if overload_pct > 20 else "MEDIUM",
            "timestamp_ms": int(time.time() * 1000),
            "responses": {}
        }

        self.shed_requests[request_id] = request
        return request

    def evaluate_shed_capacity(self):
        """
        评估本地可减载容量
        """
        # 按优先级评估
        shed_capacity = {"L4": 0, "L3": 0, "L2": 0}

        for pid, port in self.bandwidth.ports.items():
            if port["priority"] == "L4":
                shed_capacity["L4"] += port["current_power"]
            elif port["priority"] == "L3":
                shed_capacity["L3"] += port["current_power"] * 0.8  # 可减80%
            elif port["priority"] == "L2":
                shed_capacity["L2"] += port["current_power"] * 0.3  # 可减30%

        return shed_capacity

    def respond_to_shed_request(self, request_id):
        """
        响应减载请求
        """
        request = self.shed_requests.get(request_id)
        if not request:
            return None

        capacity = self.evaluate_shed_capacity()
        total_can_shed = sum(capacity.values())

        # 计算减载成本（L4成本最低，L2成本最高）
        shed_cost = (
            capacity["L4"] * 1 +
            capacity["L3"] * 3 +
            capacity["L2"] * 5
        )

        response = {
            "responder": self.node_id,
            "can_shed_w": total_can_shed,
            "shed_cost": shed_cost,
            "capacity_breakdown": capacity,
            "estimated_duration_s": 600  # 默认10分钟
        }

        request["responses"][self.node_id] = response
        return response

    def arbitrate_shed(self, request_id):
        """
        减载仲裁
        按减载成本从低到高选择最优组合
        """
        request = self.shed_requests.get(request_id)
        if not request:
            return None

        # 按减载成本排序
        sorted_responses = sorted(
            request["responses"].values(),
            key=lambda r: r["shed_cost"] / r["can_shed_w"] if r["can_shed_w"] > 0 else float('inf')
        )

        # 选择最优组合
        selected = []
        accumulated = 0
        for response in sorted_responses:
            if accumulated >= request["required_shed_w"]:
                break
            selected.append(response)
            accumulated += response["can_shed_w"]

        # 创建减载计划
        shed_id = f"shed_exec_{request_id}"
        shed_plan = {
            "shed_id": shed_id,
            "request_id": request_id,
            "required_shed_w": request["required_shed_w"],
            "actual_shed_w": accumulated,
            "selected_nodes": [
                {
                    "node_id": r["responder"],
                    "shed_w": r["can_shed_w"],
                    "capacity_breakdown": r["capacity_breakdown"]
                }
                for r in selected
            ],
            "is_sufficient": accumulated >= request["required_shed_w"],
            "timestamp_ms": int(time.time() * 1000)
        }

        self.active_sheds[shed_id] = shed_plan
        return shed_plan
```

#### 2.4.2 减载执行次序

```python
class ShedExecutionEngine:
    """
    减载执行引擎
    按5步次序执行减载，每步带随机延迟和斜率限制
    """
    def __init__(self):
        # 5步减载配置
        self.shed_steps = [
            {"name": "STEP1_L4_CUT", "delay_ms": 0, "action": "cut_l4"},
            {"name": "STEP2_L3_50PCT", "delay_ms": 50, "action": "limit_l3_50"},
            {"name": "STEP3_L3_MIN", "delay_ms": 200, "action": "limit_l3_min"},
            {"name": "STEP4_L2_70PCT", "delay_ms": 500, "action": "limit_l2_70"},
            {"name": "STEP5_EMERGENCY", "delay_ms": 1000, "action": "emergency_cut"}
        ]

    def execute_shed_plan(self, shed_plan, node_id):
        """
        执行减载计划
        """
        import random
        import time

        for step in self.shed_steps:
            # 引入基于节点ID哈希的随机延迟（0-50ms），防止多台区同步动作
            jitter = random.randint(0, 50)
            total_delay = step["delay_ms"] + jitter

            # 执行减载动作
            result = self._execute_step(step["action"], shed_plan, node_id)

            # 验证功率是否真实下降
            if not self._verify_power_reduction(result):
                # 未响应，立即执行下一级动作
                continue

            # 记录SOE
            self._record_shed_soe(step, result, node_id)

        return {"status": "COMPLETED", "shed_plan_id": shed_plan["shed_id"]}

    def _execute_step(self, action, shed_plan, node_id):
        """执行单步减载动作"""
        # 实际实现中调用设备控制接口
        return {"action": action, "power_reduced_w": 0}

    def _verify_power_reduction(self, result):
        """验证功率是否真实下降"""
        # 实际实现中读取实时功率
        return True

    def _record_shed_soe(self, step, result, node_id):
        """记录减载SOE事件"""
        # 实际实现中写入SOE日志
        pass
```

### 2.5 信用权重动态计算

```python
class CreditWeightCalculator:
    """
    信用权重动态计算器
    基于设备历史行为动态计算信用权重
    """
    def __init__(self):
        self.history = {}  # {device_id: [ResponseRecord]}

    def record_response(self, device_id, success, target_power, actual_power, response_time_ms):
        """
        记录设备响应行为
        """
        if device_id not in self.history:
            self.history[device_id] = []

        self.history[device_id].append({
            "success": success,
            "target_power": target_power,
            "actual_power": actual_power,
            "response_time_ms": response_time_ms,
            "timestamp_ms": int(time.time() * 1000)
        })

        # 保留最近100次记录
        if len(self.history[device_id]) > 100:
            self.history[device_id] = self.history[device_id][-100:]

    def calculate_credit(self, device_id):
        """
        计算设备信用权重
        Credit = 0.4 x ResponseRate + 0.3 x Accuracy + 0.2 x Availability + 0.1 x Age
        """
        records = self.history.get(device_id, [])
        if not records:
            return 0.5  # 默认权重

        # 1. 响应成功率 (ResponseRate)
        success_count = sum(1 for r in records if r["success"])
        response_rate = success_count / len(records)

        # 2. 功率精度 (Accuracy)
        accuracy_scores = []
        for r in records:
            if r["target_power"] > 0:
                deviation = abs(r["actual_power"] - r["target_power"]) / r["target_power"]
                accuracy_scores.append(max(0, 1 - deviation))
        accuracy = sum(accuracy_scores) / len(accuracy_scores) if accuracy_scores else 0

        # 3. 在线率 (Availability) - 简化计算
        availability = 0.95  # 实际从心跳数据计算

        # 4. 设备年龄 (Age)
        age_days = len(records)  # 简化：记录数越多越可信
        age_factor = min(1.0, age_days / 100)

        # 加权计算
        credit = (
            0.4 * response_rate +
            0.3 * accuracy +
            0.2 * availability +
            0.1 * age_factor
        )

        return min(1.0, max(0.0, credit))
```

---

## 3. 风险管控层

### 3.1 风险管控架构

风险管控层是VPP聚合平台的核心决策支持模块，负责在每轮调度前评估风险：

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    风险管控层 (Risk Layer)                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    风险度量引擎                                        │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │   │
│  │  │ VaR计算      │  │ CVaR计算     │  │ 压力测试      │              │   │
│  │  │ (Value at    │  │ (Conditional │  │ (Scenario    │              │   │
│  │  │  Risk)       │  │  VaR)        │  │  Analysis)   │              │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    风险场景库                                          │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │   │
│  │  │ 电价剧烈波动  │  │ 联络线故障    │  │ 极端天气      │              │   │
│  │  │ (50%+波动)   │  │ (特高压闭锁)  │  │ (高温/冰冻)   │              │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    风险应对策略                                        │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │   │
│  │  │ 合同违约对冲  │  │ 联络线闭锁    │  │ 应急保供切换  │              │   │
│  │  │ (自动减载)   │  │ (跨省→本地)  │  │ (孤岛运行)   │              │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 CVaR条件风险价值计算

```python
import numpy as np
from scipy import stats

class CVaRCalculator:
    """
    CVaR（条件风险价值）计算器
    用于评估电价剧烈波动时的潜在损失
    """
    def __init__(self, confidence_level=0.95):
        self.confidence_level = confidence_level  # 置信水平

    def calculate_cvar(self, price_scenarios, contract_positions):
        """
        计算CVaR
        price_scenarios: 电价场景矩阵 [n_scenarios, n_periods]
        contract_positions: 合同头寸 [n_periods]
        """
        # 计算每个场景的损益
        pnl_scenarios = []
        for scenario in price_scenarios:
            pnl = self._calculate_pnl(scenario, contract_positions)
            pnl_scenarios.append(pnl)

        pnl_array = np.array(pnl_scenarios)

        # 计算VaR（在置信水平下的最大可能损失）
        var = np.percentile(pnl_array, (1 - self.confidence_level) * 100)

        # 计算CVaR（超过VaR的期望损失）
        cvar = pnl_array[pnl_array <= var].mean()

        return {
            "var": var,
            "cvar": cvar,
            "confidence_level": self.confidence_level,
            "n_scenarios": len(price_scenarios),
            "mean_pnl": pnl_array.mean(),
            "std_pnl": pnl_array.std()
        }

    def _calculate_pnl(self, prices, positions):
        """
        计算给定电价场景下的损益
        """
        # 简化：购电成本 = 价格 x 电量
        total_cost = np.sum(prices * positions)
        return -total_cost  # 负值表示成本

    def stress_test(self, base_price, volatility, contract_positions, n_scenarios=10000):
        """
        压力测试
        生成蒙特卡洛场景并计算CVaR
        """
        n_periods = len(contract_positions)

        # 生成电价场景（几何布朗运动）
        scenarios = []
        for _ in range(n_scenarios):
            # 对数正态分布模拟电价
            returns = np.random.normal(0, volatility, n_periods)
            price_path = base_price * np.exp(np.cumsum(returns))
            scenarios.append(price_path)

        return self.calculate_cvar(scenarios, contract_positions)

    def check_contract_breach_risk(self, price_volatility, contract_penalty,
                                    current_position, threshold=0.5):
        """
        检查合同违约风险
        若次日现货电价出现50%以上剧烈波动，系统是否会触发合同违约罚款
        """
        # 模拟50%以上波动的极端场景
        extreme_scenarios = []
        for _ in range(1000):
            shock = np.random.choice([-1, 1]) * np.random.uniform(0.5, 1.0)
            extreme_price = current_position * (1 + shock)
            extreme_scenarios.append(extreme_price)

        # 计算违约概率
        breach_count = 0
        for price in extreme_scenarios:
            if self._would_trigger_breach(price, contract_penalty):
                breach_count += 1

        breach_probability = breach_count / 1000

        return {
            "breach_probability": breach_probability,
            "is_high_risk": breach_probability > threshold,
            "recommended_action": "REDUCE_POSITION" if breach_probability > threshold else "MAINTAIN"
        }

    def _would_trigger_breach(self, price, penalty):
        """判断是否触发合同违约"""
        # 简化逻辑：价格波动超过50%触发违约
        return abs(price) > 0.5
```

### 3.3 联络线闭锁风险模拟

```python
class TieLineRiskSimulator:
    """
    联络线闭锁风险模拟器
    模拟特高压线路故障时，系统如何快速从"跨省套利模式"切回"本地保供模式"
    """
    def __init__(self, local_capacity_mw=500, tie_line_capacity_mw=200):
        self.local_capacity = local_capacity_mw  # 本地发电容量
        self.tie_line_capacity = tie_line_capacity_mw  # 联络线容量
        self.is_tie_line_available = True
        self.switchover_time_ms = 0

    def simulate_tie_line_failure(self, current_import_mw, local_load_mw,
                                   battery_soc, battery_capacity_mwh):
        """
        模拟联络线故障场景
        计算切换时间和保供能力
        """
        # 1. 检测故障
        detection_time_ms = 50  # 故障检测时间

        # 2. 切换决策
        decision_time_ms = 100  # 决策时间

        # 3. 执行切换
        execution_time_ms = 200  # 执行时间

        total_switchover_ms = detection_time_ms + decision_time_ms + execution_time_ms
        self.switchover_time_ms = total_switchover_ms

        # 4. 计算切换后的功率缺口
        power_gap_mw = current_import_mw  # 联络线中断后，需要本地填补

        # 5. 评估本地保供能力
        battery_available_mw = min(
            battery_capacity_mwh * (battery_soc / 100) * 0.8,  # 可用80%容量
            self.local_capacity
        )

        can_sustain = battery_available_mw >= power_gap_mw

        return {
            "switchover_time_ms": total_switchover_ms,
            "power_gap_mw": power_gap_mw,
            "battery_available_mw": battery_available_mw,
            "can_sustain": can_sustain,
            "sustainable_hours": battery_available_mw / power_gap_mw if power_gap_mw > 0 else float('inf'),
            "risk_level": "LOW" if can_sustain else "HIGH",
            "recommended_action": "MAINTAIN" if can_sustain else "SHED_LOAD"
        }

    def simulate_emergency_switchover(self):
        """
        模拟应急切换流程
        """
        steps = [
            {"step": 1, "action": "检测联络线故障", "time_ms": 50},
            {"step": 2, "action": "挂起所有跨省套利策略", "time_ms": 30},
            {"step": 3, "action": "切换至本地保供模式", "time_ms": 50},
            {"step": 4, "action": "储能切换至放电模式", "time_ms": 100},
            {"step": 5, "action": "联络线功率归零", "time_ms": 50},
            {"step": 6, "action": "启动非关键负荷减载", "time_ms": 100},
            {"step": 7, "action": "确认本地功率平衡", "time_ms": 50}
        ]

        total_time = sum(s["time_ms"] for s in steps)

        return {
            "steps": steps,
            "total_time_ms": total_time,
            "is_within_limit": total_time < 2000  # 2秒内完成切换
        }
```

### 3.4 风险监控仪表盘

```python
class RiskMonitorDashboard:
    """
    风险监控仪表盘
    实时展示系统风险状态
    """
    def __init__(self):
        self.risk_metrics = {}
        self.alerts = []

    def update_metrics(self, cvar_result, tie_line_risk, market_volatility):
        """
        更新风险指标
        """
        self.risk_metrics = {
            "cvar": cvar_result,
            "tie_line_risk": tie_line_risk,
            "market_volatility": market_volatility,
            "timestamp_ms": int(time.time() * 1000)
        }

        # 检查是否需要告警
        self._check_alerts()

    def _check_alerts(self):
        """检查风险告警"""
        if self.risk_metrics.get("cvar", {}).get("cvar", 0) < -100000:
            self.alerts.append({
                "level": "WARNING",
                "message": "CVaR超过阈值，建议减少头寸",
                "timestamp_ms": int(time.time() * 1000)
            })

        if self.risk_metrics.get("tie_line_risk", {}).get("risk_level") == "HIGH":
            self.alerts.append({
                "level": "CRITICAL",
                "message": "联络线闭锁风险高，建议切换至本地保供模式",
                "timestamp_ms": int(time.time() * 1000)
            })

    def get_dashboard_data(self):
        """
        获取仪表盘数据
        """
        return {
            "risk_metrics": self.risk_metrics,
            "recent_alerts": self.alerts[-10:],  # 最近10条告警
            "overall_risk_level": self._calculate_overall_risk()
        }

    def _calculate_overall_risk(self):
        """计算总体风险等级"""
        risk_score = 0

        if self.risk_metrics.get("cvar", {}).get("cvar", 0) < -50000:
            risk_score += 3
        if self.risk_metrics.get("tie_line_risk", {}).get("risk_level") == "HIGH":
            risk_score += 4
        if self.risk_metrics.get("market_volatility", 0) > 0.5:
            risk_score += 2

        if risk_score >= 7:
            return "CRITICAL"
        elif risk_score >= 4:
            return "HIGH"
        elif risk_score >= 2:
            return "MEDIUM"
        return "LOW"
```

---

## 4. 联络线潮流建模

### 4.1 跨省联络线模型

本方案针对四川省的"陇电入川"特高压直流联络线进行专项建模：

```python
class InterprovincialTieLine:
    """
    跨省联络线模型
    支持四川-甘肃跨省电力交易优化
    """
    def __init__(self, name="陇电入川", rated_capacity_mw=8000):
        self.name = name
        self.rated_capacity = rated_capacity_mw  # 额定容量
        self.atc = rated_capacity_mw * 0.9  # 初始可用传输容量
        self.wheeling_charge_per_kwh = 0.03  # 输电网费（元/kWh）

    def update_atc(self, new_atc_mw):
        """
        更新可用传输容量
        实际中从调度系统获取
        """
        self.atc = new_atc_mw

    def calculate_arbitrage_opportunity(self, gansu_price, sichuan_price):
        """
        计算跨省套利机会
        当甘肃电价 + 输电网费 < 四川电价时，存在套利空间
        """
        total_cost = gansu_price + self.wheeling_charge_per_kwh
        spread = sichuan_price - total_cost

        if spread > 0:
            return {
                "has_opportunity": True,
                "spread_per_kwh": spread,
                "max_import_mw": self.atc,
                "estimated_hourly_profit": spread * self.atc * 1000  # 元/小时
            }
        else:
            return {
                "has_opportunity": False,
                "spread_per_kwh": spread,
                "max_import_mw": 0,
                "estimated_hourly_profit": 0
            }

    def get_pyomo_constraint(self, model, t):
        """
        Pyomo联络线约束
        跨省购电量 <= 联络线剩余可用容量(ATC)
        """
        return model.Gansu_Import[t] <= model.Tie_Line_ATC[t]
```

### 4.2 跨省套利优化模型

```python
from pyomo.environ import *

class InterprovincialArbitrageOptimizer:
    """
    跨省套利优化器
    使用Pyomo构建包含输电网费的成本目标函数
    """
    def __init__(self, tie_line, local_assets):
        self.tie_line = tie_line
        self.assets = local_assets

    def build_optimization_model(self, price_forecast_sichuan,
                                  price_forecast_gansu, load_forecast,
                                  pv_forecast, time_horizon=24):
        """
        构建优化模型
        """
        model = ConcreteModel()
        T = range(time_horizon)

        # 变量
        model.Gansu_Import = Var(T, within=NonNegativeReals)  # 甘肃购电
        model.Battery_Charge = Var(T, within=NonNegativeReals)  # 储能充电
        model.Battery_Discharge = Var(T, within=NonNegativeReals)  # 储能放电
        model.SOC = Var(T, within=NonNegativeReals, bounds=(20, 95))  # SOC

        # 参数
        model.Price_Sichuan = Param(T, initialize=price_forecast_sichuan)
        model.Price_Gansu = Param(T, initialize=price_forecast_gansu)
        model.Load = Param(T, initialize=load_forecast)
        model.PV = Param(T, initialize=pv_forecast)
        model.Tie_Line_ATC = Param(T, initialize={t: self.tie_line.atc for t in T})

        # 目标函数：最小化总成本
        def objective_rule(model):
            total_cost = 0
            for t in T:
                # 四川购电成本
                local_purchase = max(0, model.Load[t] - model.PV[t]
                                     + model.Battery_Charge[t]
                                     - model.Battery_Discharge[t]
                                     - model.Gansu_Import[t])
                total_cost += local_purchase * model.Price_Sichuan[t]

                # 甘肃购电成本（含输电网费）
                total_cost += model.Gansu_Import[t] * (
                    model.Price_Gansu[t] + self.tie_line.wheeling_charge_per_kwh
                )

            return total_cost

        model.Objective = Objective(rule=objective_rule, sense=minimize)

        # 约束：功率平衡
        def power_balance_rule(model, t):
            return (model.PV[t] + model.Battery_Discharge[t] + model.Gansu_Import[t]
                    == model.Load[t] + model.Battery_Charge[t])
        model.PowerBalance = Constraint(T, rule=power_balance_rule)

        # 约束：联络线容量
        def tie_line_rule(model, t):
            return model.Gansu_Import[t] <= model.Tie_Line_ATC[t]
        model.TieLineConstraint = Constraint(T, rule=tie_line_rule)

        # 约束：SOC动态
        def soc_dynamics_rule(model, t):
            if t == 0:
                return model.SOC[t] == 50  # 初始SOC
            return (model.SOC[t] == model.SOC[t-1]
                    + model.Battery_Charge[t] * 0.95  # 充电效率
                    - model.Battery_Discharge[t] / 0.95)  # 放电效率
        model.SOCDynamics = Constraint(T, rule=soc_dynamics_rule)

        return model

    def solve(self, model):
        """
        求解优化模型
        """
        solver = SolverFactory('glpk')  # 或使用 'cbc', 'gurobi'
        result = solver.solve(model, tee=False)

        if result.solver.status == SolverStatus.ok:
            return {
                "status": "OPTIMAL",
                "objective": model.Objective(),
                "gansu_import": [model.Gansu_Import[t].value for t in model.T],
                "battery_charge": [model.Battery_Charge[t].value for t in model.T],
                "battery_discharge": [model.Battery_Discharge[t].value for t in model.T],
                "soc": [model.SOC[t].value for t in model.T]
            }
        else:
            return {"status": "INFEASIBLE", "objective": None}
```

---

## 5. 时序底座升级

### 5.1 TDengine超级表设计

针对四川地理分布广的特点，建立按"供电分区"索引的超级表：

```sql
-- 创建超级表（按供电分区索引）
CREATE STABLE meters (
    ts TIMESTAMP,
    voltage FLOAT,
    current FLOAT,
    active_power FLOAT,
    reactive_power FLOAT,
    power_factor FLOAT,
    frequency FLOAT,
    thd_v FLOAT,
    thd_i FLOAT,
    temperature FLOAT
) TAGS (
    station_id BINARY(32),
    supply_zone BINARY(16),  -- 供电分区
    device_type BINARY(16),
    voltage_level BINARY(8)
);

-- 创建子表（每个站点一个子表）
CREATE TABLE station_001 USING meters TAGS(
    'STATION_001', 'ZONE_A', 'BATTERY', '10kV'
);

CREATE TABLE station_002 USING meters TAGS(
    'STATION_002', 'ZONE_A', 'PV', '10kV'
);

CREATE TABLE station_003 USING meters TAGS(
    'STATION_003', 'ZONE_B', 'EVCS', '0.4kV'
);

-- 跨区域检索示例
SELECT AVG(active_power), COUNT(*)
FROM meters
WHERE supply_zone = 'ZONE_A'
  AND ts >= NOW - 1h
  AND device_type = 'BATTERY'
INTERVAL(5m);
```

### 5.2 TDengine vs InfluxDB 对比

| 对比维度       | TDengine                       | InfluxDB      |
| -------------- | ------------------------------ | ------------- |
| **存储压缩率** | 10-20倍（列式存储+时间戳压缩） | 3-5倍         |
| **写入性能**   | 单机100万点/秒                 | 单机50万点/秒 |
| **查询性能**   | 10倍于InfluxDB（时序聚合场景） | 基准          |
| **超级表**     | 支持（按供电分区索引）         | 不支持        |
| **国产化**     | 支持（信创合规）               | 不支持        |
| **集群部署**   | 原生支持                       | 企业版支持    |
| **SQL兼容**    | 类SQL                          | Flux/InfluxQL |
| **推荐场景**   | 海量站点秒级波形存储           | 中小规模部署  |

### 5.3 数据保留策略

```sql
-- 创建数据保留策略
-- 原始波形数据：保留7天
CREATE STABLE raw_waveforms (
    ts TIMESTAMP,
    phase_a_current FLOAT,
    phase_b_current FLOAT,
    phase_c_current FLOAT,
    phase_a_voltage FLOAT,
    phase_b_voltage FLOAT,
    phase_c_voltage FLOAT
) TAGS (
    station_id BINARY(32)
);

-- 设置保留策略
ALTER DATABASE vpp_data RETENTION 3650;  -- 10年
-- 1kHz原始波形：7天
-- 1秒聚合数据：90天
-- 1分钟聚合数据：1年
-- 1小时聚合数据：10年

-- 创建连续聚合（自动降采样）
CREATE CONTINUOUS AGGREGATION agg_1s ON meters
BEGIN
    SELECT AVG(active_power), MAX(active_power), MIN(active_power)
    FROM meters
    INTERVAL(1s)
END;

CREATE CONTINUOUS AGGREGATION agg_1m ON meters
BEGIN
    SELECT AVG(active_power), MAX(active_power), MIN(active_power)
    FROM meters
    INTERVAL(1m)
END;
```

---

## 6. 多站点协同调度

### 6.1 协同调度架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    多站点协同调度架构                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    全局调度器 (Global Scheduler)                      │   │
│  │  - 接收VPP云端调度目标                                                │   │
│  │  - 分解为各站点调度指令                                                │   │
│  │  - 监控各站点执行状态                                                  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│        ┌───────────────────────────┼───────────────────────────┐           │
│        ▼                           ▼                           ▼           │
│  ┌─────────────┐           ┌─────────────┐           ┌─────────────┐      │
│  │ 站点调度器A  │           │ 站点调度器B  │           │ 站点调度器C  │      │
│  │ (本地执行)   │◄─────────►│ (本地执行)   │◄─────────►│ (本地执行)   │      │
│  └─────────────┘           └─────────────┘           └─────────────┘      │
│        │                         │                         │               │
│        ▼                         ▼                         ▼               │
│  ┌─────────────┐           ┌─────────────┐           ┌─────────────┐      │
│  │ 本地设备群   │           │ 本地设备群   │           │ 本地设备群   │      │
│  └─────────────┘           └─────────────┘           └─────────────┘      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6.2 全局调度算法

```python
class GlobalScheduler:
    """
    全局调度器
    将VPP云端调度目标分解到各站点
    """
    def __init__(self):
        self.stations = {}  # {station_id: StationInfo}
        self.global_target = None

    def register_station(self, station_id, max_power_kw, min_power_kw,
                         efficiency, credit_weight=0.5):
        """
        注册站点
        """
        self.stations[station_id] = {
            "max_power": max_power_kw,
            "min_power": min_power_kw,
            "efficiency": efficiency,
            "credit_weight": credit_weight,
            "current_power": 0,
            "online": True
        }

    def set_global_target(self, target_power_kw, target_duration_min):
        """
        设置全局调度目标
        """
        self.global_target = {
            "power_kw": target_power_kw,
            "duration_min": target_duration_min,
            "timestamp_ms": int(time.time() * 1000)
        }

    def dispatch(self):
        """
        执行全局调度分解
        """
        if not self.global_target:
            return None

        target = self.global_target["power_kw"]
        online_stations = {sid: s for sid, s in self.stations.items() if s["online"]}

        if not online_stations:
            return {"status": "NO_ONLINE_STATIONS"}

        # 计算总可用容量
        total_max = sum(s["max_power"] for s in online_stations.values())
        total_min = sum(s["min_power"] for s in online_stations.values())

        if target > total_max:
            return {"status": "INSUFFICIENT_CAPACITY", "max_available": total_max}
        if target < total_min:
            return {"status": "EXCESS_MIN_LOAD", "min_required": total_min}

        # 按经济性排序（效率越高越优先调度）
        sorted_stations = sorted(
            online_stations.items(),
            key=lambda x: x[1]["efficiency"],
            reverse=True
        )

        # 分配功率
        dispatch_plan = {}
        remaining = target

        for sid, station in sorted_stations:
            if remaining <= 0:
                dispatch_plan[sid] = 0
                continue

            # 该站点可分配功率
            available = station["max_power"] - station["min_power"]
            assigned = min(available, remaining)
            dispatch_plan[sid] = station["min_power"] + assigned
            remaining -= assigned

        return {
            "status": "DISPATCHED",
            "target_power_kw": target,
            "dispatch_plan": dispatch_plan,
            "timestamp_ms": int(time.time() * 1000)
        }
```

---

## 7. 灵活性聚合与上报

### 7.1 灵活性上报格式

```json
{
  "method": "reportFlexibility",
  "params": {
    "node_id": "VPP-AGG-001",
    "timestamp": 1715218372000,
    "window_start": 1715218372000,
    "window_end": 1715220172000,
    "baseline_power_w": 150000,
    "flexibility": {
      "up": {
        "capacity_w": 50000,
        "duration_s": 300,
        "ramp_rate_w_per_s": 2000,
        "confidence": 0.9,
        "sources": {
          "battery_discharge": 30000,
          "ev_v2g": 15000,
          "load_shed": 5000
        }
      },
      "down": {
        "capacity_w": 80000,
        "duration_s": 600,
        "ramp_rate_w_per_s": 3000,
        "confidence": 0.85,
        "sources": {
          "battery_charge": 40000,
          "ev_charge": 30000,
          "load_increase": 10000
        }
      }
    },
    "constraints": {
      "thermal_headroom_w": 30000,
      "battery_available_w": 20000,
      "ev_available_w": 30000,
      "min_soc": 20,
      "max_soc": 95
    }
  }
}
```

### 7.2 灵活性计算引擎

```python
class FlexibilityCalculator:
    """
    灵活性计算引擎
    实时计算并向VPP云端上报灵活性聚合容量
    """
    def __init__(self, flexibility_model):
        self.flex_model = flexibility_model
        self.baseline_calculator = BaselineCalculator()

    def calculate_flexibility(self, forecast_horizon_min=15):
        """
        计算未来时间窗口的灵活性容量
        """
        agg = self.flex_model.aggregate_flexibility()
        baseline = self.baseline_calculator.calculate_baseline()

        # 可上调容量（放电/减载）
        flex_up = {
            "capacity_w": agg["total_max_discharge"] * 1000,
            "duration_s": self._calculate_up_duration(agg) * 3600,
            "ramp_rate_w_per_s": agg["total_max_discharge"] * 1000 / 5,  # 5秒爬坡
            "confidence": self._calculate_confidence("up"),
            "sources": self._get_flex_sources("up")
        }

        # 可下调容量（充电/增载）
        flex_down = {
            "capacity_w": agg["total_max_charge"] * 1000,
            "duration_s": self._calculate_down_duration(agg) * 3600,
            "ramp_rate_w_per_s": agg["total_max_charge"] * 1000 / 5,
            "confidence": self._calculate_confidence("down"),
            "sources": self._get_flex_sources("down")
        }

        return {
            "baseline_power_w": baseline * 1000,
            "flex_up": flex_up,
            "flex_down": flex_down,
            "timestamp_ms": int(time.time() * 1000)
        }

    def _calculate_up_duration(self, agg):
        """计算可上调持续时间（小时）"""
        available_energy = agg["total_capacity_kwh"] * (agg["current_soc"] - agg["min_soc"]) / 100
        return available_energy / agg["total_max_discharge"] if agg["total_max_discharge"] > 0 else 0

    def _calculate_down_duration(self, agg):
        """计算可下调持续时间（小时）"""
        available_capacity = agg["total_capacity_kwh"] * (agg["max_soc"] - agg["current_soc"]) / 100
        return available_capacity / agg["total_max_charge"] if agg["total_max_charge"] > 0 else 0

    def _calculate_confidence(self, direction):
        """计算灵活性置信度"""
        # 基于历史预测精度动态计算
        return 0.85  # 简化示例

    def _get_flex_sources(self, direction):
        """获取灵活性来源明细"""
        sources = {}
        for aid, asset in self.flex_model.assets.items():
            if not asset["online"]:
                continue
            if direction == "up" and asset["type"] in ["battery", "ev"]:
                sources[aid] = asset["max_discharge"] * 1000
            elif direction == "down" and asset["type"] in ["battery", "ev"]:
                sources[aid] = asset["max_charge"] * 1000
        return sources


class BaselineCalculator:
    """
    基线计算器
    基于历史数据计算"无调控状态下"的负荷曲线
    """
    def __init__(self, window_days=30, similar_days=10):
        self.window_days = window_days
        self.similar_days = similar_days
        self.historical_data = []

    def load_historical_data(self, data):
        """加载历史数据"""
        self.historical_data = data

    def calculate_baseline(self, target_date=None):
        """
        计算基线负荷
        取最近10个相似日的负荷数据，剔除最高和最低值后取平均
        """
        if not self.historical_data:
            return 100.0  # 默认基线

        # 筛选相似日（同类型日、同天气条件）
        similar_days = self._find_similar_days(target_date)

        if len(similar_days) < 3:
            return 100.0

        # 剔除最高和最低值
        sorted_days = sorted(similar_days)
        trimmed = sorted_days[1:-1] if len(sorted_days) > 2 else sorted_days

        # 取平均
        baseline = sum(trimmed) / len(trimmed)
        return baseline

    def _find_similar_days(self, target_date):
        """查找相似日"""
        # 简化实现：返回最近N天的平均负荷
        if not self.historical_data:
            return []
        return self.historical_data[-self.similar_days:]
```

---

## 8. 本章小结

本章详细阐述了VPP聚合平台与智能台区管理的核心架构和实现方案：

| 模块               | 核心能力                           | 关键技术                     |
| ------------------ | ---------------------------------- | ---------------------------- |
| **VPP聚合引擎**    | 多类型资源聚合为单一资产           | FlexMeasures灵活性建模       |
| **智能台区管理**   | 拓扑发现、带宽管理、协同减载       | 电压相关性+NILM对账、WFQ算法 |
| **风险管控层**     | CVaR计算、压力测试、联络线闭锁模拟 | QuantLib/SciPy、蒙特卡洛模拟 |
| **联络线潮流建模** | 跨省套利优化、ATC约束              | Pyomo MILP优化               |
| **时序底座**       | 海量站点秒级波形存储               | TDengine超级表               |
| **多站点协同调度** | 全局目标分解、经济性排序           | 分层调度架构                 |
| **灵活性聚合上报** | 实时计算可调容量                   | JSON-RPC标准化上报           |

下一章将详细阐述**电力零售与合同能源管理**，包括合同函数化引擎、动态电价响应、EMC节能效益测量与验证等核心内容。
