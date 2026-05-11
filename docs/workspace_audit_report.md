# Workspace 规则与工作流审计报告

**日期：** 2026-05-11
**审计范围：** 全部 config/、docs/、constraints/、workflows/、lattice/ 及关联脚本
**审计目标：** 识别规则间的矛盾、冗余、死角，评估 Skill 与 MCP 需求

---

## 一、规则与工作流矛盾分析

### 1.1 `workspace_usage_guide.md` 与 `config/context-loading.yaml` 的冲突

| 文件                                               | 要求                                                                                                                           |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `config/workspace_usage_guide.md` (Cline 工作标准) | 5步法：理解意图 → 行业对齐 → 输出初稿 → 主动确认 → 优化迭代                                                                    |
| `config/context-loading.yaml`                      | 强制启动序列：`docs/model_context.md` → `config/active-release.yaml` → `README.md` → `docs/current_workspace_creation_plan.md` |
| `constraints/baseline/context_intent_gate.yaml`    | 强制前置门禁：读取 active-release、context-loading、human_review                                                               |

**矛盾点：**

- `workspace_usage_guide.md` 的"理解意图"步骤没有明确要求读取 `model_context.md` 和 `active-release.yaml`
- `context-loading.yaml` 的强制启动序列与 `workspace_usage_guide.md` 的5步法没有对齐
- 存在**两套并行的工作标准**：一套在 `config/workspace_usage_guide.md`，另一套在 `docs/workspace_usage_guide.md`

**建议：**

- 合并两套 `workspace_usage_guide.md`，消除重复
- 将 `context-loading.yaml` 的强制启动序列显式嵌入到工作标准的"理解意图"步骤中
- 统一入口：所有任务必须先读 `model_context.md` → `active-release.yaml` → `context_intent_gate.yaml`

### 1.2 `docs/workspace_usage_guide.md` 与 `config/workspace_usage_guide.md` 的冗余

**问题：** 存在两个 `workspace_usage_guide.md`：

- `config/workspace_usage_guide.md` — Cline 工作标准（5步法 + 复盘）
- `docs/workspace_usage_guide.md` — Workspace 使用指南（目录结构 + 命令速查）

**冗余点：**

- 两者都包含"如何高效使用"的内容
- 两者都包含目录结构说明
- 两者都没有互相引用

**建议：**

- `config/workspace_usage_guide.md` 保留为**Cline 行为标准**（如何执行任务）
- `docs/workspace_usage_guide.md` 保留为**用户使用指南**（如何操作工作空间）
- 在两者头部添加互相引用链接

### 1.3 `config/feature-flags.yaml` 与 `config/active-release.yaml` 的状态不一致

| 配置项                | feature-flags.yaml | active-release.yaml                           |
| --------------------- | ------------------ | --------------------------------------------- |
| `evaluation_sidecar`  | `enabled: false`   | 在 active_components 中列出                   |
| `auto_update_prompts` | `enabled: false`   | 未提及                                        |
| `mcp_tool_registry`   | `enabled: true`    | 在 governance 中引用 mcp-tools.yaml           |
| `human_review_gate`   | `enabled: true`    | 在 governance 中引用 interruption-policy.yaml |

**矛盾点：**

- `evaluation_sidecar` 在 feature-flags 中禁用，但 active-release 中列出了完整的 evaluation 组件（runner、API、test snapshots）
- 没有明确的机制说明 feature-flags 和 active-release 哪个优先级更高

**建议：**

- 明确 feature-flags 是 active-release 的子集，active-release 中的 `governance` 引用优先级高于 feature-flags
- 在 active-release.yaml 中添加 `feature_flags_override` 字段

### 1.4 `config/model-routing.yaml` 与 `config/active-release.yaml` 的版本脱节

**问题：**

- `model-routing.yaml` 版本 `0.2.0`，status `draft`
- `active-release.yaml` 引用 `config/model-routing.yaml` 作为 governance 的一部分
- 但 model-routing 中定义的 `high_risk_review`、`business_validation` 等路由规则，在 active-release 中没有对应的版本追踪

**建议：**

- 将 model-routing 的版本号纳入 active-release 的版本追踪
- 在 active-release 中添加 `model_routing_version` 字段

---

## 二、冗余分析

### 2.1 文档冗余

| 冗余组   | 文件                                                                                  | 重叠内容           |
| -------- | ------------------------------------------------------------------------------------- | ------------------ |
| 工作标准 | `config/workspace_usage_guide.md` vs `docs/workspace_usage_guide.md`                  | 使用说明、目录结构 |
| 项目概览 | `README.md` vs `docs/model_context.md` vs `docs/workspace_usage_guide.md`             | 项目描述、目录结构 |
| 创建计划 | `docs/current_workspace_creation_plan.md` vs `docs/workspace_plan.md`                 | 阶段划分、实施顺序 |
| 评估系统 | `docs/eval.md` vs `docs/evaluation_sidecar.md` vs `docs/evaluation_evolution_plan.md` | 评估架构           |

**建议：**

- 建立文档索引文件 `docs/INDEX.md`，明确每份文档的职责和受众
- 消除跨文档的重复内容，改为引用关系

### 2.2 配置冗余

| 冗余组     | 文件                                                                                  | 重叠内容           |
| ---------- | ------------------------------------------------------------------------------------- | ------------------ |
| 中断策略   | `config/interruption-policy.yaml` vs `docs/current_workspace_creation_plan.md` 第13节 | 中断类型、恢复流程 |
| 上下文加载 | `config/context-loading.yaml` vs `docs/current_workspace_creation_plan.md` 第12节     | 加载层、加载策略   |
| MCP 工具   | `config/mcp-tools.yaml` vs `docs/current_workspace_creation_plan.md` 第11节           | 工具列表、权限     |

**建议：**

- `config/` 下的 YAML 文件是**权威来源**，`docs/` 中的描述应只保留设计原理和决策理由
- 在 `docs/` 文档中添加 `> 配置详情请参见 config/xxx.yaml` 的引用标记

### 2.3 Schema 冗余

**问题：** `schemas/` 目录下有 12 个 JSON Schema 文件，但部分 Schema 之间存在字段重叠：

- `run_snapshot.schema.json` 和 `solar_financial_run_snapshot.schema.json` 高度重叠
- `interruption_event.schema.json` 中的字段在 `run_snapshot.schema.json` 中也有定义

**建议：**

- 建立 Schema 继承/引用机制（使用 `$ref`）
- 将通用字段提取到基础 Schema

---

## 三、死角分析

### 3.1 缺少"任务启动检查清单"的自动化

**问题：** `config/workspace_usage_guide.md` 定义了一个检查清单（5步法），但：

- 没有脚本或工具强制检查这些步骤是否完成
- 没有机制在任务启动时自动加载必要的上下文
- 依赖 AI 的自觉性来遵守

**建议：**

- 创建一个 `scripts/task_init_check.py` 脚本，在每次任务启动时运行
- 脚本检查：是否已读 model_context.md、active-release.yaml、context_intent_gate.yaml
- 脚本输出：当前 release 版本、活跃组件列表、待办检查项

### 3.2 缺少"规则冲突检测"机制

**问题：** 当前有多个规则来源：

- `constraints/baseline/` — 6 个基线约束
- `constraints/industries/` — 5 个行业约束
- `constraints/jurisdictions/` — 4 个司法管辖区约束
- `config/feature-flags.yaml` — 功能开关
- `config/permissions.yaml` — 权限规则
- `config/interruption-policy.yaml` — 中断策略

**死角：** 没有机制检测这些规则之间的冲突。例如：

- 一个约束说"必须人工审批"，另一个说"自动执行"
- 一个 feature-flag 禁用了某个功能，但 workflow 仍然引用了它

**建议：**

- 创建 `scripts/rule_conflict_detector.py`，定期扫描所有规则文件
- 定义规则优先级：`constraint > permission > feature-flag > workflow`
- 在 active-release 发布前自动运行冲突检测

### 3.3 缺少"跨对话记忆"的自动化

**问题：** `config/session-tracking.yaml` 和 `docs/user_profile.md` 建立了跨对话记忆系统，但：

- 更新这些文件完全依赖手动操作
- 没有自动化的"会话结束总结"脚本
- 新对话启动时没有自动加载上次会话的上下文

**建议：**

- 创建 `scripts/session_summarizer.py`，在每次重要任务完成后自动运行
- 脚本自动更新 `session-tracking.yaml` 和 `user_profile.md`
- 在 `context-loading.yaml` 中添加"上次会话摘要"作为启动加载项

### 3.4 缺少"Lattice 框架触发条件"的自动化

**问题：** `docs/user_profile.md` 中定义了 Lattice 触发条件：

> "每次新对话启动时，或用户明确要求时，必须采用 Lattice 工作方法"

但：

- 没有机制在新对话启动时自动检测是否需要 Lattice
- 没有脚本判断当前任务是否适合 Lattice 框架
- Lattice 和普通工作流之间的切换没有明确的决策树

**建议：**

- 创建 `scripts/lattice_trigger_check.py`，在新对话启动时运行
- 脚本输出：是否推荐使用 Lattice、推荐理由、备选方案
- 在 `context_intent_gate.yaml` 中添加 Lattice 触发判断步骤

### 3.5 缺少"测试覆盖率"的可见性

**问题：** `tests/` 目录下有多个测试阶段（phase7a-7f, phase8, phase9），但：

- 没有统一的测试运行入口
- 没有测试覆盖率报告
- 没有测试结果的历史追踪

**建议：**

- 创建 `scripts/run_all_tests.sh`，一键运行所有测试
- 创建 `scripts/test_coverage_report.py`，生成覆盖率报告
- 将测试结果写入 `outputs/test_reports/`

---

## 四、必须安装的 Skill 与 MCP

### 4.1 必须的 MCP 服务器

基于当前工作空间的需求，以下 MCP 服务器是**必须安装**的：

| MCP 服务器     | 用途                           | 优先级 | 理由               |
| -------------- | ------------------------------ | ------ | ------------------ |
| **Filesystem** | 读写项目文件、配置文件、工作流 | P0     | 所有任务的基础操作 |
| **Git**        | 版本控制、diff、tag、回滚      | P0     | 版本治理的核心依赖 |
| **GitHub**     | 创建 PR、管理 Issue、审查变更  | P0     | 远程仓库协作       |
| **Fetch**      | 读取公开标准、官方文档         | P0     | 行业对齐步骤需要   |
| **Memory**     | 保存跨对话的偏好和决策         | P1     | 跨对话记忆系统     |
| **Puppeteer**  | 渲染和截图 HTML 仪表盘         | P2     | dashboard 可视化   |
| **SQLite**     | 查询运行快照和评估报告         | P2     | 后续数据分析       |

**当前状态检查：**

- `config/mcp-tools.yaml` 中已定义 filesystem_read、filesystem_write、git_status、fetch_official_sources
- 但实际 `.vscode/mcp.json` 中是否已配置这些 MCP 服务器需要验证
- Memory MCP 尚未在配置中登记

### 4.2 必须的 VS Code 扩展（Skill）

| 扩展                     | 用途                    | 优先级 | 理由                            |
| ------------------------ | ----------------------- | ------ | ------------------------------- |
| **YAML** (Red Hat)       | YAML 文件校验、自动补全 | P0     | 大量 YAML 配置文件              |
| **Python** (Microsoft)   | Python 开发、调试、测试 | P0     | 核心脚本语言                    |
| **JSON Schema**          | Schema 校验、自动补全   | P0     | 12 个 JSON Schema 文件          |
| **GitLens**              | Git 历史、blame、diff   | P1     | 版本治理                        |
| **Markdown Preview**     | 文档预览                | P1     | 大量 Markdown 文档              |
| **ShellCheck**           | Shell 脚本检查          | P1     | release_promote.sh、rollback.sh |
| **GitHub Pull Requests** | PR 管理                 | P1     | 远程协作                        |
| **Docker**               | 容器化运行              | P2     | 后续部署                        |

### 4.3 必须的 Python 包

| 包            | 用途             | 优先级 | 当前状态               |
| ------------- | ---------------- | ------ | ---------------------- |
| PyYAML        | YAML 解析        | P0     | 已安装（lattice 依赖） |
| jsonschema    | JSON Schema 校验 | P0     | 需要确认               |
| pytest        | 测试框架         | P0     | 需要确认               |
| requests      | HTTP 请求        | P1     | 需要确认               |
| flask/fastapi | 评估 API         | P2     | 需要确认               |

---

## 五、优先级排序与实施建议

### P0 — 立即修复（影响日常执行）

1. **合并两套 workspace_usage_guide.md** — 消除矛盾入口
2. **创建 task_init_check.py** — 任务启动时自动检查上下文加载
3. **安装 Filesystem + Git + GitHub MCP** — 核心操作依赖
4. **安装 YAML + Python + JSON Schema 扩展** — 开发环境基础
5. **统一 context-loading.yaml 与 workspace_usage_guide.md 的启动序列**

### P1 — 本周内修复（提升效率）

1. **创建 rule_conflict_detector.py** — 检测规则冲突
2. **创建 session_summarizer.py** — 自动更新跨对话记忆
3. **创建文档索引 docs/INDEX.md** — 消除文档冗余
4. **安装 Memory MCP** — 跨对话记忆
5. **安装 GitLens + Markdown Preview 扩展**

### P2 — 本月内修复（完善体系）

1. **创建 run_all_tests.sh** — 统一测试入口
2. **创建 test_coverage_report.py** — 测试覆盖率报告
3. **创建 lattice_trigger_check.py** — Lattice 触发判断
4. **安装 Puppeteer + SQLite MCP** — 仪表盘和数据分析
5. **Schema 继承/引用机制** — 消除 Schema 冗余

---

## 六、总结

### 主要发现

| 类别       | 数量 | 严重程度                               |
| ---------- | ---- | -------------------------------------- |
| 规则矛盾   | 4 处 | 2 处严重（工作标准冲突、入口不统一）   |
| 冗余       | 3 组 | 1 组严重（两套 workspace_usage_guide） |
| 死角       | 5 处 | 2 处严重（无启动检查、无规则冲突检测） |
| 必须 MCP   | 5 个 | 3 个 P0（Filesystem、Git、GitHub）     |
| 必须 Skill | 3 个 | 3 个 P0（YAML、Python、JSON Schema）   |

### 核心问题

1. **入口不统一**：存在两套工作标准，且都没有强制关联到 `context_intent_gate.yaml`
2. **缺少自动化**：规则检查、冲突检测、会话总结都依赖手动操作
3. **MCP 配置不完整**：`config/mcp-tools.yaml` 定义了工具，但实际 MCP 服务器可能未安装
4. **文档体系混乱**：多份文档内容重叠，没有清晰的索引和引用关系

### 建议下一步

1. 立即合并两套 `workspace_usage_guide.md`，统一任务执行标准
2. 安装 P0 级别的 MCP 服务器和 VS Code 扩展
3. 创建 `scripts/task_init_check.py` 作为任务启动的强制检查点
4. 创建 `docs/INDEX.md` 建立文档索引体系

---

_版本：v1.0 | 日期：2026-05-11 | 审计人：Cline_
