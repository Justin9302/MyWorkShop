# Codex → VS Code 迁移方案

## 迁移概览

本方案将原 Codex 环境下的「AI 辅助行业工作流平台」资产仓库，迁移到 VS Code + GitHub Copilot 环境中运行。迁移保持平台原有架构设计不变，仅将运行时依赖从 Codex 迁移到 VS Code 生态。

## 当前项目状态

- **项目名称**: AI Work Platform (AI 辅助行业工作流平台)
- **当前阶段**: Stage 2 - 核心平台配置
- **版本**: `release_2026_05_05_001` (draft)
- **Git Commit**: `f686ea3`
- **资产规模**:
  - 12 个工作流 (legal/business/finance/operations)
  - 8 个约束包 (4 baseline + 4 industry)
  - 12 个 Prompt 模板
  - 6 个 JSON Schema
  - 5 个配置模块 (model-routing, context-loading, mcp-tools, feature-flags, permissions)
  - 1 个评估器

## Codex vs VS Code 差异分析

| 维度             | Codex 环境                                                                                        | VS Code 环境                                                |
| ---------------- | ------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| **模型入口指令** | `docs/model_context.md` 作为 entrypoint                                                           | `.github/copilot-instructions.md` + `.vscode/settings.json` |
| **MCP 工具**     | Codex MCP runtime (`filesystem_read`, `filesystem_write`, `git_status`, `fetch_official_sources`) | VS Code MCP 扩展 + Copilot 原生工具                         |
| **工作流执行**   | Codex 工作流运行时引擎                                                                            | VS Code Tasks + Copilot Agent 模式                          |
| **中断/恢复**    | Codex interruption-policy 原生支持                                                                | 通过 Copilot 对话中断 + checkpoint 实现                     |
| **上下文加载**   | Codex context-loading 策略引擎                                                                    | Copilot 的 `#file` 引用 + 分层加载策略                      |
| **项目配置**     | 项目级配置文件                                                                                    | `.vscode/` 目录 (settings, tasks, extensions)               |
| **Git 边界**     | `.vscode/` 在 .gitignore 中排除                                                                   | `.vscode/` 应纳入版本管理（仅共享配置）                     |

## 迁移策略

### 原则

1. **平台资产不变**: workflows/, constraints/, prompts/, schemas/, evaluators/ 目录结构与内容保持不变
2. **配置平移**: config/ 下的 YAML 配置仅做路径引用更新
3. **入口适配**: model_context.md 的内容映射到 Copilot 指令体系
4. **工具映射**: Codex MCP 工具声明映射到 VS Code MCP + Copilot 原生能力
5. **渐进迁移**: 先建 VS Code 基础设施，再逐步验证每个工作流

### 阶段划分

#### Phase 1: VS Code 基础设施搭建 ✅ (已完成 2026-05-05)

- [x] 创建 `.vscode/settings.json` — 工作区设置
- [x] 创建 `.vscode/tasks.json` — 常用任务自动化
- [x] 创建 `.vscode/extensions.json` — 推荐扩展
- [x] 创建 `.github/copilot-instructions.md` — Copilot 指令
- [x] 更新 `.gitignore` — 纳入 `.vscode/` 共享配置

#### Phase 2: 配置适配 ✅ (已完成 2026-05-05)

- [x] 更新 `config/mcp-tools.yaml` — 添加 `vscode_impl`/`vscode_tools` 映射 + `environments` 声明
- [x] 更新 `config/active-release.yaml` — 添加 `copilot_entrypoint`/`vscode_mcp_config` + 迁移记录
- [x] 创建 `.vscode/mcp.json` — 3 个 MCP Server: filesystem/fetch/git

#### Phase 3: 工作流验证 ✅ (已完成 2026-05-05)

- [x] 逐个验证 12 个工作流的结构完整性 (详见 `docs/phase3_validation_report.md`)
- [x] 验证中断/恢复机制 — 18 个中断条件均为 coherent
- [x] 验证上下文分层加载 — 12/12 符合分层策略
- [x] 验证约束规则触发 — 0 缺失约束, 0 缺失 Prompt
- [x] 结果: **12/12 PASS**, 2 minor warnings (非阻塞)

#### Phase 4: 评估器集成 ✅ (已完成 2026-05-05)

- [x] 评估器从 Sidecar (HTTP POST /evaluation/run) 适配到 VS Code Task 模式
- [x] 创建 `scripts/eval_runner.py` — CLI 评估运行器 (单次/批量)
- [x] 创建 `tests/eval_cases/synthetic/run_snapshot_sample_001.json` — 测试快照
- [x] 更新 `.vscode/tasks.json` — 3 个评估 Task
- [x] 运行验证: Score=0.75, Risk=medium, Passed=True

## 迁移完成 🎉

## 文件映射表

| Codex 原路径            | VS Code 目标路径                  | 说明                     |
| ----------------------- | --------------------------------- | ------------------------ |
| `docs/model_context.md` | `.github/copilot-instructions.md` | Copilot 系统指令         |
| —                       | `.vscode/settings.json`           | VS Code 工作区设置       |
| —                       | `.vscode/tasks.json`              | 自动化任务               |
| —                       | `.vscode/extensions.json`         | 推荐扩展列表             |
| —                       | `.vscode/mcp.json`                | MCP 服务器配置           |
| `config/mcp-tools.yaml` | 保留并更新                        | 添加 VS Code 工具映射    |
| `.gitignore`            | 更新                              | 移除 `.vscode/` 排除规则 |

## MCP 工具映射

| Codex MCP Tool           | VS Code 映射                                   |
| ------------------------ | ---------------------------------------------- |
| `filesystem_read`        | Copilot 原生文件读取能力                       |
| `filesystem_write`       | Copilot 原生文件写入能力                       |
| `git_status`             | VS Code Git 扩展 + Copilot `get_changed_files` |
| `fetch_official_sources` | VS Code MCP `fetch` + Copilot `fetch_webpage`  |

## 工作流执行模式变化

### Codex 模式

```
用户输入 → Codex Runtime → context_intent_gate → 分层加载 → 工作流步骤 → 中断/恢复 → 输出 → 评估Sidecar
```

### VS Code 模式

```
用户输入 → Copilot Agent → copilot-instructions.md (gate rules) → #file 分层引用 → Task执行步骤 → 对话中断 → 输出 → Task评估脚本
```

Copilot Agent 的心智模型与 Codex Workflow Runner 不同：

- Codex 是显式工作流引擎，严格按 YAML steps 执行
- Copilot Agent 是自主推理代理，通过 instructions 引导行为

因此工作流 YAML 从「执行指令」变为「行为约束指南」，Copilot 在 instructions 指导下自主完成各步骤。

## 风险评估

| 风险                       | 等级 | 缓解措施                                |
| -------------------------- | ---- | --------------------------------------- |
| Copilot 不严格遵循步骤顺序 | 中   | 在 copilot-instructions 中用强约束语言  |
| 中断/恢复机制差异          | 中   | 利用 Copilot 对话中断 + checkpoint 模式 |
| 上下文预算差异             | 低   | Copilot 上下文窗口足够大                |
| Schema 严格输出差异        | 低   | Copilot 支持结构化输出                  |
| MCP 工具行为差异           | 低   | 工具能力基本等价                        |

## 迁移完成标准

- [x] `.vscode/` 配置就绪且正常工作 (settings.json, tasks.json, extensions.json, mcp.json)
- [x] `.github/copilot-instructions.md` 配置完成 (settings.json 中 `useInstructionFiles: true`)
- [ ] 至少 3 个工作流在 Copilot Chat 中实际运行验证 (结构已验证，需用户手动测试)
- [x] `.gitignore` 正确管理 VS Code 配置
- [x] 所有原有平台资产文件未被修改（仅添加新文件）
- [x] `active-release.yaml` 记录迁移变更
- [x] `mcp-tools.yaml` 添加 VS Code 工具映射
- [x] Phase 3: 工作流验证 (12/12 PASS, report: `docs/phase3_validation_report.md`)
- [x] Phase 4: 评估器集成 (scripts/eval_runner.py + VS Code Tasks)
