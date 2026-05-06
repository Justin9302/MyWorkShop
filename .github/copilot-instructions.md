# Copilot Instructions — AI Work Platform

This file is the required entry point for GitHub Copilot working in this repository. It replaces `docs/model_context.md` as the active instruction source when using VS Code + Copilot.

## Software Identity

This workspace is an **AI-assisted industry workflow platform asset repository**.

It manages **how the platform works**, not the real business content processed by the platform. The product direction is **not** a general AI chat application. It is an industry workflow platform with constraint packs, auditable reference material, structured outputs, evaluations, and version governance.

Core operating principle:

- The model (Copilot) performs reasoning and generation.
- The platform owns boundaries, evidence, permissions, process, auditability, and rollback.

## Current Stage

- **Release**: `release_2026_05_05_001` (draft)
- **Stage**: Stage 2 — Core platform configuration and first workflow set
- **Environment**: VS Code + GitHub Copilot (migrated from Codex)

## Mandatory Startup Reading

Before answering project-level questions, modifying platform assets, creating workflows, adding rules, or proposing implementation plans, read these files in order:

1. `config/active-release.yaml` — active component versions
2. `README.md` — project overview
3. `docs/current_workspace_creation_plan.md` — platform governance rules

Then load only as needed:

- `docs/workspace_plan.md` — overall platform architecture
- `docs/gitman.md` — Git and rollback boundaries
- `docs/eval.md` — evaluation and evolution design
- `docs/codex_to_vscode_migration.md` — migration reference
- `schemas/workflow.schema.json` — workflow definition contract
- `schemas/run_snapshot.schema.json` — runtime record contract

## Working Rules for Copilot

Treat this repository as the **source of truth** for platform capability assets.

### Do:

- Preserve the boundary between platform assets and business content.
- Prefer versioned workflows, constraints, prompts, schemas, tests, and release manifests.
- Read `config/active-release.yaml` before assuming any component is active.
- Use staged, task-specific context loading rather than loading every document at once.
- Record or design for auditability, traceability, human review, and rollback.
- Keep high-risk actions behind explicit human approval.
- Use structured outputs (JSON/YAML) for all key deliverables.

### Do NOT:

- Store customer documents, user uploads, raw feedback, runtime logs, model outputs, vector indexes, secrets, or local environment files in Git.
- Treat planning examples as active production workflows.
- Assume any MCP tool is project-approved until it appears in `config/mcp-tools.yaml`.
- Let an evaluation process directly modify production prompts, constraints, workflows, or model routing.

## Mandatory Context & Intent Gate

Every workflow or platform-change task **MUST** begin with a context and intent gate. Before executing any task, identify:

1. **User goal** — what are they trying to accomplish?
2. **Industry & jurisdiction** — legal/business/finance/operations + region
3. **Risk level** — low/medium/high/critical
4. **Target output** — what should be produced?
5. **Active release & versions** — from `config/active-release.yaml`
6. **Required assets** — which workflow, constraints, prompts, schemas, tools are needed?
7. **Missing information** — what do you still need to know?
8. **Approval needs** — does this require human review?

**If the task is high risk, under-specified, permission-sensitive, or changes platform behavior — PAUSE and ask the user to confirm before proceeding.**

## Context Loading Policy (Layered Loading)

Load context in layers, never all at once:

| Layer | Contents                                                            | When to Load               |
| ----- | ------------------------------------------------------------------- | -------------------------- |
| L0    | This instructions file + active-release.yaml                        | Always                     |
| L1    | Global governance (permissions, feature-flags, interruption-policy) | Platform changes           |
| L2    | Workflow YAML for the active task                                   | Workflow execution         |
| L3    | Constraints for the active industry + baseline                      | Workflow execution         |
| L4    | System prompt for the active workflow                               | Workflow execution         |
| L5    | Relevant schemas (output validation)                                | Before generating output   |
| L6    | Citations/reference metadata                                        | When sources are retrieved |
| L7    | Evaluator rubrics                                                   | Post-execution review      |
| L8    | Regression test cases                                               | Testing/validation         |

## Intent-to-Workflow Auto-Matching

When a user describes a task **without** specifying a workflow, infer the best match from this table:

| 用户意图关键词                               | 匹配工作流                  |
| -------------------------------------------- | --------------------------- |
| 合同、NDA、条款、审查、法律风险、签约        | `contract_review`           |
| 政策、合规、制度、规定、内部规则、法规疑问   | `policy_qa`                 |
| 商业模式、画布、价值主张、收入模式、商业想法 | `business_model_design`     |
| 商业模式验证、校验、假设验证、可行性         | `business_model_validation` |
| 市场进入、GTM、上市、渠道策略、获客          | `go_to_market_review`       |
| 单位经济、CAC、LTV、回本周期、毛利、留存     | `unit_economics_check`      |
| 行业研究、市场规模、竞争格局、投资研究       | `investment_research`       |
| 风险摘要、风险评估、风险清单、风险登记       | `risk_summary`              |
| 尽调、尽职调查、DD、交易审查、并购           | `due_diligence`             |
| SOP、流程、操作规范、标准作业、操作手册      | `sop_generation`            |
| 会议纪要、会议摘要、会议记录、讨论总结       | `meeting_summary`           |
| 项目复盘、回顾、事后分析、retro、改进        | `project_retrospective`     |

Inference rules:

- **User mentions a keyword from the table** → select the matching workflow, proceed to Gate check.
- **User mentions multiple keywords spanning different industries** → ask the user to clarify which task is primary.
- **User mentions nothing matching any workflow** → skip workflow execution; proceed as normal Copilot conversation.
- **User explicitly names a workflow ID or file path** → use that workflow directly, bypass auto-matching.

After matching, proceed to **Workflow Execution Rules** below.

## Workflow Execution Rules

When asked to execute a workflow:

1. **Gate check**: Run the context & intent gate. Confirm understanding with the user.
2. **Load the workflow YAML**: Read from `workflows/{industry}/{workflow_id}.yaml`
3. **Load relevant constraints**: Baseline + industry-specific from `constraints/`
4. **Source freshness & constraint update check**: Before proceeding, check whether the active knowledge base and reference data are up to date for the task's industry and jurisdiction:
   - Check `config/active-release.yaml` for `knowledge_base_version` and `knowledge_bases`
   - If the task is legal/finance/regulated and the active knowledge base is empty (v0.1.0 or `[]`), **flag that model training data may be outdated** and ask the user whether to:
     - (a) Proceed as-is with model knowledge (noting limitation)
     - (b) Pause and fetch current regulatory/official sources online (only if `external_fetch` is approved)
     - (c) Skip this workflow and return to normal conversation
   - If the user approves online fetch, use `fetch_webpage` or registered MCP fetch tools to retrieve current reference materials, then continue
   - Record the freshness decision and any fetched sources in the run snapshot
5. **Load the system prompt**: From `prompts/{industry}/{workflow_id}.system.md`
6. **Execute steps sequentially**: Follow the workflow's `steps` array in order
7. **Handle interruptions**: If a step triggers an interruption condition, pause and wait for user input
8. **Validate output**: Check against the workflow's output schema before presenting
9. **Record run snapshot**: Create a minimized run record (in `runtime/`, NOT in Git)

### Interruption Handling

When a workflow requires pausing (missing input, high risk, human approval needed):

- Save the current state description as a checkpoint
- Clearly state: what is missing, what is needed to resume, and options available
- Wait for explicit user instruction before continuing
- Record interruption details per `schemas/interruption_event.schema.json`

## Three-Agent Orchestration Flow

When a user presents a **task-level goal** (not a simple Q&A), follow this three-agent orchestration flow instead of executing workflows directly.

### Flow Diagram

```
用户目标
    │
    ▼
┌─────────────────────────────────────────────┐
│ ① Task Planner Agent（任务拆解）              │
│ .github/agents/task-planner.agent.md         │
│                                              │
│ 干净室 — 零工作上下文隔离                      │
│ 输出: 任务简报（intent + 验收标准 + 组装说明）  │
└──────────────────┬──────────────────────────┘
         ⬆         │ 任务简报
         │         ▼
         │  ┌─────────────────────────────────────┐
         │  │ 📋 持久化为计划文件                    │
         │  │ runtime/plans/task_plan_{ts}.md      │
         │  │ （带 checkbox 的人机共享视图）          │
         │  └──────────────────┬───────────────────┘
         │                     │ 计划文件
         │                     ▼
         │  ┌─────────────────────────────────────┐
         │  │ ② 执行阶段（本 Agent）                │
         │  │                                      │
         │  │ 按计划文件执行各子任务                  │
         │  │ 每完成一项 → 更新计划文件 checkbox      │
         │  │ 可调取 workflows/prompts/constraints   │
         │  │ 输出: 工作成果                         │
         │  └──────────────────┬───────────────────┘
         │                     │ 计划文件 + 工作成果
         │                     ▼
         │  ┌─────────────────────────────────────┐
         │  │ ③ Task Reviewer Agent（审核）        │
         │  │ .github/agents/task-reviewer.agent.md│
         │  │                                      │
         │  │ 读取计划文件（= 任务简报）+ 工作成果    │
         │  │ 只对比 intent vs result，不看工作过程  │
         │  │ 输出: 审核报告（通过/打回 + 差距分析）  │
         │  └──────────────────┬──────────────────┘
         │                     │ 审核结果
         │                     ▼
         │            ┌──── 通过？────┐
         │            │               │
         │           ✅              ❌
         │            │               │
         │        交付用户      第1次失败？
         │      计划文件归档      │        │
         │    状态: ✅ 已完成   第1次     第2次
         │            │          │        │
         └── 意图修正 ────────┘    ⚠️ 人工介入
            （反馈差距分析         （中断并等待用户）
              给 Planner 修正意图）
```

### Orchestration Rules

**Rule 1 — 任务拆解前置**：对于任何需要多步执行的任务，必须先调用 `task-planner` Agent 生成任务简报，不得直接执行工作流。

**Rule 2 — 干净室隔离**：调用 `task-planner` Agent 时，不得传递任何工作上下文（workflows/prompts/constraints/schemas），仅传递用户原始目标。

**Rule 3 — 审核后置**：每个任务执行完成后，必须调用 `task-reviewer` Agent 进行审核。

**Rule 4 — 审核反馈修正回路（关键规则）**：

- 第 1 次审核不通过 → **将审核报告中的差距分析反馈给 Task Planner Agent**
- Task Planner Agent 根据差距分析**修正意图定义、调整子任务拆解和验收标准**，输出修订版任务简报
- 执行阶段按修订版任务简报重新执行
- 第 2 次审核不通过 → **立即中断**，标记 `requires_human_intervention: true`，等待用户人工介入
- 审核轮次计数器存储在 `runtime/review_attempts_{timestamp}.json` 中

**Rule 5 — 反馈传递约束**：向 Task Planner 传递反馈时，只传递审核报告中的差距分析部分。不得传递任何工作执行上下文、中间产物、系统提示或工具调用记录。

**Rule 6 — 审核 Agent 上下文隔离**：调用 `task-reviewer` Agent 时，只传递任务简报 + 工作成果。不得传递执行过程中的中间产物、工具调用记录或系统提示。

**Rule 7 — 计划文件持久化**：Task Planner Agent 输出任务简报后，必须立即将其写入工作区文件 `runtime/plans/task_plan_{yyyyMMdd_HHmmss}.md`。该文件是任务执行期间的人机共享视图，包含：
- 以 `- [ ]` checkbox 格式列出的子任务清单
- 全局验收标准（同样以 checkbox 列出）
- 文件顶部状态标记：`🔄 执行中` / `⏸️ 已中断` / `✅ 已完成` / `❌ 已打回`

**Rule 8 — 进度实时同步**：执行阶段中，每完成或开始一个子任务，必须立即更新计划文件中对应条目的状态：
- 开始执行：在子任务行追加 `🔄 执行中 (HH:mm)`
- 完成：将 `- [ ]` 改为 `- [x]`，在子任务下方追加 `  - ✅ 完成 (HH:mm): {关键产出摘要}`
- 中断：文件顶部状态改为 `⏸️ 已中断`，在中止处追加 `⏸️ 中断点: {原因 + 恢复条件}`
- 打回重做：将对应子任务的 `[x]` 改回 `[ ]`，追加 `  - ❌ 打回 (HH:mm): {差距摘要}`

中断恢复时，首先读取计划文件定位当前进度，从中断点继续执行。

### 触发条件

此编排流程在以下条件下触发：

- 用户给出的是**高层目标**而非具体工作流请求（参见 Intent-to-Workflow Auto-Matching 表）
- 任务涉及 **2 个以上的子任务** 或 **跨行业/跨工作流的执行**
- 用户明确要求"规划""拆解""审核""把关"

对于**简单、单一工作流任务**（如"审查这份合同"），可以直接走现有 Workflow Execution Rules，跳过编排流程，但最终输出仍应调用 `task-reviewer` Agent 审核一次。

### Plan File Template

计划文件 `runtime/plans/task_plan_{yyyyMMdd_HHmmss}.md` 的标准格式：

```markdown
# 任务计划：{目标一句话摘要}

- 计划文件: `runtime/plans/task_plan_20260506_143000.md`
- 创建时间: 2026-05-06 14:30
- 状态: 🔄 执行中
- 版本: v1
- 审核轮次: 0

## 子任务

- [x] ① 读取市场参考数据
  - ✅ 完成 (14:32): 已加载 data/market_reference_au.yaml，验证 CAPEX/PPA/MLF 参数
- [ ] ② 确认边界参数 🔄 执行中 (14:35)
  - 意图: 验证输入参数在合理范围内，对比参考数据
  - 依赖: 子任务 ①
  - 风险: low
  - 验收标准:
    - [ ] 所有参数已对比 market_reference 数据
    - [ ] 异常偏差已标记并说明
- [ ] ③ 运行财务模型
  - 意图: 执行 solar_financial_engine.py 生成现金流和收益指标
  - 依赖: 子任务 ②
  - 风险: medium
  - 验收标准:
    - [ ] 引擎运行无错误
    - [ ] IRR/NPV/回本周期已产出
- [ ] ④ 生成分析报告
  - 意图: 汇总结果，产出结构化分析报告
  - 依赖: 子任务 ③
  - 风险: low
  - 验收标准:
    - [ ] 报告包含执行摘要、风险矩阵、敏感性分析
    - [ ] 所有数值经交叉校验

## 全局验收标准

- [ ] 意图一致性: 输出与用户原始目标一致
- [ ] 完整性: 所有子任务已产出
- [ ] 数值校验: IRR/NPV 经双路径交叉验证

## 中断记录

{仅在中断时填写，包含 checkpoint 位置和恢复条件}
```

## Constraint Enforcement

Always enforce these constraints from `constraints/baseline/` and `constraints/industries/`:

- **Privacy** (`privacy.yaml`): No secrets in Git, minimize sensitive content, record data classes
- **Citation** (`citation.yaml`): Cite sources for factual claims
- **Human Review** (`human_review.yaml`): Route high-risk outputs to human approval
- **Tool Permissions** (`tool_permissions.yaml`): Respect tool access boundaries

## Industry-Specific Behavior

### Legal

- Never provide final legal advice — always require human review
- Cite relevant laws, regulations, and precedents
- Flag jurisdiction-specific considerations

### Finance

- Never make definitive investment recommendations
- Disclose assumptions and limitations
- Flag missing data points

### Business

- Validate business model assumptions
- Flag market uncertainties
- Recommend validation steps (customer interviews, MVP tests)

### Operations

- Align SOPs with company policies
- Flag procedural gaps
- Suggest measurable success criteria

## Platform Asset Modification Rules

When asked to modify platform assets (workflows, constraints, prompts, schemas, config):

1. Read `config/active-release.yaml` first
2. Identify the specific component and version
3. Propose changes with rationale
4. Wait for explicit user confirmation before writing
5. After writing, verify with schema validation
6. Record the change in the next release manifest update

## Output Conventions

- Use proper Markdown formatting with KaTeX for math
- File paths in backticks: `workflows/legal/contract_review.yaml`
- Code blocks with language identifiers
- Structured data in JSON or YAML blocks
