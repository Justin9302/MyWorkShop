# 文档索引 (Documentation Index)

> 本文档是 Workspace_1 所有文档的唯一入口索引。
> 最后更新：2026-05-22

---

## 快速导航

| 你想做什么？            | 看这里                                    |
| ----------------------- | ----------------------------------------- |
| 了解项目全景            | `docs/model_context.md`                   |
| 查看当前版本和活跃组件  | `config/active-release.yaml`              |
| 了解 Cline 如何执行任务 | `config/workspace_usage_guide.md`         |
| 了解如何操作工作空间    | `docs/workspace_usage_guide.md`           |
| 查看平台创建计划        | `docs/current_workspace_creation_plan.md` |
| 查看平台架构设计        | `docs/workspace_plan.md`                  |
| 查看 Git 和回滚策略     | `docs/gitman.md`                          |
| 查看评估系统设计        | `docs/eval.md`                            |
| 查看用户配置文件        | `docs/user_profile.md`                    |
| 查看会话历史            | `config/session-tracking.yaml`            |
| 查看任务复盘            | `docs/retrospective_YYYYMMDD.md`          |
| 查看审计报告            | `docs/workspace_audit_report.md`          |
| 查看文档同步依赖        | `docs/sync-manifest.yaml`                 |
| 打开工作空间            | `Workspace_1.code-workspace`              |

---

## 文档分类

### 🏗️ 项目全景（必读）

| 文档                                      | 用途                                 | 优先级                 | 关联配置                     |
| ----------------------------------------- | ------------------------------------ | ---------------------- | ---------------------------- |
| `docs/model_context.md`                   | 项目全景、当前阶段、活跃组件版本     | **P0（每次任务必读）** | `config/active-release.yaml` |
| `config/active-release.yaml`              | 当前发布版本、治理配置、活跃组件列表 | **P0（每次任务必读）** | `config/releases/`           |
| `README.md`                               | 项目概述                             | **P0（每次任务必读）** | —                            |
| `docs/current_workspace_creation_plan.md` | 平台治理规则、创建计划、验收标准     | **P0（每次任务必读）** | 所有 config/                 |

### ⚙️ 工作标准与流程

| 文档                                            | 用途                                               | 优先级                 |
| ----------------------------------------------- | -------------------------------------------------- | ---------------------- |
| `config/workspace_usage_guide.md`               | **Cline 行为标准** — 5步法 + 强制上下文加载 + 复盘 | **P0（每次任务必读）** |
| `docs/workspace_usage_guide.md`                 | **用户操作指南** — 目录结构、命令速查、最佳实践    | P1（用户参考）         |
| `config/context-loading.yaml`                   | 上下文加载策略 — 分层加载、启动序列、审计          | P1（技术参考）         |
| `constraints/baseline/context_intent_gate.yaml` | 强制前置门禁规则                                   | P1（技术参考）         |

### 📐 架构设计

| 文档                                | 用途                   | 优先级         |
| ----------------------------------- | ---------------------- | -------------- |
| `docs/workspace_plan.md`            | 平台架构设计文档       | P2（架构参考） |
| `docs/gitman.md`                    | Git 版本治理与回滚策略 | P2（架构参考） |
| `docs/eval.md`                      | 评估系统设计文档       | P2（架构参考） |
| `docs/evaluation_sidecar.md`        | 评估旁路服务设计       | P2（架构参考） |
| `docs/evaluation_evolution_plan.md` | 评估系统进化计划       | P2（架构参考） |
| `docs/release_governance.md`        | 发布治理文档           | P2（架构参考） |

### 👤 用户与历史

| 文档                           | 用途                                        | 优先级             |
| ------------------------------ | ------------------------------------------- | ------------------ |
| `docs/user_profile.md`         | 用户配置文件 — 工作习惯、偏好、会话历史     | P1（每次任务参考） |
| `config/session-tracking.yaml` | 会话跟踪 — 跨对话记忆、关键决策、项目里程碑 | P1（每次任务参考） |
| `docs/retrospective_*.md`      | 任务复盘记录                                | P2（复盘参考）     |

### 🔍 审计与评估

| 文档/工作流                                        | 用途                                     | 优先级         |
| -------------------------------------------------- | ---------------------------------------- | -------------- |
| `docs/workspace_audit_report.md`                   | 工作空间审计报告（规则矛盾、冗余、死角） | P1（治理参考） |
| `workflows/operations/system_health_check.yaml`    | 系统健康检查与进化工作流（按需触发）     | P1（治理参考） |
| `prompts/operations/system_health_check.system.md` | 系统健康检查系统提示词                   | P1（治理参考） |
| `schemas/health_check_report.schema.json`          | 健康检查报告 Schema                      | P1（治理参考） |
| `docs/phase3_validation_report.md`                 | Phase 3 验证报告                         | P2（历史参考） |
| `docs/codex_to_vscode_migration.md`                | Codex 到 VS Code 迁移记录                | P2（历史参考） |

### 🔄 同步管理

| 文档/脚本                 | 用途                                    | 优先级         |
| ------------------------- | --------------------------------------- | -------------- |
| `docs/sync-manifest.yaml` | 文档同步依赖清单 — 声明文件间依赖关系   | P1（治理参考） |
| `scripts/sync_checker.py` | 文档同步检查器 — 自动检查关联文件一致性 | P1（治理参考） |

---

## 配置索引

| 配置文件                          | 用途                   | 关联文档                                     |
| --------------------------------- | ---------------------- | -------------------------------------------- |
| `config/active-release.yaml`      | 当前发布版本和活跃组件 | `docs/model_context.md`                      |
| `config/context-loading.yaml`     | 上下文加载策略         | `config/workspace_usage_guide.md`            |
| `config/feature-flags.yaml`       | 功能开关               | `config/active-release.yaml`                 |
| `config/model-routing.yaml`       | 模型路由策略           | `config/active-release.yaml`                 |
| `config/permissions.yaml`         | 权限控制               | `constraints/baseline/tool_permissions.yaml` |
| `config/mcp-tools.yaml`           | MCP 工具注册表         | `.vscode/mcp.json`                           |
| `config/interruption-policy.yaml` | 中断与恢复策略         | `scripts/interruption_handler.py`            |
| `config/session-tracking.yaml`    | 会话跟踪               | `docs/user_profile.md`                       |
| `config/rollout-policy.yaml`      | 灰度发布策略           | `scripts/rollout_manager.py`                 |
| `config/eval-set-config.yaml`     | 评估集自动分类规则     | `scripts/eval_set_manager.py`                |
| `config/dashboard-config.yaml`    | 质量仪表盘配置         | `scripts/dashboard.py`                       |

---

## 目录结构速查

```
Workspace_1/
├── config/          # 系统配置（版本化）
│   └── releases/    #   发布清单
├── constraints/     # 约束规则包
│   ├── baseline/    #   基线约束（6个）
│   ├── industries/  #   行业约束（5个）
│   ├── jurisdictions/ # 司法管辖区约束（4个）
│   └── countries/   #   国家约束（3个 + 模板）
├── docs/            # 文档（本文档所在目录）
├── evaluators/      # 评估规则和评分标准
│   ├── rules/       #   规则检查（3个）
│   └── rubrics/     #   评分标准（6个）
├── lattice/         # Lattice 晶格框架
│   ├── schemas/     #   Schema 定义（6个）
│   ├── scripts/     #   核心引擎（5个）
│   ├── workflows/   #   工作流定义（3个）
│   ├── templates/   #   模板文件（3个）
│   └── examples/    #   示例（6个）
├── prompts/         # 系统提示词（含 country/ 领域，共17个）
├── schemas/         # JSON Schema 和 OpenAPI 定义（12个）
├── scripts/         # 核心执行脚本（含 MCP 工具脚本，共20+个）
├── tests/           # 测试用例（8个阶段 + eval_cases）
│   ├── eval_cases/  #   评估样本（synthetic/ 6个）
│   ├── regression/  #   回归测试（constraints/prompts/workflows）
│   ├── phase7a/     #   LLM-as-Judge
│   ├── phase7b/     #   动态评估集
│   ├── phase7c/     #   候选变更管线
│   ├── phase7d/     #   沙箱回归测试
│   ├── phase7e/     #   灰度发布管理
│   ├── phase7f/     #   质量仪表盘
│   ├── phase8/      #   工作流编排引擎
│   └── phase9/      #   中断处理与恢复
├── workflows/       # 工作流定义（16个，含 country/ + system_health_check）
├── data/            # 数据文件（Git 排除）
├── input/           # 输入文件（Git 排除）
├── logs/            # 日志文件（Git 排除）
├── outputs/         # 输出结果（Git 排除）
└── runtime/         # 运行时文件（Git 排除）
```

---

## 文档维护规则

1. **新增文档**：必须在本文档中添加索引条目
2. **文档更新**：更新内容后同步更新本文档的描述
3. **文档废弃**：在本文档中标记为 `[DEPRECATED]` 并说明替代文档
4. **优先级标记**：P0 = 每次任务必读，P1 = 任务相关时参考，P2 = 架构/历史参考

---

_版本：v1.2 | 日期：2026-05-22 | 维护人：Cline_
