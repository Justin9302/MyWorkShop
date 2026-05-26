# 家庭能源管理系统（HEMS）技术方案 v1.0

> **基于OpenEMS架构的家庭能源独立与VPP聚合方案**
> **融合相邻用户自动组网、NILM硬件闭环、可调节负荷优化调度**

---

## 文档信息

| 项目     | 内容                                           |
| -------- | ---------------------------------------------- |
| 文档编号 | HEMS-TECH-2026-001                             |
| 版本号   | v1.0                                           |
| 制定日期 | 2026-05-10                                     |
| 基于框架 | OpenEMS 三层架构 + VPP_EMS 能量路由器标准规范  |
| 核心范式 | 能源交换机（Energy Switch）+ 相邻用户自组网    |
| 适用领域 | 家庭能源管理（HEMS）+ 虚拟电厂（VPP）边缘节点  |
| 目标设备 | 光伏、储能、EV/V2G、空调、热泵、泳池、可控家电 |

---

## 目录

1. [方案概述与设计目标](#1-方案概述与设计目标)
2. [系统架构设计](#2-系统架构设计)
3. [设备接入与协议适配](#3-设备接入与协议适配)
4. [相邻用户发现与自动组网](#4-相邻用户发现与自动组网)
5. [家庭能源独立策略](#5-家庭能源独立策略)
6. [可调节负荷优化调度](#6-可调节负荷优化调度)
7. [VPP聚合与收益模型](#7-vpp聚合与收益模型)
8. [NILM设备与HEMS硬件交互闭环](#8-nilm设备与hems硬件交互闭环)
9. [电网安全运行机制](#9-电网安全运行机制)
10. [硬件参考设计](#10-硬件参考设计)
11. [软件架构与数据流](#11-软件架构与数据流)
12. [实施路线图](#12-实施路线图)
13. [附录](#13-附录)

---

## 1. 方案概述与设计目标

### 1.1 方案背景

随着分布式光伏、户用储能、电动汽车V2G技术的普及，家庭已经从单纯的"电力消费者"转变为"产消者"（Prosumer）。家庭能源管理系统（HEMS）作为连接家庭分布式资源与电网的智能枢纽，是实现家庭能源独立和参与虚拟电厂（VPP）的关键基础设施。

本方案基于OpenEMS三层架构（Edge/Backend/UI），融合VPP_EMS能量路由器标准规范中的"能源交换机"范式，针对家庭场景进行定制化设计，实现：

- **家庭能源独立**：最大化自有光伏消纳，减少电网依赖
- **VPP聚合**：家庭作为分布式资源参与电力市场
- **相邻用户自组网**：社区级能源共享与协同调度
- **NILM硬件闭环**：非侵入式负载监测与HEMS交互

### 1.2 设计目标

| 目标类别     | 具体目标                         | 关键指标                                   |
| ------------ | -------------------------------- | ------------------------------------------ |
| **能源独立** | 家庭电力自给率 ≥ 80%             | 年自给率（PV+储能+EV V2G覆盖家庭用电比例） |
| **经济收益** | 年化综合收益 ≥ 家庭电费支出的30% | 峰谷套利 + 需求响应 + VPP聚合收益          |
| **电网安全** | 并网点功率波动 ≤ ±10%/分钟       | 功率变化率控制，防止对电网冲击             |
| **自组网**   | 相邻用户发现时间 ≤ 5分钟         | 从设备上电到完成邻居发现与组网             |
| **NILM精度** | 设备识别准确率 ≥ 90%             | 典型家庭场景下主要设备识别率               |
| **离线自治** | 断网后持续运行 ≥ 72小时          | 本地控制闭环不依赖云端                     |

### 1.3 覆盖设备清单

| 设备类别       | 具体设备                |     可控性      |   调度优先级   | 通信协议       |
| -------------- | ----------------------- | :-------------: | :------------: | -------------- |
| **光伏**       | 屋顶光伏逆变器          |   限功率/关断   | L1（发电优先） | Modbus/SunSpec |
| **储能**       | 家用储能电池（5-20kWh） |   充放电控制    | L2（灵活调度） | Modbus/CAN     |
| **EV/V2G**     | 电动汽车 + V2G充电桩    |   双向充放电    |  L3（可延时）  | OCPP/ISO 15118 |
| **空调**       | 变频空调（1-3台）       | 温度设定/限功率 |  L3（可延时）  | Modbus/KNX     |
| **热泵热水器** | 空气源热泵热水器        |  加热时段控制   |  L3（可延时）  | Modbus         |
| **泳池系统**   | 泳池过滤泵 + 加热泵     |  运行时段控制   | L4（机会负荷） | Modbus         |
| **可控家电**   | 洗衣机/洗碗机/烘干机    |    启动延时     | L4（机会负荷） | WiFi/MQTT      |
| **基础负荷**   | 照明/冰箱/安防等        | 不可控（监测）  | L1（关键负荷） | 电表监测       |

### 1.4 调度优先级定义（L1-L4）

|  级别  | 名称       | 定义                   | 调度策略           | 典型设备               |
| :----: | ---------- | ---------------------- | ------------------ | ---------------------- |
| **L1** | 关键负荷   | 断电影响安全或造成不便 | 永不减载，优先保障 | 照明、冰箱、安防、网络 |
| **L2** | 可调度资产 | 可灵活充放电的储能设备 | 按优化策略调度     | 储能电池、光伏         |
| **L3** | 可延时负荷 | 可在时间上平移的负荷   | 优先减载/延时      | EV充电、空调、热泵     |
| **L4** | 机会负荷   | 非必要、可随时中断     | 首选切断/延时      | 泳池泵、洗衣机、烘干机 |

---

## 2. 系统架构设计

### 2.1 总体架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          VPP云端聚合平台 (Backend)                           │
│  多家庭聚合调度 | 电力市场接入 | 收益结算 | 全局拓扑管理 | 预测引擎        │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    │               │               │
            ┌───────▼───────┐ ┌───────▼───────┐ ┌───────▼───────┐
            │  家庭HEMS节点A  │ │  家庭HEMS节点B  │ │  家庭HEMS节点C  │
            │  (Edge)       │◄┤  (Edge)       │◄┤  (Edge)       │
            └───────┬───────┘ └───────┬───────┘ └───────┬───────┘
                    │                 │                 │
            ┌───────┴───────┐ ┌───────┴───────┐ ┌───────┴───────┐
            │  家庭能源总线   │ │  家庭能源总线   │ │  家庭能源总线   │
            │  (家庭内网)    │ │  (家庭内网)    │ │  (家庭内网)    │
            └───────┬───────┘ └───────┬───────┘ └───────┬───────┘
                    │                 │                 │
      ┌─────────────┼──────┬──────┐  │  ┌──────┬──────┐ │
      ▼             ▼      ▼      ▼  ▼  ▼      ▼      ▼ ▼
    ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐
    │ PV │ │储能│ │EV  │ │空调│ │热泵│ │泳池│ │家电│ │NILM│
    │    │ │    │ │V2G │ │    │ │    │ │    │ │    │ │    │
    └────┘ └────┘ └────┘ └────┘ └────┘ └────┘ └────┘ └────┘
```

### 2.2 三层架构详解

#### 2.2.1 Edge层（家庭HEMS网关）

部署于家庭内的边缘计算节点，是家庭能源管理的核心：

| 模块             | 功能                                   | 技术要求                    |
| ---------------- | -------------------------------------- | --------------------------- |
| **设备接入引擎** | 多协议设备接入（Modbus/OCPP/MQTT/KNX） | 支持≥20个设备同时接入       |
| **本地控制闭环** | 毫秒级功率平衡控制                     | 控制周期 ≤ 1秒              |
| **NILM引擎**     | 非侵入式负载监测与设备指纹识别         | 1kHz采样，识别延迟≤200ms    |
| **邻居发现模块** | 相邻用户自动发现与组网                 | 电压相关性分析+NILM事件对账 |
| **离线自治引擎** | 断网后独立运行                         | ≥72小时离线运行             |
| **本地预测**     | 光伏出力/负荷超短期预测                | 5分钟粒度，MAE<10%          |
| **安全模块**     | 物理约束校验、孤岛检测                 | 符合IEEE 1547标准           |

#### 2.2.2 Backend层（VPP云端聚合平台）

| 模块             | 功能                         |
| ---------------- | ---------------------------- |
| **多家庭聚合**   | 管理数千个家庭HEMS节点       |
| **全局调度优化** | 基于聚合灵活性的VPP市场参与  |
| **收益结算引擎** | 家庭级收益计算与分成         |
| **拓扑管理**     | 社区级电网拓扑维护           |
| **预测引擎**     | 光伏/负荷/电价预测（24小时） |
| **数据湖**       | 时序数据存储与分析           |

#### 2.2.3 UI层（用户交互界面）

| 终端             | 功能                             |
| ---------------- | -------------------------------- |
| **家庭能源看板** | 实时功率流向、设备状态、收益展示 |
| **移动端App**    | 远程监控、设备控制、告警通知     |
| **社区能源地图** | 邻居能源共享状态、社区自给率     |
| **VPP参与面板**  | 需求响应事件、收益明细、碳足迹   |

### 2.3 数据流架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                        数据流三层闭环                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  闭环一：实时控制环（毫秒级）                                        │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐     │
│  │ 传感器采样 │───→│ 物理约束  │───→│ 控制算法  │───→│ 指令下发  │     │
│  │ (1kHz)   │    │ 校验     │    │ 解算     │    │ (Modbus) │     │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘     │
│                                                                     │
│  闭环二：状态上报环（秒级）                                          │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐     │
│  │ 设备状态  │───→│ 数据聚合  │───→│ MQTT推送  │───→│ 云端存储  │     │
│  │ (1Hz)    │    │ (Edge)   │    │ (WSS)    │    │ (InfluxDB)│     │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘     │
│                                                                     │
│  闭环三：协同路由环（秒~分钟级）                                     │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐     │
│  │ 本地拓扑  │───→│ 邻居节点  │───→│ 带宽配额  │───→│ 路由表    │     │
│  │ 发现     │    │ 握手     │    │ 协商     │    │ 更新     │     │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘     │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. 设备接入与协议适配

### 3.1 设备接入架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                    HEMS 设备接入引擎                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    统一设备抽象层                             │   │
│  │  Device ID | 设备类型 | 额定功率 | 当前状态 | 调度接口      │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                              │                                      │
│        ┌─────────────────────┼─────────────────────┐               │
│        ▼                     ▼                     ▼               │
│  ┌──────────┐         ┌──────────┐         ┌──────────┐           │
│  │ Modbus   │         │  OCPP    │         │  MQTT    │           │
│  │ 适配器   │         │  适配器   │         │  适配器   │           │
│  └──────────┘         └──────────┘         └──────────┘           │
│        │                     │                     │               │
│        ▼                     ▼                     ▼               │
│  ┌──────────┐         ┌──────────┐         ┌──────────┐           │
│  │ RS485/   │         │  TCP/IP  │         │  WiFi/   │           │
│  │ TCP      │         │          │         │  Ethernet│           │
│  └──────────┘         └──────────┘         └──────────┘           │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 各设备接入方案

#### 3.2.1 光伏逆变器接入

| 参数            | 说明                                                             |
| --------------- | ---------------------------------------------------------------- |
| **协议**        | Modbus RTU/TCP + SunSpec标准                                     |
| **数据点**      | 直流功率、交流功率、电压、电流、频率、日发电量、总发电量         |
| **控制点**      | 有功功率限值（百分比）、启停控制                                 |
| **采样频率**    | 1Hz（功率数据），1kHz（波形用于NILM校验）                        |
| **SunSpec模型** | Model 101 (逆变器单相)、Model 103 (逆变器三相)、Model 201 (电表) |

**典型Modbus寄存器映射：**

```yaml
solar_inverter:
  protocol: modbus_tcp
  address: 192.168.1.100:502
  slave_id: 1
  registers:
    - name: total_dc_power
      address: 40001
      type: float32
      scale: 1.0
      unit: W
    - name: total_ac_power
      address: 40003
      type: float32
      scale: 1.0
      unit: W
    - name: grid_voltage
      address: 40005
      type: float32
      scale: 1.0
      unit: V
    - name: grid_frequency
      address: 40007
      type: float32
      scale: 0.01
      unit: Hz
    - name: daily_yield
      address: 40009
      type: float32
      scale: 1.0
      unit: kWh
    - name: power_limit
      address: 41001
      type: uint16
      scale: 1.0
      unit: "%"
      writable: true
```

#### 3.2.2 储能电池接入

| 参数         | 说明                                                  |
| ------------ | ----------------------------------------------------- |
| **协议**     | Modbus RTU/TCP + CAN（BMS直连）                       |
| **数据点**   | SOC、SOE、SOH、充放电功率、电压、电流、循环次数、温度 |
| **控制点**   | 充放电功率设定值、运行模式（充电/放电/待机）          |
| **采样频率** | 1Hz（状态数据），10Hz（功率数据）                     |

**BMS关键数据：**

```yaml
battery_storage:
  protocol: modbus_tcp
  address: 192.168.1.101:502
  slave_id: 2
  registers:
    - name: soc
      address: 40001
      type: uint16
      scale: 0.1
      unit: "%"
    - name: soh
      address: 40002
      type: uint16
      scale: 0.1
      unit: "%"
    - name: total_energy
      address: 40003
      type: float32
      scale: 1.0
      unit: kWh
    - name: charge_power_limit
      address: 40005
      type: float32
      scale: 1.0
      unit: W
    - name: discharge_power_limit
      address: 40007
      type: float32
      scale: 1.0
      unit: W
    - name: battery_voltage
      address: 40009
      type: float32
      scale: 1.0
      unit: V
    - name: battery_current
      address: 40011
      type: float32
      scale: 1.0
      unit: A
    - name: battery_temp
      address: 40013
      type: float32
      scale: 1.0
      unit: "°C"
    - name: cycle_count
      address: 40015
      type: uint32
      scale: 1.0
      unit: "次"
    - name: power_setpoint
      address: 41001
      type: float32
      scale: 1.0
      unit: W
      writable: true
    - name: mode
      address: 41003
      type: uint16
      scale: 1.0
      enum:
        0: STANDBY
        1: CHARGE
        2: DISCHARGE
      writable: true
```

#### 3.2.3 EV/V2G充电桩接入

| 参数         | 说明                                        |
| ------------ | ------------------------------------------- |
| **协议**     | OCPP 1.6J / 2.0.1 + ISO 15118（V2G通信）    |
| **数据点**   | 充电功率、SOC、充电状态、连接状态、累计电量 |
| **控制点**   | 充电功率限值、启停控制、V2G放电功率设定     |
| **采样频率** | 1Hz（功率数据），事件触发（状态变更）       |

**OCPP关键操作：**

```yaml
ev_charger:
  protocol: ocpp_1.6j
  endpoint: ws://192.168.1.102:8080/ocpp
  charge_point_id: "CP-001"

  # 数据上报（MeterValues）
  meter_values:
    - measurand: "Power.Active.Import"
      unit: "W"
      interval_s: 1
    - measurand: "Energy.Active.Import.Register"
      unit: "kWh"
      interval_s: 300
    - measurand: "SoC"
      unit: "%"
      interval_s: 60

  # 控制指令（RemoteStartTransaction / RemoteStopTransaction）
  # 功率限制（SetChargingProfile）
  charging_profile:
    - charging_profile_kind: "Relative"
      stack_level: 1
      charging_schedule:
        charging_rate_unit: "A" # 或 "W"
        charging_schedule_period:
          - start_period: 0
            limit: 32 # 最大电流
```

**V2G扩展（ISO 15118）：**

```yaml
v2g_extension:
  protocol: iso_15118
  # V2G支持的数据交换
  capabilities:
    - bidirectional_charging: true
    - grid_frequency_regulation: true
    - emergency_power_supply: true

  # V2G放电控制
  discharge_control:
    - discharge_power_limit: 7000 # 最大放电功率(W)
    - min_soc: 20 # 最低SOC(%)
    - target_soc: 80 # 目标SOC(%)
```

#### 3.2.4 空调接入

| 参数         | 说明                                                       |
| ------------ | ---------------------------------------------------------- |
| **协议**     | Modbus RTU（商用空调）/ KNX（楼宇自控）/ 红外+WiFi（家用） |
| **数据点**   | 运行状态、温度设定、实际温度、功率、模式                   |
| **控制点**   | 温度设定值、启停、模式切换、功率限值                       |
| **采样频率** | 10秒（状态数据）                                           |

```yaml
air_conditioner:
  protocol: modbus_rtu
  interface: /dev/ttyRS485_1
  baud_rate: 9600
  slave_id: 3

  registers:
    - name: power_status
      address: 40001
      type: uint16
      enum:
        0: OFF
        1: ON
      writable: true

    - name: mode
      address: 40002
      type: uint16
      enum:
        0: AUTO
        1: COOL
        2: HEAT
        3: FAN
        4: DRY
      writable: true

    - name: temp_setpoint
      address: 40003
      type: uint16
      scale: 0.1
      unit: "°C"
      range: [16, 30]
      writable: true

    - name: room_temp
      address: 40004
      type: uint16
      scale: 0.1
      unit: "°C"

    - name: power_consumption
      address: 40005
      type: float32
      scale: 1.0
      unit: W

    - name: power_limit
      address: 41001
      type: uint16
      scale: 1.0
      unit: "%"
      range: [30, 100]
      writable: true
```

#### 3.2.5 热泵热水器接入

| 参数         | 说明                                       |
| ------------ | ------------------------------------------ |
| **协议**     | Modbus RTU                                 |
| **数据点**   | 水温、运行状态、功率、压缩机状态、加热模式 |
| **控制点**   | 温度设定、加热时段、运行模式               |
| **采样频率** | 10秒                                       |

```yaml
heat_pump_water_heater:
  protocol: modbus_rtu
  interface: /dev/ttyRS485_2
  baud_rate: 9600
  slave_id: 4

  registers:
    - name: water_temp
      address: 40001
      type: uint16
      scale: 0.1
      unit: "°C"

    - name: target_temp
      address: 40002
      type: uint16
      scale: 0.1
      unit: "°C"
      range: [40, 65]
      writable: true

    - name: power_status
      address: 40003
      type: uint16
      enum:
        0: OFF
        1: HEATING
        2: STANDBY
      writable: true

    - name: power_consumption
      address: 40004
      type: float32
      scale: 1.0
      unit: W

    - name: compressor_status
      address: 40005
      type: uint16
      enum:
        0: OFF
        1: ON

    - name: heating_schedule
      address: 41001
      type: string
      length: 48 # 24小时×2字节（开关+温度）
      writable: true
```

#### 3.2.6 泳池过滤与加热系统接入

| 参数         | 说明                                   |
| ------------ | -------------------------------------- |
| **协议**     | Modbus RTU / 定时器+功率监测           |
| **数据点**   | 过滤泵功率、加热器功率、水温、运行状态 |
| **控制点**   | 过滤泵启停、加热器启停、运行时段       |
| **采样频率** | 30秒                                   |

```yaml
pool_system:
  protocol: modbus_rtu
  interface: /dev/ttyRS485_2
  baud_rate: 9600
  slave_id: 5

  registers:
    - name: filter_pump_status
      address: 40001
      type: uint16
      enum:
        0: OFF
        1: ON
      writable: true

    - name: filter_pump_power
      address: 40002
      type: float32
      scale: 1.0
      unit: W

    - name: heater_status
      address: 40003
      type: uint16
      enum:
        0: OFF
        1: ON
      writable: true

    - name: heater_power
      address: 40004
      type: float32
      scale: 1.0
      unit: W

    - name: pool_water_temp
      address: 40005
      type: uint16
      scale: 0.1
      unit: "°C"

    - name: target_temp
      address: 40006
      type: uint16
      scale: 0.1
      unit: "°C"
      writable: true

    - name: schedule
      address: 41001
      type: string
      length: 96 # 24小时×4字节（过滤泵+加热器）
      writable: true
```

#### 3.2.7 可控家电接入

| 参数         | 说明                           |
| ------------ | ------------------------------ |
| **协议**     | WiFi + MQTT / Zigbee / HomeKit |
| **数据点**   | 运行状态、功率、剩余时间       |
| **控制点**   | 启停、延时启动、模式选择       |
| **采样频率** | 事件触发                       |

```yaml
smart_appliances:
  protocol: mqtt
  broker: localhost:1883
  topic_prefix: "home/appliances/"

  devices:
    - name: washing_machine
      topic: "washing_machine"
      commands:
        - start_delayed: "home/appliances/washing_machine/cmd"
        - stop: "home/appliances/washing_machine/stop"
      telemetry:
        - status: "home/appliances/washing_machine/status"
        - power: "home/appliances/washing_machine/power"
        - remaining_time: "home/appliances/washing_machine/remaining"

    - name: dishwasher
      topic: "dishwasher"
      commands:
        - start_delayed: "home/appliances/dishwasher/cmd"
        - stop: "home/appliances/dishwasher/stop"
      telemetry:
        - status: "home/appliances/dishwasher/status"
        - power: "home/appliances/dishwasher/power"
        - remaining_time: "home/appliances/dishwasher/remaining"

    - name: dryer
      topic: "dryer"
      commands:
        - start_delayed: "home/appliances/dryer/cmd"
        - stop: "home/appliances/dryer/stop"
      telemetry:
        - status: "home/appliances/dryer/status"
        - power: "home/appliances/dryer/power"
        - remaining_time: "home/appliances/dryer/remaining"
```

### 3.3 统一设备抽象模型

所有设备通过统一抽象层接入HEMS，提供标准化的数据接口和控制接口：

```go
// 统一设备接口定义（Go语言示例）
type Device interface {
    // 基本信息
    GetID() string
    GetType() DeviceType
    GetPriority() PriorityTag

    // 数据接口
    GetTelemetry() (*Telemetry, error)
    SubscribeTelemetry(handler func(*Telemetry)) (cancel func())

    // 控制接口
    SetPowerLimit(watts float64) error
    SetOnOff(on bool) error
    GetCapabilities() []Capability

    // 状态管理
    GetStatus() DeviceStatus
    IsOnline() bool
}

// 设备类型枚举
type DeviceType int
const (
    DevicePV        DeviceType = iota // 光伏
    DeviceBattery                     // 储能
    DeviceEVCharger                   // EV充电桩
    DeviceV2G                         // V2G
    DeviceHVAC                        // 空调
    DeviceHeatPump                    // 热泵
    DevicePool                        // 泳池系统
    DeviceAppliance                   // 家电
    DeviceNILM                        // NILM监测
)

// 遥测数据结构
type Telemetry struct {
    Timestamp     int64   // Unix毫秒时间戳
    ActivePower   float64 // 有功功率 (W)
    ReactivePower float64 // 无功功率 (VAR)
    Voltage       float64 // 电压 (V)
    Current       float64 // 电流 (A)
    PowerFactor   float64 // 功率因数
    Frequency     float64 // 频率 (Hz)
    SOC           float64 // 荷电状态 (%) - 仅储能/EV
    Temperature   float64 // 温度 (°C)
    StatusCode    int     // 状态码
    FaultCode     int     // 故障码
}
```

---

## 4. 相邻用户发现与自动组网

### 4.1 组网架构

```
                    ┌─────────────────────────────────────┐
                    │        社区能源网络（VPP微网）        │
                    │                                     │
                    │  ┌──────────┐    ┌──────────┐      │
                    │  │ 家庭A    │◄──►│ 家庭B    │      │
                    │  │ HEMS节点 │    │ HEMS节点 │      │
                    │  └────┬─────┘    └────┬─────┘      │
                    │       │               │            │
                    │  ┌────▼─────┐    ┌────▼─────┐      │
                    │  │ 家庭C    │◄──►│ 家庭D    │      │
                    │  │ HEMS节点 │    │ HEMS节点 │      │
                    │  └──────────┘    └──────────┘      │
                    │                                     │
                    │  台区变压器：社区总容量               │
                    └─────────────────────────────────────┘
```

### 4.2 三种互补的拓扑发现机制

#### 4.2.1 电压相关性分析

**原理**：物理位置越近的家庭，其电网接入点的电压波动相关性越高。

```
算法流程：
1. 每个HEMS节点持续记录本地电压（1秒分辨率）
2. 每5分钟生成电压波动指纹（过去5分钟的ΔV曲线）
3. 通过局域网组播广播电压指纹
4. 接收邻居节点的电压指纹
5. 计算互相关性系数 ρ
6. 如果 ρ > 0.85：判定为物理邻近节点
7. 更新本地邻居表
```

**电压指纹格式：**

```json
{
  "method": "voltageFingerprint",
  "params": {
    "node_id": "HEMS-A001",
    "timestamp": 1715218372000,
    "window_s": 300,
    "resolution_s": 1,
    "delta_v_samples": [0.1, 0.2, -0.1, 0.3, ...],  // 300个ΔV值
    "base_voltage_v": 230.5,
    "topology_version": 15
  }
}
```

**相关性计算：**

```python
import numpy as np

def calculate_voltage_correlation(fingerprint_a, fingerprint_b):
    """
    计算两个节点的电压波动相关性
    返回相关系数 ρ ∈ [-1, 1]
    """
    va = np.array(fingerprint_a['delta_v_samples'])
    vb = np.array(fingerprint_b['delta_v_samples'])

    # Pearson相关系数
    correlation = np.corrcoef(va, vb)[0, 1]

    return correlation

def is_physically_near(correlation, threshold=0.85):
    """
    判断是否物理邻近
    """
    return correlation > threshold
```

#### 4.2.2 NILM事件对账

**原理**：当某个家庭内有大功率设备启停时，会在同一台区下的其他家庭电网中产生可检测的电压/电流扰动。通过比对事件时间戳和特征，确认物理连接关系。

```
流程：
1. 节点A检测到本地大功率设备启动事件（如EV充电开始）
2. 记录事件时间戳、功率变化量、谐波特征
3. 通过协同通道广播事件通知
4. 节点B接收到通知后，比对本地观测到的扰动
5. 如果时间戳偏差 < 100ms 且特征匹配：
   a. 确认A和B处于同一条低压支路
   b. 记录电气距离（基于扰动衰减程度）
```

**NILM事件对账报文：**

```json
{
  "method": "nilmEventMatch",
  "params": {
    "source_node": "HEMS-A001",
    "event_id": "nilm-ev-20260509-001",
    "event_type": "EV_CHARGE_START",
    "timestamp": 1715218372000,
    "power_delta_w": 7000,
    "harmonic_signature": [3.2, 1.1, 0.5, 0.3],
    "confidence": 0.95
  }
}
```

#### 4.2.3 电力载波RSSI（可选扩展）

**原理**：通过电力线注入低频识别信号，测量信号强度推算电气距离。

```
适用场景：
- 电压相关性分析无法区分近距离节点时
- 需要更精确的电气距离测量时

实现方式：
1. HEMS节点在电力线上注入特定频率的识别信号（< 1kHz）
2. 邻居节点测量接收信号强度（RSSI）
3. 根据信号衰减模型推算电气距离
4. 更新邻居表中的距离信息
```

### 4.3 邻居发现协议

#### 4.3.1 发现流程

```
节点上电 → 监听组播频道（5秒）
    │
    ├── 收到邻居心跳 → 记录邻居信息
    │
    └── 未收到邻居心跳 → 主动广播发现请求
            │
            ▼
    等待响应（超时3秒）
            │
            ├── 收到响应 → 建立邻居关系
            │
            └── 超时 → 标记为孤立节点，等待云端同步
```

**发现请求：**

```json
{
  "method": "neighborDiscovery",
  "params": {
    "node_id": "HEMS-A001",
    "ip_address": "192.168.1.200",
    "port": 8080,
    "capabilities": ["VOLTAGE_FINGERPRINT", "NILM_EVENT", "BANDWIDTH_LOAN"],
    "topology_version": 15
  }
}
```

**发现响应：**

```json
{
  "method": "neighborDiscoveryResponse",
  "params": {
    "node_id": "HEMS-B002",
    "ip_address": "192.168.1.201",
    "port": 8080,
    "capabilities": ["VOLTAGE_FINGERPRINT", "NILM_EVENT", "BANDWIDTH_LOAN"],
    "topology_version": 15,
    "voltage_correlation": 0.92,
    "electrical_distance": 0.15
  }
}
```

### 4.4 邻居表维护

每个HEMS节点维护本地邻居表，记录所有已发现的邻居信息：

```go
// 邻居表结构
type NeighborTable struct {
    mu        sync.RWMutex
    neighbors map[string]*NeighborInfo
    self      *NodeInfo
}

type NeighborInfo struct {
    NodeID            string    // 邻居节点ID
    IPAddress         string    // IP地址
    Port              int       // 通信端口
    VoltageCorr       float64   // 电压相关系数
    ElectricalDist    float64   // 电气距离 (0-1)
    LastSeen          int64     // 最后心跳时间
    TopologyVersion   uint32    // 拓扑版本号
    CreditWeight      float64   // 信用权重
    AvailableQuota    float64   // 可用带宽配额 (W)
    IsOnline          bool      // 是否在线
    Capabilities      []string  // 能力集
}

// 邻居表更新
func (nt *NeighborTable) UpdateNeighbor(info *NeighborInfo) {
    nt.mu.Lock()
    defer nt.mu.Unlock()
    nt.neighbors[info.NodeID] = info
}

// 邻居心跳超时检测（每30秒执行）
func (nt *NeighborTable) CheckHeartbeat() {
    now := time.Now().UnixMilli()
    for id, neighbor := range nt.neighbors {
        if now - neighbor.LastSeen > 90000 { // 3次心跳未收到
            neighbor.IsOnline = false
            // 触发重发现流程
        }
    }
}
```

### 4.5 社区级协同调度

#### 4.5.1 带宽配额协商

邻居节点间定期交换带宽使用状态，实现社区级功率平衡：

```json
{
  "method": "declareBandwidth",
  "params": {
    "node_id": "HEMS-A001",
    "timestamp": 1715218372000,
    "transformer_rated_va": 315000,
    "current_load_va": 8500,
    "pv_generation_w": 5200,
    "battery_soc": 65,
    "battery_available_w": 3000,
    "ev_available_w": 7000,
    "critical_load_w": 1500,
    "available_quota_w": 12000,
    "credit_weight": 0.92,
    "topology_version": 15
  }
}
```

#### 4.5.2 社区能源共享

当某家庭光伏过剩而邻居需要用电时，通过社区能源共享机制实现点对点交易：

```
场景：家庭A光伏过剩（5kW），家庭B需要充电（3kW）

流程：
1. 家庭A HEMS检测到光伏过剩（储能已满）
2. 广播"多余电量"通知到社区网络
3. 家庭B HEMS检测到需要充电
4. 双方通过协商确定交易价格（基于社区内部电价）
5. 家庭A增加并网功率，家庭B增加用电功率
6. 台区变压器层面实现净功率平衡
7. 交易记录上链存证
```

**社区能源共享报文：**

```json
{
  "method": "energyShareOffer",
  "params": {
    "source_node": "HEMS-A001",
    "offer_id": "offer-20260509-001",
    "available_energy_wh": 5000,
    "time_window_start": 1715218372000,
    "time_window_end": 1715221972000,
    "price_per_kwh": 0.35,
    "energy_type": "PV_GREEN"
  }
}
```

#### 4.5.3 社区级需求响应

当台区变压器接近容量上限时，社区内所有HEMS节点协同响应：

```
触发条件：社区总功率 > 变压器额定容量 × 90%

协同响应流程：
1. 根节点（社区主HEMS）广播减载请求
2. 各家庭HEMS评估可减载容量
3. 按减载成本从低到高排序
4. 选择最优组合满足减载需求
5. 各家庭执行本地减载
6. 验证减载效果
7. 记录协同减载SOE
```

---

## 5. 家庭能源独立策略

### 5.1 核心原则

家庭能源独立的核心是"最大化自有能源利用，最小化电网依赖"，遵循以下优先级：

```
第1优先：光伏发电 → 直接供给家庭负荷
第2优先：光伏余电 → 给储能电池充电
第3优先：光伏余电 → 给EV充电（V2G模式）
第4优先：储能放电 → 供给家庭负荷（光伏不足时）
第5优先：EV V2G放电 → 供给家庭负荷（储能不足时）
第6优先：电网购电 → 补充不足部分
第7优先：光伏余电 → 社区共享/并网卖电
```

### 5.2 运行模式

#### 5.2.1 自发自用模式（默认模式）

**目标**：最大化光伏就地消纳，减少向电网购电。

```
每个控制周期（1秒）：
  1. 读取光伏出力 P_pv、家庭负荷 P_load、储能SOC
  2. 计算净功率 P_net = P_pv - P_load

  3. 如果 P_net > 0（光伏有余）：
     a. 如果 SOC < 95%：储能充电，功率 = min(P_net, 储能最大充电功率)
     b. 如果 SOC ≥ 95% 且 EV已连接：EV充电，功率 = min(P_net, EV最大充电功率)
     c. 如果仍有剩余：并网馈电

  4. 如果 P_net < 0（光伏不足）：
     a. 如果 SOC > 20%：储能放电，功率 = min(|P_net|, 储能最大放电功率)
     b. 如果 SOC ≤ 20% 且 EV已连接且支持V2G：EV放电，功率 = min(|P_net|, EV最大放电功率)
     c. 如果仍不足：从电网购电
```

#### 5.2.2 峰谷套利模式

**目标**：利用分时电价差异，低电价时充电、高电价时放电，获取价差收益。

```
每个控制周期（1秒）：
  1. 获取当前电价 price_now 和未来24小时电价曲线
  2. 获取光伏预测和负荷预测

  3. 如果 price_now < price_low_threshold（低价时段）：
     a. 如果 SOC < 95%：以最大功率给储能充电
     b. 如果 EV已连接：启动EV充电
     c. 预冷/预热空调（利用建筑热惯性）
     d. 启动热泵热水器加热

  4. 如果 price_now > price_high_threshold（高价时段）：
     a. 如果 SOC > 20%：储能放电供给家庭负荷
     b. 如果 EV已连接且支持V2G：EV放电
     c. 限制L3/L4设备用电
     d. 空调温度偏移（夏季+2°C，冬季-2°C）

  5. 如果 price_now 在中间区间：
     a. 按自发自用模式运行
```

#### 5.2.3 离网/孤岛模式

**目标**：电网断电时，利用光伏+储能+EV V2G维持家庭关键负荷运行。

```
触发条件：电网断电检测（电压<180V或频率<47.5Hz持续200ms）

孤岛运行策略：
  1. 立即断开并网开关（<200ms）
  2. 切换至孤岛模式
  3. 仅保障L1关键负荷（照明、冰箱、安防、网络）
  4. 光伏优先供给关键负荷
  5. 储能作为主电源，维持电压和频率
  6. EV V2G作为备用电源（储能SOC<30%时启动）
  7. 非关键负荷（L3/L4）全部切断
  8. 每5分钟检测电网是否恢复
  9. 电网恢复后，同步并网（需满足IEEE 1547要求）
```

### 5.3 日前优化调度

基于预测数据，HEMS在每日0点生成次日最优调度计划：

```python
def optimize_daily_schedule(pv_forecast, load_forecast, price_forecast,
                            battery_params, ev_params, hvac_params):
    """
    日前优化调度
    输出：次日各时段设备调度计划（15分钟粒度）
    """
    # 优化变量
    # - 储能充放电功率 (96个时段)
    # - EV充放电功率 (96个时段)
    # - 空调温度设定 (96个时段)
    # - 热泵加热时段 (96个时段)
    # - 泳池泵运行时段 (96个时段)
    # - 可控家电启动时间

    # 约束条件
    # - 功率平衡：P_pv + P_bat + P_grid + P_ev = P_load
    # - 储能SOC范围：20% ≤ SOC ≤ 95%
    # - EV离网时SOC ≥ 用户设定值
    # - 室内温度舒适范围
    # - 热水温度范围

    # 优化目标（可配置权重）
    # - 最小化电费支出
    # - 最大化光伏消纳
    # - 最小化碳排放
    # - 最小化设备折旧

    # 使用混合整数线性规划（MILP）求解
    schedule = solve_milp(
        objective="min_cost",
        variables=[P_bat, P_ev, T_ac, schedule_hp, schedule_pool, schedule_appliances],
        constraints=[power_balance, soc_range, comfort_temp, ...],
        horizon=96  # 24小时 × 4个15分钟时段
    )

    return schedule
```

### 5.4 动态电价响应机制

HEMS具备完整的动态电价响应能力，支持多种零售电价模式，包括分时电价（TOU）、实时电价（RTP）、尖峰电价（CPP）和需求侧竞价（DSB）。

#### 5.4.1 支持的动态电价模式

| 电价模式              | 说明                            |           更新频率           | 数据来源     | 响应策略                |
| --------------------- | ------------------------------- | :--------------------------: | ------------ | ----------------------- |
| **分时电价（TOU）**   | 固定峰/谷/平三段式电价          |        每日/季度更新         | 零售商公布   | 日前优化 + 日内执行     |
| **实时电价（RTP）**   | 每5-30分钟更新的现货市场价格    |           5-30分钟           | AEMO/API接口 | 实时跟踪 + 预测修正     |
| **尖峰电价（CPP）**   | 极端天气/电网紧张时触发的高电价 | 事件触发（提前4-24小时通知） | 零售商通知   | 预冷/预热 + 储能放电    |
| **需求侧竞价（DSB）** | 用户主动报价削减负荷            |           事件触发           | VPP平台      | 用户设定底价 + 自动竞价 |

#### 5.4.2 动态电价数据获取

HEMS通过以下方式获取动态电价数据：

```python
class DynamicPriceClient:
    """
    动态电价数据获取客户端
    支持多种数据源接入
    """
    def __init__(self):
        self.price_sources = {}
        self.current_price = 0.0
        self.price_curve = []  # 未来24小时电价曲线
        self.last_update = 0

    def register_source(self, name, source_type, config):
        """
        注册电价数据源
        source_type: "RETAILER_API" | "AEMO" | "VPP_PLATFORM" | "MANUAL"
        """
        self.price_sources[name] = {
            "type": source_type,
            "config": config,
            "last_success": 0
        }

    def fetch_current_price(self):
        """
        获取当前实时电价
        支持多种数据源自动切换
        """
        for name, source in self.price_sources.items():
            try:
                if source["type"] == "RETAILER_API":
                    price = self._fetch_retailer_api(source["config"])
                elif source["type"] == "AEMO":
                    price = self._fetch_aemo_price(source["config"])
                elif source["type"] == "VPP_PLATFORM":
                    price = self._fetch_vpp_price(source["config"])
                else:
                    continue

                self.current_price = price
                self.last_update = time.time()
                source["last_success"] = time.time()
                return price
            except Exception as e:
                print(f"Source {name} failed: {e}")
                continue

        # 所有数据源失败，使用最后一次有效价格
        return self.current_price

    def fetch_price_forecast(self, hours_ahead=24):
        """
        获取未来电价预测曲线
        用于日前优化和日内滚动修正
        """
        # 优先使用零售商API提供的预测
        for name, source in self.price_sources.items():
            if source["type"] == "RETAILER_API":
                try:
                    forecast = self._fetch_retailer_forecast(
                        source["config"], hours_ahead
                    )
                    self.price_curve = forecast
                    return forecast
                except:
                    continue

        # 回退到基于历史数据的预测
        return self._predict_price_from_history(hours_ahead)

    def _fetch_retailer_api(self, config):
        """
        从零售商API获取实时电价
        示例：AGL/Origin/EnergyAustralia等零售商的公开API
        """
        api_url = config.get("api_url")
        api_key = config.get("api_key")

        # 实际实现中调用零售商的REST API
        # 例如：GET https://api.retailer.com/v1/pricing/current
        response = requests.get(
            api_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=5
        )
        data = response.json()

        # 解析响应（不同零售商格式不同）
        return data.get("current_price", 0.0)

    def _fetch_aemo_price(self, config):
        """
        从AEMO（澳大利亚能源市场运营商）获取现货价格
        适用于参与现货市场的用户
        """
        # AEMO提供5分钟粒度的区域参考价格（RRP）
        # 通过AEMO API或第三方数据服务获取
        region = config.get("region", "NSW1")
        # 实际实现...
        return 0.0

    def _predict_price_from_history(self, hours_ahead):
        """
        基于历史电价数据预测未来电价
        当API不可用时的回退方案
        """
        now = time.time()
        forecast = []

        for hour in range(hours_ahead):
            # 基于相似日匹配
            predicted_price = self._similar_day_price(now + hour * 3600)
            forecast.append({
                "timestamp": now + hour * 3600,
                "price": predicted_price
            })

        return forecast
```

#### 5.4.3 动态电价响应算法

```python
class DynamicPriceResponder:
    """
    动态电价响应引擎
    根据实时电价和预测电价，动态调整家庭能源调度策略
    """
    def __init__(self, price_client, battery, ev, hvac, heat_pump):
        self.price = price_client
        self.battery = battery
        self.ev = ev
        self.hvac = hvac
        self.heat_pump = heat_pump

        # 可配置参数
        self.price_thresholds = {
            "buy_low": 0.25,    # 低价买入阈值 (元/kWh)
            "sell_high": 0.60,  # 高价卖出阈值 (元/kWh)
            "critical": 1.00,   # 尖峰电价阈值 (元/kWh)
        }

        # 用户偏好
        self.user_preferences = {
            "min_comfort_temp": 24,  # 最低舒适温度
            "max_comfort_temp": 28,  # 最高舒适温度
            "min_hot_water_temp": 40,  # 最低热水温度
            "ev_min_soc": 60,  # EV离网最低SOC
        }

    def respond_to_current_price(self, current_price, pv_power, load_power):
        """
        对当前电价做出实时响应（1秒周期执行）
        """
        # 1. 判断当前电价区间
        price_level = self._classify_price(current_price)

        # 2. 根据电价区间执行对应策略
        if price_level == "CRITICAL":
            return self._critical_price_response(current_price)
        elif price_level == "HIGH":
            return self._high_price_response(current_price)
        elif price_level == "LOW":
            return self._low_price_response(current_price, pv_power)
        else:  # NORMAL
            return self._normal_price_response(pv_power, load_power)

    def _classify_price(self, price):
        """电价分类"""
        if price >= self.price_thresholds["critical"]:
            return "CRITICAL"
        elif price >= self.price_thresholds["sell_high"]:
            return "HIGH"
        elif price <= self.price_thresholds["buy_low"]:
            return "LOW"
        else:
            return "NORMAL"

    def _critical_price_response(self, price):
        """
        尖峰电价响应（极端高价）
        目标：最大化放电，最小化购电
        """
        actions = []

        # 1. 储能全力放电（直到SOC下限）
        if self.battery.soc > self.battery.min_soc:
            discharge = self.battery.max_discharge
            actions.append(("battery", "discharge", discharge))

        # 2. EV V2G放电（如果已连接且SOC充足）
        if self.ev.is_connected and self.ev.soc > self.user_preferences["ev_min_soc"] + 20:
            v2g_power = min(
                self.ev.max_discharge,
                (self.ev.soc - self.user_preferences["ev_min_soc"]) / 100 * self.ev.capacity * 1000
            )
            actions.append(("ev_v2g", "discharge", v2g_power))

        # 3. 空调温度偏移（夏季+3°C，冬季-3°C）
        actions.append(("hvac", "temp_offset", 3.0))

        # 4. 热泵停止加热
        actions.append(("heat_pump", "stop", 0))

        # 5. 切断所有L4设备
        actions.append(("pool", "stop", 0))
        actions.append(("appliances", "delay_all", 0))

        return actions

    def _high_price_response(self, price):
        """
        高电价响应
        目标：减少购电，利用储能放电
        """
        actions = []

        # 1. 储能放电（按需）
        if self.battery.soc > self.battery.min_soc + 10:
            discharge = min(self.battery.max_discharge * 0.7, self.battery.max_discharge)
            actions.append(("battery", "discharge", discharge))

        # 2. 空调温度偏移（夏季+1°C，冬季-1°C）
        actions.append(("hvac", "temp_offset", 1.0))

        # 3. 热泵延时加热
        if self.heat_pump.can_delay(hours=2):
            actions.append(("heat_pump", "delay", 2))

        # 4. 限制EV充电功率
        if self.ev.is_charging:
            actions.append(("ev", "limit_power", self.ev.rated_power * 0.5))

        return actions

    def _low_price_response(self, price, pv_power):
        """
        低电价响应
        目标：最大化充电，预冷/预热
        """
        actions = []

        # 1. 储能全力充电
        if self.battery.soc < self.battery.max_soc:
            charge = self.battery.max_charge
            actions.append(("battery", "charge", charge))

        # 2. EV充电（如果已连接）
        if self.ev.is_connected and self.ev.soc < 100:
            actions.append(("ev", "charge", self.ev.max_charge))

        # 3. 空调预冷/预热
        actions.append(("hvac", "pre_condition", 0))

        # 4. 热泵加热
        if self.heat_pump.water_temp < self.heat_pump.max_temp:
            actions.append(("heat_pump", "heat", self.heat_pump.rated_power))

        # 5. 启动泳池泵和加热器
        actions.append(("pool", "start", 0))

        # 6. 启动延时家电
        actions.append(("appliances", "start_available", 0))

        return actions

    def _normal_price_response(self, pv_power, load_power):
        """
        正常电价响应
        按自发自用模式运行
        """
        # 回退到自发自用模式
        return self._self_consumption_mode(pv_power, load_power)
```

#### 5.4.4 电价预测与日前优化集成

HEMS将电价预测作为日前优化的重要输入：

```python
def optimize_with_dynamic_price(pv_forecast, load_forecast, price_forecast,
                                battery_params, ev_params, hvac_params):
    """
    基于动态电价的日前优化调度
    电价预测作为核心输入，影响所有设备的调度决策
    """
    # 电价信号处理
    price_signal = analyze_price_signal(price_forecast)

    # 识别关键电价时段
    critical_periods = price_signal["critical_periods"]  # 尖峰电价时段
    low_price_periods = price_signal["low_price_periods"]  # 低价时段
    high_price_periods = price_signal["high_price_periods"]  # 高价时段

    # 优化策略
    schedule = {}

    # 1. 储能调度：低充高放
    schedule["battery"] = optimize_battery_with_price(
        price_forecast, battery_params,
        charge_periods=low_price_periods,
        discharge_periods=high_price_periods + critical_periods
    )

    # 2. EV充电调度：安排在低价时段
    schedule["ev"] = optimize_ev_charging(
        price_forecast, ev_params,
        preferred_periods=low_price_periods
    )

    # 3. 空调预冷/预热：在低价时段提前调节
    schedule["hvac"] = optimize_hvac_with_price(
        price_forecast, hvac_params,
        pre_cool_periods=low_price_periods,
        shed_periods=high_price_periods + critical_periods
    )

    # 4. 热泵加热：安排在低价或光伏高峰时段
    schedule["heat_pump"] = optimize_heat_pump_with_price(
        price_forecast, pv_forecast,
        preferred_periods=low_price_periods
    )

    # 5. 机会负荷：安排在低价时段
    schedule["pool"] = schedule_opportunity_load(
        price_forecast, pv_forecast,
        preferred_periods=low_price_periods
    )

    # 6. 可控家电：安排在低价时段
    schedule["appliances"] = schedule_appliances_with_price(
        price_forecast,
        preferred_periods=low_price_periods
    )

    return schedule


def analyze_price_signal(price_forecast):
    """
    分析电价信号，识别关键时段
    """
    prices = [p["price"] for p in price_forecast]
    mean_price = np.mean(prices)
    std_price = np.std(prices)

    # 识别尖峰电价时段（超过均值+2倍标准差）
    critical_threshold = mean_price + 2 * std_price
    critical_periods = [
        p for p in price_forecast
        if p["price"] >= critical_threshold
    ]

    # 识别低价时段（低于均值-1倍标准差）
    low_threshold = mean_price - std_price
    low_price_periods = [
        p for p in price_forecast
        if p["price"] <= low_threshold
    ]

    # 识别高价时段（高于均值+1倍标准差，但未到尖峰）
    high_threshold = mean_price + std_price
    high_price_periods = [
        p for p in price_forecast
        if high_threshold <= p["price"] < critical_threshold
    ]

    return {
        "critical_periods": critical_periods,
        "low_price_periods": low_price_periods,
        "high_price_periods": high_price_periods,
        "mean_price": mean_price,
        "std_price": std_price
    }
```

#### 5.4.5 零售商API集成示例

```yaml
# 动态电价数据源配置示例
dynamic_pricing:
  # 数据源1：零售商API（主数据源）
  sources:
    - name: "retailer_agl"
      type: "RETAILER_API"
      config:
        api_url: "https://api.agl.com.au/v1/pricing/dynamic"
        api_key: "${AGL_API_KEY}"
        plan_type: "AGL_Real_Time" # 实时电价套餐
        region: "NSW"
      fallback_priority: 1

    # 数据源2：AEMO现货价格（备用）
    - name: "aemo_spot"
      type: "AEMO"
      config:
        region: "NSW1"
        api_url: "https://api.aemo.com.au/v1/spot-prices"
      fallback_priority: 2

    # 数据源3：VPP平台（备用）
    - name: "vpp_platform"
      type: "VPP_PLATFORM"
      config:
        api_url: "https://vpp.energy.com/v1/pricing"
        api_key: "${VPP_API_KEY}"
      fallback_priority: 3

  # 电价阈值配置
  thresholds:
    buy_low: 0.25 # 低价买入阈值 (元/kWh)
    sell_high: 0.60 # 高价卖出阈值 (元/kWh)
    critical: 1.00 # 尖峰电价阈值 (元/kWh)

  # 用户偏好
  user_preferences:
    comfort_temp_range: [24, 28] # 舒适温度范围
    min_hot_water_temp: 40 # 最低热水温度
    ev_min_soc: 60 # EV离网最低SOC
    max_price_response: "AGGRESSIVE" # 响应策略: CONSERVATIVE/MODERATE/AGGRESSIVE
```

#### 5.4.6 动态电价响应场景示例

```
场景1：实时电价从0.35元/kWh突然跳升至0.85元/kWh（电网紧张信号）

HEMS响应（1秒内）：
  1. 检测到电价跳升 → 触发高电价响应模式
  2. 储能从充电切换为放电（5kW → -3kW）
  3. EV充电暂停（7kW → 0kW）
  4. 空调温度从26°C偏移至27°C（削减1.2kW）
  5. 热泵停止加热（削减2.5kW）
  6. 泳池泵停止（削减1.5kW）
  7. 总削减：7.2kW
  8. 并网功率从+5kW（购电）变为-2.2kW（馈电）


场景2：实时电价从0.35元/kWh下降至0.18元/kWh（光伏出力高峰）

HEMS响应（1秒内）：
  1. 检测到电价下降 → 触发低电价响应模式
  2. 储能开始充电（0kW → 5kW）
  3. EV开始充电（0kW → 7kW）
  4. 空调预冷（26°C → 24°C，增加1.5kW）
  5. 热泵启动加热（增加2.5kW）
  6. 泳池泵启动（增加1.5kW）
  7. 总增加：17.5kW
  8. 并网功率从-3kW（馈电）变为+14.5kW（购电）


场景3：收到尖峰电价事件通知（明天14:00-16:00，电价1.20元/kWh）

HEMS日前优化：
  1. 在尖峰时段前（12:00-14:00）：
     - 储能充满至95% SOC
     - 空调预冷至24°C
     - 热泵加热至65°C
  2. 在尖峰时段（14:00-16:00）：
     - 储能全力放电（5kW）
     - EV V2G放电（7kW，SOC从80%降至60%）
     - 空调温度偏移至28°C
     - 所有非关键负荷切断
  3. 尖峰时段后（16:00-18:00）：
     - 恢复正常运行
     - 储能和EV在低价时段补充
```

### 5.5 日内滚动修正

实际运行中，HEMS每15分钟根据实时数据修正调度计划：

```
每15分钟执行：
  1. 读取实际光伏出力 vs 预测偏差
  2. 读取实际负荷 vs 预测偏差
  3. 读取实时电价 vs 预测偏差
  4. 更新储能SOC实际值
  5. 重新优化未来4小时调度计划（16个15分钟时段）
  6. 下发修正后的设备控制指令
```

### 5.5 家庭能源独立关键指标

| 指标             | 计算公式                                     | 目标值 |
| ---------------- | -------------------------------------------- | :----: |
| **自给率**       | (1 - 电网购电量 / 总用电量) × 100%           | ≥ 80%  |
| **自消纳率**     | 自发自用电量 / 光伏总发电量 × 100%           | ≥ 60%  |
| **峰值负荷削减** | (原始峰值 - 优化后峰值) / 原始峰值 × 100%    | ≥ 30%  |
| **能源成本节约** | (原始电费 - 优化后电费) / 原始电费 × 100%    | ≥ 30%  |
| **VPP参与率**    | 参与需求响应次数 / 总需求响应事件次数 × 100% | ≥ 90%  |

---

## 6. 可调节负荷优化调度

### 6.1 可调节负荷分类

| 类别       | 设备          | 调节方式       |   响应时间    | 调节容量 |       舒适度影响       |
| ---------- | ------------- | -------------- | :-----------: | :------: | :--------------------: |
| **储能类** | 储能电池      | 充放电功率调节 |     <1秒      |  5-20kW  |           无           |
| **V2G类**  | EV V2G        | 双向充放电     |     <5秒      |  7-22kW  |  低（需保证离网SOC）   |
| **温控类** | 空调          | 温度设定偏移   |   5-15分钟    |  1-5kW   |    中（±2°C可接受）    |
| **储热类** | 热泵热水器    | 加热时段平移   |   10-30分钟   |  2-5kW   | 低（水温范围40-65°C）  |
| **间歇类** | 泳池泵        | 运行时段平移   | 可延时1-4小时 |  1-3kW   |           低           |
| **延时类** | 洗衣机/烘干机 | 启动延时       | 可延时1-8小时 |  2-4kW   | 低（用户设定完成时间） |

### 6.2 柔性调节策略

#### 6.2.1 储能电池调度

```python
class BatteryScheduler:
    """
    储能电池调度器
    """
    def __init__(self, capacity_kwh=10, max_charge_kw=5, max_discharge_kw=5,
                 min_soc=20, max_soc=95, efficiency=0.95):
        self.capacity = capacity_kwh
        self.max_charge = max_charge_kw
        self.max_discharge = max_discharge_kw
        self.min_soc = min_soc
        self.max_soc = max_soc
        self.efficiency = efficiency
        self.soc = 50  # 初始SOC

    def dispatch(self, price, pv_surplus, load_deficit, mode="SELF_CONSUMPTION"):
        """
        根据当前状态和模式，计算最优充放电功率
        返回：功率（正=放电，负=充电）
        """
        if mode == "SELF_CONSUMPTION":
            return self._self_consumption_dispatch(pv_surplus, load_deficit)
        elif mode == "PEAK_VALLEY":
            return self._peak_valley_dispatch(price)
        elif mode == "VPP_FOLLOW":
            return self._vpp_follow_dispatch()

    def _self_consumption_dispatch(self, pv_surplus, load_deficit):
        """自发自用模式"""
        if pv_surplus > 0 and self.soc < self.max_soc:
            # 光伏有余，充电
            charge_power = min(pv_surplus, self.max_charge)
            return -charge_power  # 负值=充电
        elif load_deficit > 0 and self.soc > self.min_soc:
            # 光伏不足，放电
            discharge_power = min(load_deficit, self.max_discharge)
            return discharge_power  # 正值=放电
        return 0

    def _peak_valley_dispatch(self, price):
        """峰谷套利模式"""
        if price < 0.3:  # 低价时段
            charge_power = self.max_charge
            return -charge_power
        elif price > 0.8:  # 高价时段
            discharge_power = self.max_discharge
            return discharge_power
        return 0

    def update_soc(self, power_w, interval_s=1):
        """更新SOC"""
        energy_change = power_w * interval_s / 3600 / 1000  # kWh
        if power_w < 0:  # 充电
            energy_change *= self.efficiency
        else:  # 放电
            energy_change /= self.efficiency
        self.soc += energy_change / self.capacity * 100
        self.soc = max(self.min_soc, min(self.max_soc, self.soc))
```

#### 6.2.2 空调柔性调度

利用建筑热惯性和人体舒适度范围，实现空调负荷的柔性调节：

```python
class HVACOptimizer:
    """
    空调柔性调度优化器
    利用建筑热惯性，在保证舒适度的前提下平移负荷
    """
    def __init__(self, room_capacity=100, thermal_resistance=0.5,
                 rated_power=3.5, cop=3.5):
        self.room_capacity = room_capacity  # 房间热容量 (kWh/°C)
        self.thermal_resistance = thermal_resistance  # 热阻 (°C/kW)
        self.rated_power = rated_power  # 额定功率 (kW)
        self.cop = cop  # 能效比
        self.room_temp = 26  # 当前室温
        self.comfort_range = (24, 28)  # 舒适温度范围

    def pre_cool(self, outdoor_temp, target_temp=24):
        """
        预冷策略：在低价时段提前降温
        """
        cooling_power = self.rated_power
        cooling_effect = cooling_power * self.cop  # 制冷效果 (kW)

        # 计算预冷时间
        temp_diff = self.room_temp - target_temp
        if temp_diff > 0:
            required_energy = temp_diff * self.room_capacity  # kWh
            pre_cool_time = required_energy / cooling_effect  # 小时
            return pre_cool_time, cooling_power
        return 0, 0

    def temperature_offset(self, offset_c, outdoor_temp):
        """
        温度偏移控制：在高峰时段适度偏移温度
        offset_c: 正=升温（夏季），负=降温（冬季）
        """
        if offset_c > 0:  # 夏季升温
            new_target = min(self.room_temp + offset_c, self.comfort_range[1])
        else:  # 冬季降温
            new_target = max(self.room_temp + offset_c, self.comfort_range[0])

        # 计算可削减的功率
        power_reduction = self._calculate_power_reduction(new_target, outdoor_temp)
        return new_target, power_reduction

    def _calculate_power_reduction(self, target_temp, outdoor_temp):
        """计算温度偏移后的功率削减量"""
        # 简化的热力学模型
        heat_gain = (outdoor_temp - self.room_temp) / self.thermal_resistance  # kW
        required_cooling = heat_gain  # 维持当前温度所需制冷量
        new_required_cooling = (outdoor_temp - target_temp) / self.thermal_resistance
        power_reduction = (required_cooling - new_required_cooling) / self.cop
        return max(0, power_reduction)
```

#### 6.2.3 热泵热水器调度

利用热水储热能力，将加热时段平移至光伏出力高峰或低价时段：

```python
class HeatPumpScheduler:
    """
    热泵热水器调度器
    利用水箱储热能力，灵活安排加热时段
    """
    def __init__(self, tank_volume=300, rated_power=3.0, cop=3.0,
                 min_temp=40, max_temp=65):
        self.volume = tank_volume  # 水箱容积 (L)
        self.rated_power = rated_power  # 额定功率 (kW)
        self.cop = cop
        self.min_temp = min_temp
        self.max_temp = max_temp
        self.water_temp = 50  # 当前水温
        self.target_temp = 55  # 目标水温

    def can_delay(self, hours=2):
        """
        判断是否可以延时加热
        基于当前水温、目标温度和用水需求
        """
        # 水温自然下降速率（约0.5°C/小时）
        cooling_rate = 0.5  # °C/hour
        temp_after_delay = self.water_temp - cooling_rate * hours
        return temp_after_delay >= self.min_temp

    def schedule_heating(self, pv_forecast, price_forecast, hours_ahead=24):
        """
        优化加热时段安排
        优先在光伏出力高峰或低价时段加热
        """
        # 计算需要加热的能量
        energy_needed = self._calculate_heating_energy()

        # 找到最优加热时段
        best_slots = []
        for hour in range(hours_ahead):
            score = 0
            # 光伏出力得分
            score += pv_forecast[hour] * 0.5
            # 电价得分（低电价=高得分）
            score += (1 - price_forecast[hour] / max(price_forecast)) * 0.3
            # 用水需求得分（用水前加热）
            score += self._usage_score(hour) * 0.2
            best_slots.append((hour, score))

        # 按得分排序，选择最优时段
        best_slots.sort(key=lambda x: x[1], reverse=True)
        return best_slots[:int(energy_needed / self.rated_power)]

    def _calculate_heating_energy(self):
        """计算加热所需能量"""
        temp_rise = self.target_temp - self.water_temp
        if temp_rise <= 0:
            return 0
        # 水的比热容：4.186 kJ/(kg·°C)
        energy_kwh = self.volume * 4.186 * temp_rise / 3600
        return energy_kwh / self.cop  # 考虑COP
```

#### 6.2.4 泳池系统调度

泳池过滤和加热是典型的机会负荷，可灵活安排运行时段：

```python
class PoolScheduler:
    """
    泳池系统调度器
    过滤泵和加热器作为机会负荷，安排在光伏出力高峰时段运行
    """
    def __init__(self, filter_pump_power=1.5, heater_power=3.0,
                 min_filter_hours=6, target_temp=28):
        self.filter_power = filter_pump_power  # kW
        self.heater_power = heater_power  # kW
        self.min_filter_hours = min_filter_hours  # 每日最少过滤时间
        self.target_temp = target_temp
        self.water_temp = 26

    def optimize_schedule(self, pv_forecast, hours_ahead=24):
        """
        优化泳池系统运行时段
        过滤泵和加热器安排在光伏出力高峰时段
        """
        # 按光伏出力排序时段
        hours_with_pv = [(h, pv) for h, pv in enumerate(pv_forecast)]
        hours_with_pv.sort(key=lambda x: x[1], reverse=True)

        # 选择最优时段运行过滤泵
        filter_schedule = []
        for hour, _ in hours_with_pv[:self.min_filter_hours]:
            filter_schedule.append(hour)

        # 加热器在过滤泵运行时启动（需要加热时）
        heater_schedule = []
        if self.water_temp < self.target_temp:
            # 在过滤泵运行时段中选择光伏出力最高的时段加热
            for hour in filter_schedule[:4]:  # 最多加热4小时
                heater_schedule.append(hour)

        return {
            "filter_pump": sorted(filter_schedule),
            "heater": sorted(heater_schedule)
        }
```

#### 6.2.5 可控家电调度

洗衣机、洗碗机、烘干机等家电作为延时类负荷，用户设定"完成时间"，HEMS自动选择最优启动时间：

```python
class ApplianceScheduler:
    """
    可控家电调度器
    用户设定完成时间，HEMS自动选择最优启动时间
    """
    def __init__(self):
        self.appliances = {}

    def register_appliance(self, name, power_kw, duration_h, max_delay_h=8):
        """
        注册可控家电
        name: 设备名称
        power_kw: 额定功率
        duration_h: 运行时长
        max_delay_h: 最大可延时时间
        """
        self.appliances[name] = {
            "power": power_kw,
            "duration": duration_h,
            "max_delay": max_delay_h
        }

    def optimize_start_time(self, appliance_name, deadline,
                           pv_forecast, price_forecast):
        """
        优化启动时间
        deadline: 用户设定的完成时间
        返回最优启动时间
        """
        app = self.appliances[appliance_name]
        latest_start = deadline - app["duration"]
        earliest_start = max(0, deadline - app["max_delay"])

        best_score = -float('inf')
        best_start = earliest_start

        for start_hour in range(int(earliest_start), int(latest_start) + 1):
            # 计算该时段启动的综合得分
            score = 0
            for offset in range(int(app["duration"])):
                hour = start_hour + offset
                if hour < len(pv_forecast):
                    # 光伏出力得分（高光伏=高得分）
                    score += pv_forecast[hour] * 0.6
                if hour < len(price_forecast):
                    # 低电价得分
                    score += (1 - price_forecast[hour]) * 0.4

            if score > best_score:
                best_score = score
                best_start = start_hour

        return best_start
```

### 6.3 多设备协同调度算法

```python
class CoordinatedScheduler:
    """
    多设备协同调度器
    综合考虑所有可调节负荷，生成最优调度计划
    """
    def __init__(self):
        self.battery = None
        self.ev = None
        self.hvac = None
        self.heat_pump = None
        self.pool = None
        self.appliances = []

    def optimize(self, pv_forecast, load_forecast, price_forecast,
                 weather_forecast, user_preferences):
        """
        多设备协同优化调度
        返回所有设备的调度计划
        """
        schedule = {
            "battery": [],
            "ev": [],
            "hvac": [],
            "heat_pump": [],
            "pool": [],
            "appliances": []
        }

        # 1. 首先满足关键负荷（L1）
        # 2. 最大化光伏消纳
        # 3. 储能优化（峰谷套利）
        # 4. EV充电优化
        # 5. 温控负荷优化（利用热惯性）
        # 6. 机会负荷安排（光伏高峰时段）

        # 分层优化策略
        # 第一层：储能+EV（能量型，响应快）
        # 第二层：空调+热泵（温控型，有热惯性）
        # 第三层：泳池+家电（机会型，可灵活安排）

        # 第一层优化：储能+EV
        battery_schedule = self._optimize_battery(
            pv_forecast, load_forecast, price_forecast
        )
        schedule["battery"] = battery_schedule

        # 第二层优化：空调+热泵
        hvac_schedule = self._optimize_hvac(
            weather_forecast, price_forecast, user_preferences
        )
        schedule["hvac"] = hvac_schedule

        heat_pump_schedule = self._optimize_heat_pump(
            pv_forecast, price_forecast, user_preferences
        )
        schedule["heat_pump"] = heat_pump_schedule

        # 第三层优化：泳池+家电
        pool_schedule = self._optimize_pool(pv_forecast)
        schedule["pool"] = pool_schedule

        for app in self.appliances:
            app_schedule = self._optimize_appliance(
                app, pv_forecast, price_forecast
            )
            schedule["appliances"].append(app_schedule)

        return schedule

    def _optimize_battery(self, pv_forecast, load_forecast, price_forecast):
        """储能优化调度"""
        # 使用动态规划求解最优充放电策略
        n_periods = len(price_forecast)
        soc = 50  # 初始SOC
        schedule = []

        for i in range(n_periods):
            net_load = load_forecast[i] - pv_forecast[i]
            price = price_forecast[i]

            if net_load < 0:  # 光伏有余
                # 充电
                charge = min(-net_load, self.battery.max_charge)
                schedule.append(-charge)
            elif price > 0.8:  # 高电价
                # 放电
                discharge = min(net_load, self.battery.max_discharge)
                schedule.append(discharge)
            else:
                schedule.append(0)

        return schedule
```

---

## 7. VPP聚合与收益模型

### 7.1 家庭作为VPP节点

每个家庭HEMS节点作为VPP的最小聚合单元，向VPP云端上报灵活性容量：

```
家庭HEMS → 聚合灵活性 → VPP云端 → 电力市场
     │                        │
     │ 灵活性上报              │ 市场参与
     │ • 可上调容量            │ • 需求响应
     │ • 可下调容量            │ • 调频服务
     │ • 持续时间              │ • 现货市场
     │ • 置信度                │ • 容量市场
```

### 7.2 灵活性聚合上报

```json
{
  "method": "reportFlexibility",
  "params": {
    "node_id": "HEMS-A001",
    "timestamp": 1715218372000,
    "window_start": 1715218372000,
    "window_end": 1715220172000,
    "baseline_power_w": 3500,
    "flexibility": {
      "up": {
        "capacity_w": 8000,
        "duration_s": 600,
        "ramp_rate_w_per_s": 2000,
        "confidence": 0.9,
        "sources": {
          "battery_discharge": 5000,
          "ev_v2g": 7000,
          "hvac_shed": 2000,
          "pool_shed": 1500
        }
      },
      "down": {
        "capacity_w": 10000,
        "duration_s": 1800,
        "ramp_rate_w_per_s": 3000,
        "confidence": 0.85,
        "sources": {
          "battery_charge": 5000,
          "ev_charge": 7000,
          "hvac_increase": 2000,
          "heat_pump": 3000
        }
      }
    },
    "constraints": {
      "min_soc": 20,
      "ev_departure_time": 1715241600000,
      "ev_min_soc": 60,
      "comfort_temp_range": [24, 28]
    }
  }
}
```

### 7.3 收益模型

#### 7.3.1 收益来源

| 收益来源         | 说明                     | 年化收益估算  | 占比 |
| ---------------- | ------------------------ | :-----------: | :--: |
| **峰谷套利**     | 低储高放，利用分时电价差 | 1,500-3,000元 | 30%  |
| **光伏自发自用** | 减少电网购电             | 2,000-4,000元 | 40%  |
| **光伏余电上网** | 多余光伏卖给电网         |  500-1,500元  | 15%  |
| **需求响应**     | 参与电网削峰填谷         |  500-1,000元  | 10%  |
| **V2G放电**      | EV在高峰时段放电         |   300-800元   |  5%  |
| **社区能源共享** | 邻居间点对点交易         |   200-500元   | 待定 |

#### 7.3.2 收益计算引擎

```python
class RevenueCalculator:
    """
    家庭能源收益计算引擎
    """
    def __init__(self, grid_buy_price, grid_sell_price,
                 peak_valley_prices, dr_incentive):
        self.buy_price = grid_buy_price  # 购电价 (元/kWh)
        self.sell_price = grid_sell_price  # 售电价 (元/kWh)
        self.peak_prices = peak_valley_prices  # 分时电价
        self.dr_incentive = dr_incentive  # 需求响应激励 (元/kWh)

    def calculate_daily_revenue(self, pv_gen, battery_charge, battery_discharge,
                                ev_charge, ev_discharge, grid_import, grid_export,
                                dr_participation):
        """
        计算日收益
        """
        # 1. 光伏自发自用节省
        self_consumption = pv_gen - grid_export
        self_consumption_saving = self_consumption * self.buy_price

        # 2. 光伏余电上网收益
        export_revenue = grid_export * self.sell_price

        # 3. 峰谷套利收益
        arbitrage_revenue = 0
        for hour in range(24):
            if battery_discharge[hour] > 0:
                # 放电收益（按实时电价）
                arbitrage_revenue += battery_discharge[hour] * self.peak_prices[hour]
            if battery_charge[hour] > 0:
                # 充电成本
                arbitrage_revenue -= battery_charge[hour] * self.peak_prices[hour]

        # 4. V2G放电收益
        v2g_revenue = 0
        for hour in range(24):
            if ev_discharge[hour] > 0:
                v2g_revenue += ev_discharge[hour] * self.peak_prices[hour]

        # 5. 需求响应收益
        dr_revenue = dr_participation * self.dr_incentive

        # 6. 电网购电成本
        grid_cost = sum(grid_import) * self.buy_price

        total_revenue = (self_consumption_saving + export_revenue +
                        arbitrage_revenue + v2g_revenue + dr_revenue)
        total_cost = grid_cost

        return {
            "self_consumption_saving": self_consumption_saving,
            "export_revenue": export_revenue,
            "arbitrage_revenue": arbitrage_revenue,
            "v2g_revenue": v2g_revenue,
            "dr_revenue": dr_revenue,
            "grid_cost": grid_cost,
            "net_revenue": total_revenue - total_cost,
            "self_sufficiency_rate": self_consumption / (self_consumption + sum(grid_import)) * 100
        }
```

### 7.4 VPP参与流程

```
VPP需求响应事件流程：

VPP云端 → 发布需求响应事件
    │
    ▼
家庭HEMS → 评估可参与容量
    │
    ├── 可参与 → 上报响应容量
    │       │
    │       ▼
    │   VPP确认 → 执行响应
    │       │
    │       ▼
    │   验证响应效果
    │       │
    │       ▼
    │   结算收益
    │
    └── 不可参与 → 上报不可用原因
            │
            ▼
        VPP调整调度计划
```

---

## 8. NILM设备与HEMS硬件交互闭环

### 8.1 NILM系统架构

NILM（非侵入式负载监测）作为HEMS的"感知层"，通过分析总线电流/电压波形，识别各设备的运行状态和能耗，与HEMS形成感知-决策-控制的完整闭环。

```
┌─────────────────────────────────────────────────────────────────┐
│                    NILM + HEMS 交互闭环                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────┐         ┌──────────────────┐             │
│  │   NILM感知层      │         │   HEMS决策层      │             │
│  │                  │         │                  │             │
│  │ • 1kHz波形采样   │────────►│ • 设备状态识别   │             │
│  │ • 设备指纹提取   │  事件   │ • 负荷分解       │             │
│  │ • 事件检测       │  通知   │ • 异常检测       │             │
│  └────────┬─────────┘         └────────┬─────────┘             │
│           │                            │                       │
│           │ 设备状态/能耗               │ 调度指令              │
│           ▼                            ▼                       │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    闭环反馈环                            │   │
│  │  NILM识别设备状态 → HEMS优化调度 → 设备执行 → NILM验证  │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 8.2 NILM硬件设计

#### 8.2.1 硬件规格

| 参数          | 规格                                          |
| ------------- | --------------------------------------------- |
| **采样率**    | 1 kHz（三相电压/电流同步采样）                |
| **ADC分辨率** | 16位                                          |
| **输入通道**  | 3×电压（0-300V AC）+ 3×电流（0-100A，使用CT） |
| **通信接口**  | RS485（Modbus RTU）+ WiFi（MQTT）+ 以太网     |
| **处理器**    | ESP32-S3 / ARM Cortex-M7                      |
| **供电**      | 220V AC 直供（内置电源模块）                  |
| **安装方式**  | DIN导轨安装，入户配电箱内                     |
| **尺寸**      | 4个模数（72mm宽）                             |

#### 8.2.2 与HEMS网关的交互方式

```
┌─────────────────────────────────────────────────────────────────┐
│                    NILM硬件与HEMS网关交互                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  方式一：集成式（推荐）                                          │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │               HEMS网关（含NILM功能）                      │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │   │
│  │  │ 1kHz ADC采样  │─►│ NILM推理引擎  │─►│ HEMS调度引擎  │  │   │
│  │  │ (电能计量芯片) │  │ (边缘AI)     │  │ (控制算法)   │  │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘  │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  方式二：分离式                                                │
│  ┌──────────────┐    MQTT/Modbus    ┌──────────────┐          │
│  │  NILM采集器   │─────────────────►│  HEMS网关     │          │
│  │  (独立硬件)   │  设备事件+能耗    │  (控制决策)   │          │
│  └──────────────┘                   └──────────────┘          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 8.3 NILM设备识别算法

#### 8.3.1 设备指纹库

```python
class DeviceFingerprint:
    """
    设备电气指纹模型
    用于NILM设备识别
    """
    def __init__(self):
        self.fingerprint_db = {}

    def register_device(self, device_id, device_type, rated_power):
        """
        注册设备指纹
        在设备首次接入时，通过特征提取建立指纹
        """
        fingerprint = {
            "device_id": device_id,
            "device_type": device_type,
            "rated_power": rated_power,
            "v_i_trajectory": None,  # V-I轨迹特征
            "harmonic_profile": None,  # 谐波特征
            "startup_slope": None,  # 启动斜率
            "power_factor_range": None,  # 功率因数范围
            "transient_response": None,  # 暂态响应
            "last_seen": None,
            "confidence": 0.0
        }
        self.fingerprint_db[device_id] = fingerprint

    def extract_features(self, voltage_samples, current_samples):
        """
        从1kHz采样数据中提取设备特征
        """
        features = {}

        # 1. V-I轨迹特征
        features['v_i_trajectory'] = self._extract_vi_trajectory(
            voltage_samples, current_samples
        )

        # 2. 谐波特征（FFT分析）
        features['harmonic_profile'] = self._extract_harmonics(
            current_samples
        )

        # 3. 启动斜率
        features['startup_slope'] = self._extract_startup_slope(
            current_samples
        )

        # 4. 功率因数
        features['power_factor'] = self._calculate_power_factor(
            voltage_samples, current_samples
        )

        return features

    def identify_device(self, features):
        """
        根据提取的特征识别设备
        返回最匹配的设备ID和置信度
        """
        best_match = None
        best_score = 0

        for device_id, fingerprint in self.fingerprint_db.items():
            score = self._match_score(features, fingerprint)
            if score > best_score:
                best_score = score
                best_match = device_id

        return best_match, best_score

    def _extract_vi_trajectory(self, v, i):
        """提取V-I轨迹特征"""
        # 归一化
        v_norm = v / np.max(np.abs(v))
        i_norm = i / np.max(np.abs(i))
        return np.column_stack((v_norm, i_norm))

    def _extract_harmonics(self, current):
        """提取谐波特征（1-15次谐波）"""
        fft = np.fft.fft(current)
        harmonics = np.abs(fft[1:16]) / np.abs(fft[0])
        return harmonics.tolist()

    def _extract_startup_slope(self, current):
        """提取启动电流斜率"""
        # 检测电流上升沿
        diff = np.diff(current)
        startup_idx = np.argmax(diff)
        slope = diff[startup_idx] / (1/1000)  # A/s
        return slope

    def _calculate_power_factor(self, v, i):
        """计算功率因数"""
        # 有功功率
        p = np.mean(v * i)
        # 视在功率
        s = np.sqrt(np.mean(v**2)) * np.sqrt(np.mean(i**2))
        return p / s if s != 0 else 0

    def _match_score(self, features, fingerprint):
        """计算特征匹配得分"""
        score = 0

        # 谐波特征匹配
        if fingerprint['harmonic_profile'] is not None:
            harmonic_diff = np.abs(
                np.array(features['harmonic_profile']) -
                np.array(fingerprint['harmonic_profile'])
            )
            score += 0.4 * (1 - np.mean(harmonic_diff))

        # 启动斜率匹配
        if fingerprint['startup_slope'] is not None:
            slope_diff = abs(features['startup_slope'] - fingerprint['startup_slope'])
            slope_score = max(0, 1 - slope_diff / fingerprint['startup_slope'])
            score += 0.3 * slope_score

        # 功率因数匹配
        if fingerprint['power_factor_range'] is not None:
            pf = features['power_factor']
            pf_min, pf_max = fingerprint['power_factor_range']
            if pf_min <= pf <= pf_max:
                score += 0.3

        return score
```

#### 8.3.2 设备事件检测

```python
class EventDetector:
    """
    NILM事件检测器
    检测设备启停事件，用于负荷分解和邻居发现
    """
    def __init__(self, power_threshold=50, min_duration=3):
        self.power_threshold = power_threshold  # 功率变化阈值 (W)
        self.min_duration = min_duration  # 最小持续时间 (采样点)
        self.baseline_power = 0
        self.is_transitioning = False

    def detect_event(self, power_samples):
        """
        检测功率变化事件
        返回事件列表 [(timestamp, delta_power, event_type), ...]
        """
        events = []
        power_diff = np.diff(power_samples)

        # 检测上升沿（设备启动）
        startup_indices = np.where(power_diff > self.power_threshold)[0]
        for idx in startup_indices:
            # 验证持续时间
            if self._verify_duration(power_samples, idx, 'START'):
                events.append({
                    'timestamp': idx,
                    'delta_power': power_samples[idx + 1] - power_samples[idx],
                    'event_type': 'START',
                    'confidence': self._calculate_confidence(power_samples, idx)
                })

        # 检测下降沿（设备关闭）
        shutdown_indices = np.where(power_diff < -self.power_threshold)[0]
        for idx in shutdown_indices:
            if self._verify_duration(power_samples, idx, 'STOP'):
                events.append({
                    'timestamp': idx,
                    'delta_power': power_samples[idx] - power_samples[idx + 1],
                    'event_type': 'STOP',
                    'confidence': self._calculate_confidence(power_samples, idx)
                })

        return events

    def _verify_duration(self, power_samples, idx, event_type):
        """验证事件持续时间"""
        if event_type == 'START':
            # 检查启动后功率是否稳定
            end_idx = min(idx + self.min_duration, len(power_samples) - 1)
            return np.all(power_samples[idx:end_idx] > self.baseline_power + self.power_threshold)
        else:
            end_idx = min(idx + self.min_duration, len(power_samples) - 1)
            return np.all(power_samples[idx:end_idx] < self.baseline_power - self.power_threshold)
```

### 8.4 NILM-HEMS闭环控制流程

```
┌─────────────────────────────────────────────────────────────────────┐
│                    NILM-HEMS 完整闭环流程                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  步骤1：NILM感知                                                    │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ 1kHz采样 → FFT分析 → 事件检测 → 设备指纹匹配 → 设备状态识别  │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                              │                                      │
│                              ▼                                      │
│  步骤2：状态更新                                                    │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ 更新设备状态表：{设备A: 运行中(2.5kW), 设备B: 待机(10W), ...} │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                              │                                      │
│                              ▼                                      │
│  步骤3：HEMS决策                                                    │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ 基于设备状态 + 光伏出力 + 电价 → 优化调度决策                 │   │
│  │ 输出：各设备控制指令（功率设定/启停/延时）                     │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                              │                                      │
│                              ▼                                      │
│  步骤4：指令执行                                                    │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ Modbus/OCPP/MQTT → 设备执行指令                              │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                              │                                      │
│                              ▼                                      │
│  步骤5：NILM验证                                                    │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ 验证设备是否按指令响应 → 记录响应偏差 → 更新信用权重         │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                              │                                      │
│                              ▼                                      │
│  步骤6：闭环反馈                                                    │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ 响应正常 → 继续执行调度计划                                   │   │
│  │ 响应异常 → 触发告警 + 重新调度                               │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 8.5 NILM在HEMS中的关键应用

| 应用场景           | 说明                                   | 技术实现                       |
| ------------------ | -------------------------------------- | ------------------------------ |
| **设备级能耗监测** | 无需智能插座，通过NILM分解各设备能耗   | 1kHz采样 + 事件检测 + 负荷分解 |
| **物理身份校验**   | 验证设备声明标签与实际电气特征是否一致 | 指纹匹配 + 置信度评分          |
| **异常检测**       | 检测设备老化、接触不良等异常           | 谐波特征变化 + 启动斜率偏移    |
| **邻居发现辅助**   | 通过NILM事件对账确认物理连接关系       | 事件时间戳 + 特征匹配          |
| **基线计算**       | 基于NILM分解的精细化基线               | 设备级负荷分解 + 相似日匹配    |
| **需求响应验证**   | 验证设备是否按指令响应                 | 功率变化量 + 响应时间          |

---

## 9. 电网安全运行机制

### 9.1 物理约束引擎

HEMS内置物理约束引擎，作为所有调度决策的硬性边界：

#### 9.1.1 并网功率约束

| 参数       | 正常范围       | 告警阈值 | 动作阈值 |
| ---------- | -------------- | :------: | :------: |
| 并网功率   | ≤ 家庭进线容量 |   80%    |   95%    |
| 功率变化率 | ≤ 10%/分钟     | 15%/分钟 | 20%/分钟 |
| 电压偏差   | ±5%            |   ±7%    |   ±10%   |
| 频率偏差   | ±0.2Hz         |  ±0.5Hz  |  ±1.0Hz  |

#### 9.1.2 功率变化率控制

防止多设备同时动作导致对电网的冲击：

```python
class RampRateController:
    """
    功率变化率控制器
    确保并网点功率变化率不超过安全阈值
    """
    def __init__(self, max_ramp_rate_pct=10, interval_s=60):
        self.max_ramp_rate = max_ramp_rate_pct  # 最大变化率 (%/interval)
        self.interval = interval_s  # 计算间隔 (秒)
        self.last_power = 0
        self.last_time = None

    def check_ramp_rate(self, current_power, timestamp):
        """
        检查功率变化率是否超限
        返回是否允许执行
        """
        if self.last_time is None:
            self.last_power = current_power
            self.last_time = timestamp
            return True

        time_diff = (timestamp - self.last_time) / 1000  # 秒
        if time_diff < 1:
            return True  # 太短，不判断

        power_change = abs(current_power - self.last_power)
        ramp_rate = (power_change / self.last_power) * 100 if self.last_power > 0 else 0

        # 归一化到60秒
        normalized_rate = ramp_rate * (self.interval / time_diff)

        if normalized_rate > self.max_ramp_rate:
            return False  # 变化率超限，拒绝执行

        self.last_power = current_power
        self.last_time = timestamp
        return True

    def limit_power_change(self, target_power, current_power):
        """
        限制功率变化量，确保变化率不超限
        返回限制后的目标功率
        """
        max_change = current_power * (self.max_ramp_rate / 100)
        change = target_power - current_power

        if abs(change) > max_change:
            change = np.sign(change) * max_change

        return current_power + change
```

### 9.2 孤岛检测与保护

#### 9.2.1 孤岛检测方法

| 检测方法   | 原理                   | 检测时间  |     可靠性     |
| ---------- | ---------------------- | :-------: | :------------: |
| **被动式** | 检测电压/频率异常偏移  | 100-500ms |       中       |
| **主动式** | 注入小扰动信号检测响应 | 50-200ms  |       高       |
| **通信式** | 与电网调度通信确认     |   <50ms   | 最高（需通信） |

#### 9.2.2 孤岛运行切换流程

```
正常并网运行
    │
    ├── 电网失电检测（电压<180V或频率<47.5Hz持续200ms）
    │       │
    │       ▼
    │   断开并网开关（<200ms）
    │       │
    │       ▼
    │   切换至孤岛模式
    │       │
    │       ├── 储能作为主电源（V/f控制）
    │       ├── 光伏限功率运行（防止过充）
    │       ├── 仅保障L1关键负荷
    │       └── EV V2G作为备用电源
    │       │
    │       ▼
    │   每5秒检测电网是否恢复
    │       │
    │       ├── 电网恢复 → 同步并网（需满足IEEE 1547）
    │       │       │
    │       │       ▼
    │       │   恢复并网运行
    │       │
    │       └── 电网未恢复 → 继续孤岛运行
    │
    └── 电网正常 → 继续并网运行
```

### 9.3 柔性减载策略

#### 9.3.1 减载触发条件

| 触发条件       |         阈值         | 响应动作       |
| -------------- | :------------------: | -------------- |
| 并网功率超限   | > 家庭进线容量 × 95% | 按优先级减载   |
| 功率变化率超限 |      > 20%/分钟      | 限制功率变化   |
| 电压越限       |   < 207V 或 > 253V   | 断开非关键负荷 |
| 频率越限       |   < 49Hz 或 > 51Hz   | 断开非关键负荷 |
| VPP指令        |     收到减载指令     | 按指令执行     |

#### 9.3.2 减载执行次序

| 步骤 | 动作               |   延迟   | 目标设备               |
| :--: | ------------------ | :------: | ---------------------- |
|  1   | 切断L4设备         |  T+0ms   | 泳池泵、洗衣机、烘干机 |
|  2   | L3设备限流至50%    |  T+50ms  | EV充电、空调、热泵     |
|  3   | L3设备限流至最小   | T+200ms  | EV充电、空调、热泵     |
|  4   | 储能停止放电       | T+500ms  | 储能电池               |
|  5   | 紧急全切（保留L1） | T+1000ms | 所有非L1设备           |

---

## 10. 硬件参考设计

### 10.1 HEMS网关硬件规格

| 组件         | 规格                            | 说明              |
| ------------ | ------------------------------- | ----------------- |
| **主控SoC**  | ARM Cortex-A72 四核 1.5GHz      | 主计算单元        |
| **NPU**      | 2 TOPS AI加速器                 | NILM推理加速      |
| **内存**     | 4GB LPDDR4                      | 运行时数据        |
| **存储**     | 64GB eMMC + microSD扩展         | 本地日志存储      |
| **ADC**      | 6通道 16位 1kHz同步采样         | 电压/电流采样     |
| **通信**     | 2×千兆以太网 + WiFi 6 + BLE 5.0 | 网络连接          |
| **工业接口** | 2×RS485 + 1×CAN + 2×USB 3.0     | 设备接入          |
| **安全**     | TPM 2.0安全芯片                 | 密钥存储/安全启动 |
| **供电**     | 9-36V DC 或 PoE+                | 灵活供电          |
| **功耗**     | < 15W（典型）                   | 低功耗设计        |
| **尺寸**     | DIN导轨安装，6个模数（108mm宽） | 标准配电箱安装    |

### 10.2 NILM采集器硬件规格

| 组件           | 规格                                 |
| -------------- | ------------------------------------ |
| **主控**       | ESP32-S3 (240MHz, 512KB SRAM)        |
| **ADC**        | 6通道 16位 1kHz同步采样（ADS131M06） |
| **电流传感器** | 3× 开口式CT (100A/50mA)              |
| **电压采样**   | 3× 电阻分压 (0-300V AC)              |
| **通信**       | WiFi + RS485 (Modbus RTU)            |
| **供电**       | 220V AC 直供                         |
| **功耗**       | < 3W                                 |
| **尺寸**       | DIN导轨安装，4个模数（72mm宽）       |

### 10.3 硬件连接拓扑

```
┌─────────────────────────────────────────────────────────────────────┐
│                    家庭配电箱内硬件连接                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  电网进线 ──┬── 智能电表 ──┬── 总闸 ──┬── 家庭配电母线              │
│             │             │          │                             │
│             │             │          ├── L1回路：照明/插座          │
│             │             │          ├── L2回路：空调               │
│             │             │          ├── L3回路：厨房               │
│             │             │          └── L4回路：泳池/花园          │
│             │             │                                        │
│             │             └── NILM采集器（母线总电流/电压采样）     │
│             │                                                        │
│             └── HEMS网关（控制决策+通信）                            │
│                                                                     │
│  光伏逆变器 ── RS485 ──┐                                            │
│  储能电池   ── RS485 ──┤                                            │
│  EV充电桩   ── 以太网 ──┤── HEMS网关                                │
│  空调       ── RS485 ──┤                                            │
│  热泵热水器 ── RS485 ──┘                                            │
│  泳池系统   ── RS485 ──┐                                            │
│  可控家电   ── WiFi ───┘                                            │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 11. 软件架构与数据流

### 11.1 软件模块架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                    HEMS 软件模块架构                                 │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    应用层 (Application)                      │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐      │   │
│  │  │ 能源调度  │ │ 设备管理  │ │ 收益计算  │ │ 用户界面  │      │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘      │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                              │                                      │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    服务层 (Service)                          │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐      │   │
│  │  │ 预测引擎  │ │ 优化引擎  │ │ 规则引擎  │ │ 事件引擎  │      │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘      │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                              │                                      │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    核心层 (Core)                             │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐      │   │
│  │  │ 设备抽象  │ │ NILM引擎  │ │ 物理约束  │ │ 通信管理  │      │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘      │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                              │                                      │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    驱动层 (Driver)                           │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐      │   │
│  │  │ Modbus   │ │  OCPP    │ │  MQTT    │ │  KNX     │      │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘      │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 11.2 数据流设计

```
┌─────────────────────────────────────────────────────────────────────┐
│                    HEMS 数据流设计                                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  实时数据流（1秒周期）：                                            │
│  设备 → Modbus/OCPP/MQTT → 设备抽象层 → 数据聚合 → 本地存储       │
│                                                          │         │
│                                                          ▼         │
│                                                   控制算法执行       │
│                                                          │         │
│                                                          ▼         │
│                                                   指令下发到设备     │
│                                                                     │
│  准实时数据流（15分钟周期）：                                       │
│  本地存储 → 预测引擎 → 优化引擎 → 调度计划更新 → 设备控制          │
│                                                                     │
│  批量数据流（每日）：                                               │
│  本地存储 → 数据压缩 → MQTT推送 → 云端存储                         │
│                                                                     │
│  事件数据流（事件触发）：                                           │
│  NILM事件检测 → 设备状态更新 → 规则引擎 → 告警/动作                │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 11.3 推荐技术栈

| 组件             | 推荐技术                       | 说明         |
| ---------------- | ------------------------------ | ------------ |
| **边缘计算框架** | OpenEMS Edge / 自研Go服务      | 实时控制闭环 |
| **NILM引擎**     | TensorFlow Lite / ONNX Runtime | 边缘AI推理   |
| **时序数据库**   | InfluxDB / SQLite（本地）      | 时序数据存储 |
| **消息队列**     | MQTT (Mosquitto)               | 设备通信     |
| **协议转换**     | 自研Modbus/OCPP适配器          | 设备接入     |
| **前端**         | React / Vue + ECharts          | 用户界面     |
| **移动端**       | Flutter / React Native         | App          |
| **云端**         | Python FastAPI + PostgreSQL    | VPP聚合平台  |

---

## 12. 实施路线图

### 12.1 分阶段实施

```
Phase 0 (1-2月)         Phase 1 (3-6月)          Phase 2 (7-12月)         Phase 3 (13-18月)
┌──────────────┐      ┌────────────────┐       ┌──────────────────┐      ┌──────────────────┐
│ 原型验证      │ ──→ │ 单家庭试点      │ ──→  │ 社区试点          │ ──→ │ 规模化部署       │
│              │      │                │       │                  │      │                  │
│ • 核心算法    │      │ • 设备接入     │       │ • 邻居组网        │      │ • VPP聚合        │
│ • 模拟测试    │      │ • 本地控制     │       │ • 社区共享        │      │ • 市场参与       │
│ • 硬件选型    │      │ • NILM验证    │       │ • 协同调度        │      │ • 收益结算       │
└──────────────┘      └────────────────┘       └──────────────────┘      └──────────────────┘
```

### 12.2 关键里程碑

| 里程碑         |   时间   | 交付物                   |
| -------------- | :------: | ------------------------ |
| M1: 原型完成   | 第2个月  | HEMS原型系统（模拟环境） |
| M2: 单家庭试点 | 第6个月  | 1个家庭完整部署并运行    |
| M3: NILM验证   | 第8个月  | NILM识别准确率≥90%       |
| M4: 社区试点   | 第12个月 | 5-10个家庭组网运行       |
| M5: VPP接入    | 第15个月 | 社区资源接入VPP平台      |
| M6: 规模化     | 第18个月 | 50+家庭部署              |

---

## 13. 附录

### 附录A：设备类型编码表

| 编码 | 设备类型 | 说明          |
| :--: | -------- | ------------- |
| 0x01 | PV       | 光伏逆变器    |
| 0x02 | ESS      | 储能系统      |
| 0x03 | EVCS     | EV充电桩      |
| 0x04 | V2G      | V2G双向充电桩 |
| 0x05 | HVAC     | 空调          |
| 0x06 | HPWH     | 热泵热水器    |
| 0x07 | POOL     | 泳池系统      |
| 0x08 | APPL     | 可控家电      |
| 0x09 | NILM     | NILM监测设备  |
| 0x0A | METER    | 智能电表      |

### 附录B：事件类型编码表

| 编码  | 事件类型        | 严重程度 |
| :---: | --------------- | :------: |
| E-001 | DEVICE_ONLINE   |   INFO   |
| E-002 | DEVICE_OFFLINE  |   WARN   |
| E-003 | DEVICE_FAULT    |  ERROR   |
| E-010 | PV_SURPLUS      |   INFO   |
| E-011 | BATTERY_FULL    |   INFO   |
| E-012 | EV_ARRIVAL      |   INFO   |
| E-013 | EV_DEPARTURE    |   INFO   |
| E-020 | GRID_OUTAGE     | CRITICAL |
| E-021 | GRID_RESTORE    |   INFO   |
| E-022 | POWER_OVERLOAD  |   WARN   |
| E-030 | NILM_EVENT      |   INFO   |
| E-031 | NILM_ANOMALY    |   WARN   |
| E-032 | NILM_MISMATCH   |   WARN   |
| E-040 | NEIGHBOR_FOUND  |   INFO   |
| E-041 | NEIGHBOR_LOST   |   WARN   |
| E-050 | ENERGY_SHARE    |   INFO   |
| E-060 | VPP_DR_EVENT    |   WARN   |
| E-061 | VPP_DR_RESPONSE |   INFO   |
| E-070 | ISLAND_MODE     |   WARN   |
| E-071 | GRID_SYNC       |   INFO   |

### 附录C：通信协议对比

|    协议    | 适用设备           |  传输方式  | 实时性 | 复杂度 |
| :--------: | ------------------ | :--------: | :----: | :----: |
| Modbus RTU | 逆变器、储能、电表 | RS485串口  |   高   |   低   |
| Modbus TCP | 逆变器、储能       |   以太网   |   高   |   低   |
| OCPP 1.6J  | EV充电桩           | WebSocket  |   中   |   中   |
| OCPP 2.0.1 | EV充电桩（V2G）    | WebSocket  |   中   |   高   |
| ISO 15118  | V2G通信            | PLC/以太网 |   高   |   高   |
|    MQTT    | 智能家电           |    WiFi    |   中   |   低   |
|    KNX     | 楼宇自控           |  专用总线  |   高   |   高   |
|  SunSpec   | 光伏逆变器         |   Modbus   |   高   |   低   |

### 附录D：参考文档

| 文档                                | 说明                     |
| ----------------------------------- | ------------------------ |
| OpenEMS 官方文档                    | OpenEMS三层架构参考      |
| VPP_EMS 能量路由器综合标准规范 v2.0 | 能源交换机范式、协议规范 |
| IEEE 1547-2018                      | 分布式能源并网标准       |
| IEC 61850                           | 变电站通信标准           |
| OCPP 2.0.1                          | 充电桩通信协议           |
| ISO 15118-20                        | V2G通信协议              |

---

## 版本历史

| 版本 |    日期    | 修改内容                                       |
| :--: | :--------: | ---------------------------------------------- |
| v1.0 | 2026-05-10 | 初始版本，基于OpenEMS架构和VPP_EMS标准规范制定 |

---

_本文档基于OpenEMS三层架构和VPP_EMS能量路由器标准规范v2.0制定_
_文档状态：已完成（共13章 + 4个附录）_

```

```
