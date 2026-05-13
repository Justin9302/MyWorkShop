# Workspace_1 使用指南（User Guide）

> **Cline 工作标准请参见：** `config/workspace_usage_guide.md`
> **上下文加载策略请参见：** `config/context-loading.yaml`
> **强制前置门禁请参见：** `constraints/baseline/context_intent_gate.yaml`

---

## 概述

这是一个 **Codex 工作空间**，集成了 AI 辅助开发环境，用于构建和管理多领域的工作流系统。它支持能源、金融、法律、商业运营等多个领域的自动化工作流执行、评估和治理。

---

## 核心能力

### 1. 工作流引擎

- **位置**: `workflows/` 目录
- **支持领域**: 能源、金融、法律、商业、运营
- **格式**: YAML 定义的工作流
- **运行方式**: `scripts/workflow_runner.py`

### 2. 评估系统 (Evaluation System)

- **位置**: `evaluators/` + `scripts/eval_runner.py`
- **功能**: 对工作流输出进行自动化评估
- **评估器类型**:
  - LLM Judge (`scripts/llm_judge.py`)
  - 规则检查 (`evaluators/rules/`)
  - 评分标准 (`evaluators/rubrics/`)

### 3. 中断处理系统

- **位置**: `scripts/interruption_handler.py`
- **功能**: 处理工作流执行中的中断事件
- **策略配置**: `config/interruption-policy.yaml`

### 4. 发布与回滚管理

- **发布**: `scripts/release_promote.sh`
- **回滚**: `scripts/rollback.sh`
- **发布配置**: `config/releases/`

### 5. 仪表盘

- **位置**: `scripts/dashboard.py`
- **功能**: 可视化工作流执行状态和评估结果

---

## 如何最大化发挥工作空间作用

### ✅ 高效使用技巧

#### 1. 任务执行控制

- **中止任务**: 在终端中按 `Ctrl+C` 可中止正在运行的脚本
- **暂停/恢复**: 工作流支持 checkpoint 机制，可在 `workflows/*.yaml` 中配置
- **中断处理**: 通过 `config/interruption-policy.yaml` 配置中断策略

#### 2. 插入用户想法和修正

- **直接编辑工作流 YAML**: 修改 `workflows/` 下的 YAML 文件可调整工作流步骤
- **修改评估标准**: 编辑 `evaluators/rubrics/` 下的 YAML 文件调整评分规则
- **添加测试用例**: 在 `tests/eval_cases/` 下添加新的评估测试用例
- **使用中断处理器**: 在运行时通过中断事件注入修正

#### 3. 工作流开发流程

```
创建/修改工作流 YAML → 运行 workflow_runner.py → 评估结果 → 迭代优化
```

#### 4. 评估与回归测试

```
运行 eval_runner.py → 生成评估报告 → 运行 regression_test.py → 检查回归
```

#### 5. 发布管理流程

```
修改 release YAML → 运行 release_promote.sh → 验证 → 必要时运行 rollback.sh
```

---

## 目录结构速查

| 目录           | 用途                              |
| -------------- | --------------------------------- |
| `workflows/`   | 各领域工作流定义 (YAML)           |
| `scripts/`     | 核心执行脚本 (Python/Shell)       |
| `evaluators/`  | 评估规则和评分标准                |
| `config/`      | 系统配置 (功能开关、路由、权限等) |
| `constraints/` | 约束规则 (基线、行业、司法管辖区) |
| `prompts/`     | 各领域的系统提示词                |
| `schemas/`     | JSON Schema 和 OpenAPI 定义       |
| `tests/`       | 各阶段测试用例                    |
| `docs/`        | 文档                              |
| `data/`        | 数据文件                          |
| `input/`       | 输入文件                          |
| `outputs/`     | 输出结果                          |
| `logs/`        | 日志文件                          |
| `runtime/`     | 运行时文件                        |

---

## 常用命令

```bash
# 运行工作流
python scripts/workflow_runner.py workflows/energy/new_energy_project_analysis.yaml

# 运行评估
python scripts/eval_runner.py --workflow <workflow-path>

# 运行回归测试
python scripts/regression_test.py

# 启动仪表盘
python scripts/dashboard.py

# 发布新版本
bash scripts/release_promote.sh

# 回滚
bash scripts/rollback.sh
```

---

## 工作流状态指示器

为了让你清晰区分"普通对话"和"工作流执行中"两种模式，系统提供了 `workflow_status_indicator.py` 状态指示器。

### 状态图标速查

| 图标 | 状态                     | 含义                           |
| ---- | ------------------------ | ------------------------------ |
| 🆕   | created                  | 工作流已创建                   |
| ❓   | context_intent_pending   | 等待意图确认                   |
| ✅   | context_intent_confirmed | 意图已确认                     |
| ⚡   | running                  | **执行中** — AI 正在按步骤执行 |
| ⏸️   | workflow_pause           | **已暂停** — 等待用户输入      |
| 🛑   | interrupted_by_user      | 用户中断                       |
| 🚫   | cancelled_by_user        | 用户取消                       |
| ✅   | completed                | 已完成                         |
| ❌   | failed                   | 失败                           |

### 使用方式

```bash
# 1. 查看当前工作流状态（简洁）
python scripts/workflow_status_indicator.py status --snapshot runtime/workflow_runtime/snapshot_xxx.json

# 2. 生成状态横幅（醒目，适合嵌入对话）
python scripts/workflow_status_indicator.py banner --snapshot runtime/workflow_runtime/snapshot_xxx.json

# 3. 查看待回答的问题
python scripts/workflow_status_indicator.py pending --snapshot runtime/workflow_runtime/snapshot_xxx.json

# 4. 查看执行进度
python scripts/workflow_status_indicator.py progress --snapshot runtime/workflow_runtime/snapshot_xxx.json

# 5. 列出所有活跃的工作流
python scripts/workflow_status_indicator.py list-active

# 6. 生成完整状态报告（Markdown）
python scripts/workflow_status_indicator.py report --snapshot runtime/workflow_runtime/snapshot_xxx.json -o OUTPUT/workflow_status_report.md
```

### 状态横幅示例

当工作流执行中时，横幅会显示：

```
╔══════════════════════════════════════════════════════════════╗
║  ⚡  工作流状态: 执行中
║
║  工作流: new_energy_project_analysis
║  运行 ID: run_abc123
║  当前节点: 市场数据验证
║  进度: 2/14
║
║  💡 当前处于工作流执行模式，AI 正在按步骤执行任务
╚══════════════════════════════════════════════════════════════╝
```

当工作流暂停等待输入时：

```
╔══════════════════════════════════════════════════════════════╗
║  ⏸️  工作流状态: 已暂停（等待用户输入）
║
║  工作流: new_energy_project_analysis
║  运行 ID: run_abc123
║  当前节点: confirm_intent
║  进度: 1/14
║
║  ⏸️  等待用户输入:
║     - 原因: missing_required_input
║       ❓ 请确认项目类型（纯光伏/纯储能/光储混合）
║       ❓ 请提供核心技术参数（MWp/MW/MWh/时长/化学类型）
║
║  💡 工作流已暂停，请回复补充信息以继续执行
╚══════════════════════════════════════════════════════════════╝
```

### 如何集成到对话中

当 AI 助手开始执行工作流时，它会：

1. 创建运行快照（`runtime/workflow_runtime/snapshot_xxx.json`）
2. 在每次回复开头显示状态横幅，让你知道当前处于工作流模式
3. 当需要你输入时，横幅会显示待回答问题
4. 工作流结束后，横幅会提示"工作流已结束"

---

## 与 AI 助手协作的最佳实践

1. **明确任务范围**: 告诉 AI 助手你想修改哪个领域、哪个工作流
2. **提供上下文**: 引用相关文件路径，帮助 AI 快速定位
3. **分步执行**: 复杂任务分步骤进行，每步确认结果
4. **利用测试**: 修改后运行相关测试验证正确性
5. **版本控制**: 所有修改通过 Git 管理，便于回滚

---

## 注意事项

- 修改 `config/` 下的配置文件会影响系统行为，请谨慎操作
- 发布前务必运行回归测试
- 中断处理需要预先配置策略
- 评估结果存储在 `outputs/` 目录
