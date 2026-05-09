# LatticeWork — 晶格工作流框架

> **将复杂工作拆解为原子任务，通过 PCDCA 循环逐层构建，实现人类可读、AI 可执行的自主化工作流。**

## 核心理念

LatticeWork 的灵感来源于**晶格结构（Lattice）**—— 一种从核心到外层的分层构建方式。与传统的自上而下（Top-Down）或自底向上（Bottom-Up）不同，LatticeWork 采用**逆向构建（Bottom-Up from Core）**：

```
Layer N (核心层)  →  层组装  →  意图对齐  →  Layer N-1  →  ...  →  Layer 0 (外层)
```

每一层都像晶格中的一个原子层，从最核心的领域模型开始构建，逐层向外扩展，每层完成后执行组装测试和意图对齐。

## 架构概览

```
lattice/
├── schemas/              # 数据模式定义 (JSON Schema)
│   ├── lattice.schema.json          # 晶格方案顶层模式
│   ├── atomic_task.schema.json      # 原子任务模式
│   ├── pcdca_cycle.schema.json      # PCDCA循环记录模式
│   ├── layer_assembly.schema.json   # 层组装记录模式
│   └── blocker.schema.json          # 阻塞点注册模式
│
├── templates/            # YAML 模板
│   ├── template_lattice.yaml        # 晶格方案模板
│   ├── template_atomic_task.yaml    # 原子任务模板
│   └── template_layer_assembly.yaml # 层组装模板
│
├── scripts/              # 可执行脚本
│   ├── lattice_core.py              # 晶格引擎核心
│   ├── lattice_blocker.py           # 阻塞点管理器
│   ├── lattice_pcdca.py             # PCDCA循环执行器
│   └── lattice_runner.py            # 主运行器（CLINE入口点）
│
├── workflows/            # 工作流定义
│   ├── lattice_workflow.yaml        # 晶格执行工作流
│   ├── pcdca_workflow.yaml          # PCDCA循环工作流
│   └── blocker_workflow.yaml        # 阻塞点管理工作流
│
├── examples/             # 示例方案
│   ├── quant_trading/               # 量化交易 - 基差套利策略
│   ├── software_design/             # 软件设计 - 微服务架构
│   └── business_model/              # 商业模式 - SaaS定价模型
│
├── lattice_runtime/      # 运行时数据（自动生成）
│   ├── pcdca_log/                   # PCDCA循环日志
│   ├── checkpoints/                 # 执行检查点
│   └── blocker_registry.json        # 阻塞点注册表
│
└── README.md             # 本文档
```

## 核心概念

### 1. 晶格方案 (Lattice)

晶格方案是整个工作流的顶层定义。它包含：

- **意图定义**：用户目标、验收标准、约束条件
- **层级分解**：从核心层到外层的分层结构
- **执行策略**：执行方向、PCDCA配置、人工介入策略

### 2. 原子任务 (Atomic Task)

最小可执行单元。每个任务：

- 有明确的**意图**和**验收标准**
- 定义**依赖关系**和**接口契约**
- 通过 **PCDCA 循环**完成
- 有完整的**状态追踪**

### 3. PCDCA 循环

每个原子任务通过 PCDCA 循环完成：

```
P (Plan)           → 识别阻塞点 + 制定执行计划
C (Check-HITL)     → 人工审核计划 (Pass/Fail)
D (Do)             → 执行计划中的步骤
C (Check)          → 验证产物是否符合验收标准 (Pass/Fail)
A (Action)         → Pass→标记完成 | Fail→回退到Plan | Blocked→暂停
```

### 4. 层组装 (Layer Assembly)

当同一层级的所有原子任务都完成 PCDCA 循环后：

1. 验证所有任务状态为 pass
2. 运行组装测试
3. 检查意图对齐
4. 记录层组装结果
5. 进入下一层

### 5. 阻塞点管理 (Blocker)

阻塞点分为三类：

- **已知阻塞（Known）**：已知已知，有预设解决方案
- **发现阻塞（Discovered）**：已知未知，执行中发现
- **隐含阻塞（Implicit）**：未知未知，需要人工介入

## 快速开始

### 1. 安装依赖

```bash
pip install pyyaml
```

### 2. 验证晶格方案

```bash
python lattice/scripts/lattice_core.py validate \
    --lattice lattice/examples/quant_trading/lattice_basis_arbitrage.yaml
```

### 3. 生成执行顺序

```bash
python lattice/scripts/lattice_core.py execution-order \
    --lattice lattice/examples/quant_trading/lattice_basis_arbitrage.yaml
```

### 4. 生成 CLINE 执行指令

```bash
python lattice/scripts/lattice_runner.py cline-instructions \
    --lattice lattice/examples/quant_trading/lattice_basis_arbitrage.yaml
```

### 5. 完整执行

```bash
python lattice/scripts/lattice_runner.py run \
    --lattice lattice/examples/quant_trading/lattice_basis_arbitrage.yaml
```

## 执行流程

### 完整执行流程

```
1. 验证晶格方案
   ↓
2. 生成逆向执行顺序
   ↓
3. 从核心层开始逐层执行:
   ┌─────────────────────────────────────────┐
   │  Layer N (核心层)                        │
   │  ├── task_0001 (PCDCA循环)              │
   │  ├── task_0002 (PCDCA循环)              │
   │  └── task_0003 (PCDCA循环)              │
   │  ↓                                      │
   │  层组装测试                              │
   │  ↓                                      │
   │  意图对齐检查                            │
   └─────────────────────────────────────────┘
   ↓
4. Layer N-1 (重复上述过程)
   ↓
5. ... 直到 Layer 0
   ↓
6. 生成执行报告
```

### 单个任务的 PCDCA 循环

```
┌─────────────────────────────────────────┐
│  PCDCA 循环 #1                          │
│  ├── P: 识别阻塞 + 制定计划              │
│  ├── C(HITL): 人工审核计划               │
│  ├── D: 执行步骤                        │
│  ├── C: 验证产物                        │
│  └── A: 决策                            │
│       ├── proceed → 标记完成             │
│       ├── retry → 开始新的PCDCA循环       │
│       ├── block → 暂停并通知用户          │
│       ├── escalate → 升级到人工处理       │
│       └── skip → 跳过该任务              │
└─────────────────────────────────────────┘
```

## 脚本命令参考

### lattice_core.py

| 命令              | 描述                   |
| ----------------- | ---------------------- |
| `parse`           | 解析并显示晶格方案信息 |
| `execution-order` | 生成逆向执行顺序       |
| `assemble`        | 创建层组装记录         |
| `align`           | 检查意图对齐           |
| `pcdca-template`  | 生成PCDCA循环记录模板  |
| `validate`        | 验证晶格方案完整性     |

### lattice_blocker.py

| 命令       | 描述           |
| ---------- | -------------- |
| `register` | 注册阻塞点     |
| `status`   | 查看阻塞点状态 |
| `update`   | 更新阻塞点状态 |
| `resolve`  | 解决阻塞点     |
| `escalate` | 升级阻塞点     |
| `report`   | 生成阻塞点报告 |

### lattice_pcdca.py

| 命令         | 描述               |
| ------------ | ------------------ |
| `start`      | 开始新的PCDCA循环  |
| `plan`       | 记录Plan阶段       |
| `plan-check` | 记录Plan-Check阶段 |
| `do`         | 记录Do阶段步骤     |
| `check`      | 记录Check阶段      |
| `action`     | 记录Action阶段     |
| `status`     | 查看循环状态       |

### lattice_runner.py

| 命令                 | 描述              |
| -------------------- | ----------------- |
| `run`                | 完整执行晶格方案  |
| `run-layer`          | 仅执行指定层      |
| `run-task`           | 仅执行指定任务    |
| `status`             | 查看执行状态      |
| `cline-instructions` | 生成CLINE执行指令 |

## 适用领域

LatticeWork 适用于需要**分层构建**和**逐步验证**的复杂工作：

| 领域         | 示例                               |
| ------------ | ---------------------------------- |
| **量化交易** | 算法设计、回测验证、策略优化       |
| **软件设计** | 微服务架构、领域驱动设计、系统重构 |
| **商业模式** | 定价策略、市场分析、收入预测       |
| **法律合规** | 合同审查、尽职调查、政策分析       |
| **能源金融** | 太阳能财务模型、储能市场分析       |

## 设计原则

1. **人类可读，AI可执行**：所有方案使用自然语言描述，同时包含结构化字段供AI执行
2. **从核心构建**：从最核心的领域模型开始，逐层向外扩展
3. **每层验证**：每层完成后执行组装测试和意图对齐
4. **PCDCA循环**：每个原子任务通过完整的PCDCA循环完成
5. **Human-in-the-Loop**：关键决策点需要人工审核
6. **阻塞点管理**：阻塞点分类处理，严重阻塞升级到人工
7. **完整审计**：所有执行过程落盘，可追溯

## 许可证

MIT License
