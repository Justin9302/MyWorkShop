# 当前工作环境创建计划

本计划基于 `workspace_plan.md`、`gitman.md`、`eval.md` 三份文件整理，目标是在当前工作区创建一个可版本化、可审计、可评估、可回滚的 AI 辅助工作平台工程环境。

## 1. 创建目标

当前工作环境不直接承载真实客户内容，而是承载平台的可回滚资产：

- 平台架构文档与实施路线
- 工作流定义
- 约束规则包
- Prompt 模板
- 输出 Schema
- 评估器与回归测试样本
- 示例与脱敏测试材料
- 发布 Manifest 与版本治理记录

真实业务文件、用户上传、运行日志、模型输出、向量索引、密钥和原始反馈只保存在本地运行区或专门数据系统中，不纳入 Git 同步。

## 2. 核心原则

### 2.1 Git 只管理平台能力

GitHub 用来管理“系统如何工作”，不管理“用户实际做了什么”。

应纳入 Git：

- 配置
- 模板
- 规则
- Schema
- 工作流
- 评估逻辑
- 脱敏或合成测试样本
- 平台文档

不纳入 Git：

- 客户文件
- 用户上传
- 运行日志
- 模型输出
- 原始反馈
- 向量库
- API Key
- `.env`
- 任何未脱敏业务数据

### 2.2 平台主流程与评估旁路解耦

主平台负责工作流执行、检索、约束、工具调用、用户交互和审计日志。

评估系统作为 Sidecar Service，只读取运行快照，只输出评估报告和改进建议，不直接修改生产配置。

### 2.3 从第一版开始预留治理能力

即使动态评估与自动进化放在后期，也应从第一版开始保留：

- 运行快照格式
- 审计日志字段
- 人工反馈入口
- 组件版本号
- Active Release Manifest
- 回归测试目录
- 评估报告 Schema

### 2.4 用户输入后的强制上下文读取与意图确认

任何工作流在接收用户输入后，必须先进入“上下文读取与意图确认”阶段，不能直接生成最终答案、执行工具调用或修改项目资产。

该阶段至少包括：

- 读取当前项目结构、相关配置、工作流定义、约束包、Prompt 版本、Schema、Active Release Manifest 和可用参考资料元数据。
- 识别用户输入所属场景、行业、地区、风险等级、目标产物、成功标准和可能缺失的信息。
- 对照当前项目状态判断可执行范围、依赖条件、权限边界、人工审批要求和禁止动作。
- 形成意图确认结果，包括用户目标、已知信息、缺口问题、计划使用的工作流、检索范围、约束规则和预期输出形式。
- 在高风险、信息不足、权限不明确或会改变项目资产的情况下，必须先向用户确认或进入人工审批节点。

该步骤是所有工作流的强制前置门禁，应在工作流 Schema、运行快照和审计日志中显式记录。若该阶段未完成，工作流不得进入执行阶段。

### 2.5 按需分步加载上下文

平台不得在每次运行时一次性加载全部 prompt、资料、规则和历史上下文。每次工作流应根据用户意图、行业场景、地区、风险等级和目标产物，分层、按需加载相关能力，以控制上下文长度、降低误用规则的风险，并提高可审计性。

推荐加载原则：

- 先加载全局最小治理规则，再加载具体工作流规则。
- 先加载元数据和摘要，再按需要加载原文片段。
- 先加载行业通用约束，再加载地区、组织和任务级约束。
- Prompt 模板只加载当前工作流需要的 system、step 和 output 模板，不加载无关行业包。
- 检索资料按权限、适用场景、有效期、权威等级和引用许可过滤后再进入上下文。
- 任何超过上下文预算的资料必须先摘要、聚类、排序或进入二次检索，不得无选择拼接。
- 分步加载过程必须写入运行快照，记录加载了哪些配置、规则、prompt、资料摘要和工具权限。

### 2.6 中断、补充与恢复必须结构化

工作流中断不是普通对话终止，而是将当前运行状态冻结到可恢复 checkpoint，并等待用户补充、人工审批或运行控制指令。

中断分为三类：

- 工作流设计暂停：由 workflow 节点、约束规则或工具权限触发，是正式业务中断，必须记录 checkpoint、暂停原因、待确认问题和恢复节点。
- 用户主动停止：由界面停止按钮触发，用于取消或暂停当前生成、工具调用或长任务，必须记录为 `cancelled_by_user` 或 `interrupted_by_user`。
- 快捷键停止：由键盘快捷键触发，本质上等价于用户主动停止，只作为快速入口，不承担复杂审批逻辑。

用户在中断后的补充内容不得直接拼接进完整 prompt。平台应把补充内容写入 append-only 运行事件，再提取成结构化补丁，例如 `intent_patch`、`context_patch`、`approval_patch`、`constraint_patch`。补丁通过验证后，才能更新 `run_snapshot`、`context_load_plan` 和工作流状态。

恢复前必须重新验证：

- 补充内容是否回答了中断问题。
- 用户意图、行业、地区、风险等级或目标产物是否发生变化。
- 是否触发新的约束、人审或工具权限要求。
- 是否需要重新生成上下文加载计划。
- 是否可以从原 checkpoint 恢复，还是必须退回上下文读取与意图确认门禁。

## 3. 推荐目录结构

建议将当前工作区整理成如下工程骨架：

```text
ai-work-platform/
  README.md

  docs/
    workspace_plan.md
    gitman.md
    eval.md
    architecture.md
    current_workspace_creation_plan.md

  config/
    model-routing.yaml
    feature-flags.yaml
    permissions.yaml
    context-loading.yaml
    mcp-tools.yaml
    interruption-policy.yaml
    tenants.example.yaml
    active-release.yaml

  workflows/
    legal/
      contract_review.yaml
      policy_qa.yaml
    business/
      business_model_design.yaml
      business_model_validation.yaml
      go_to_market_review.yaml
      unit_economics_check.yaml
    finance/
      investment_research.yaml
      due_diligence.yaml
    operations/
      sop_generation.yaml
      meeting_summary.yaml

  constraints/
    baseline/
      privacy.yaml
      safety.yaml
      citation.yaml
      human_review.yaml
    industries/
      legal.yaml
      business.yaml
      finance.yaml
      operations.yaml
    jurisdictions/
      us.yaml
      eu.yaml
      cn.yaml
      au.yaml

  prompts/
    legal/
      contract_review.system.md
      contract_review.review.md
    finance/
      research_summary.system.md
    business/
      business_model_design.system.md
      business_model_validation.system.md
    operations/
      sop_generation.system.md

  schemas/
    workflow.schema.json
    run_snapshot.schema.json
    eval_report.schema.json
    citation.schema.json
    context_load_plan.schema.json
    interruption_event.schema.json

  evaluators/
    rules/
      citation_check.yaml
      risk_check.yaml
      schema_check.yaml
    rubrics/
      contract_review.yaml
      business_model_validation.yaml
      research_summary.yaml
      sop_generation.yaml

  tests/
    eval_cases/
      synthetic/
      anonymized/
    regression/
      workflows/
      constraints/
      prompts/

  examples/
    fake_contract.md
    fake_policy.md
    fake_research_brief.md

  scripts/
    validate_schemas.sh
    run_evals.sh
    validate_context_loading.sh

  runtime/
    .gitkeep

  outputs/
    .gitkeep

  logs/
    .gitkeep

  .env.example
  .gitignore
```

说明：

- `runtime/`、`outputs/`、`logs/` 可以在本地存在，但必须被 `.gitignore` 排除。
- 如果未来拆分服务，`evaluators/` 可升级为独立的 `evaluation-service/`。
- 当前三份文件建议迁入 `docs/`，保留历史来源。

## 4. 第一阶段：工作区骨架创建

目标：先建立不会混淆业务内容和平台资产的本地工程边界。

交付物：

- `README.md`
- `docs/` 文档目录
- `.gitignore`
- `.env.example`
- `config/active-release.yaml`
- 基础目录骨架

关键任务：

1. 初始化 Git 仓库。
2. 将现有三份规划文件归档到 `docs/`。
3. 创建 `.gitignore`，明确排除运行态和敏感数据。
4. 创建 `.env.example`，只保留变量名和说明，不写真实密钥。
5. 创建 `active-release.yaml`，记录当前启用的工作流、约束包、prompt、评估器版本。

审核点：

- Git 中是否只包含平台规则、配置和文档。
- `.gitignore` 是否覆盖客户文件、日志、输出、向量库、密钥。
- 目录命名是否适合后续多人协作。

## 5. 第二阶段：核心平台配置

目标：把“通用底座 + 行业工作流 + 约束引擎”的最小配置落地。

交付物：

- `config/model-routing.yaml`
- `config/permissions.yaml`
- `config/feature-flags.yaml`
- `config/context-loading.yaml`
- `config/mcp-tools.yaml`
- `config/interruption-policy.yaml`
- `schemas/workflow.schema.json`
- `schemas/run_snapshot.schema.json`
- `schemas/context_load_plan.schema.json`
- `schemas/interruption_event.schema.json`
- `schemas/citation.schema.json`
- 第一批行业工作流 YAML

建议先落地 4 个行业包：

- 法律/合规：合同审查、政策问答
- 商业/战略：商业模式建模、商业模式校验、市场进入策略审查、单位经济模型校验
- 金融/投研：行业研究、风险摘要、尽调清单
- 企业运营：SOP 生成、会议纪要、项目复盘

每个工作流至少定义：

- 角色
- 上下文读取与意图确认步骤
- 分步上下文加载策略
- 输入字段
- 检索范围
- 约束规则
- 中断、补充和恢复节点
- 执行步骤
- 输出模板
- 人工审批节点
- 版本号

商业模式建模与校验工作流应额外定义：

- 目标客户、使用场景、痛点和替代方案
- 价值主张、产品边界、差异化假设和不可做范围
- 收入模式、定价假设、成本结构和单位经济模型
- 获客渠道、转化漏斗、销售周期和留存假设
- 市场规模、竞争格局、进入壁垒和监管约束
- 关键假设、验证实验、成功指标和失败阈值
- 证据等级、引用来源、缺口问题和待验证风险
- 输出形态，例如商业模式画布、假设清单、验证计划、风险摘要和下一步实验路线
- 需要人工审批的动作，例如对外发布商业判断、投资建议、财务预测或未经验证的市场结论

审核点：

- 工作流是否像专业流程，而不是普通聊天。
- 是否所有关键输出都有结构化 Schema。
- 是否所有高风险动作都有人审节点。
- 是否避免加载无关行业、地区、prompt、资料和工具权限。
- 是否所有中断点都有恢复条件、取消条件和审计字段。
- 商业模式结论是否明确区分事实、假设、推断和待验证事项。

## 6. 第三阶段：约束与参考资料元数据

目标：把专业边界从 prompt 中拆出来，形成可版本化的规则包。

交付物：

- `constraints/baseline/privacy.yaml`
- `constraints/baseline/safety.yaml`
- `constraints/baseline/citation.yaml`
- `constraints/baseline/human_review.yaml`
- `constraints/industries/legal.yaml`
- `constraints/industries/finance.yaml`
- `constraints/industries/operations.yaml`
- `constraints/jurisdictions/us.yaml`
- `constraints/jurisdictions/au.yaml`

资料元数据最低字段：

```yaml
document_metadata:
  industry: ""
  jurisdiction: ""
  scenario: ""
  effective_date: ""
  expiry_date: ""
  authority_level: ""
  confidentiality: ""
  source_url: ""
  version: ""
  owner: ""
  citable: true
  requires_human_confirmation: false
```

审核点：

- 哪些约束是硬约束，哪些是软约束。
- 哪些行业或地区必须单独配置。
- 哪些资料可以直接引用，哪些只能作为内部参考。

## 7. 第四阶段：审计日志与运行快照

目标：保证未来可评估、可追责、可回滚。

交付物：

- `schemas/run_snapshot.schema.json`
- `schemas/eval_report.schema.json`
- 审计事件字段说明
- 示例运行快照

每次工作流运行至少记录：

- `run_id`
- `workflow_id`
- `workflow_version`
- `prompt_version`
- `constraint_pack_version`
- `knowledge_base_version`
- `model_version`
- `evaluator_version`
- 用户输入摘要
- 上下文读取结果摘要
- 用户意图分析与确认结果
- 上下文加载计划和实际加载结果
- 检索资料及引用片段
- 输出结果摘要
- 触发的约束规则
- 工具调用记录
- 人工审批结果
- 用户反馈
- 工作流状态、当前节点、checkpoint 和恢复节点
- 中断事件、用户补充事件和结构化补丁

建议新增运行状态与中断事件对象：

```yaml
workflow_state:
  status: "running"
  current_node: ""
  last_checkpoint_id: ""
  resume_from_node: ""

interruptions:
  - interrupt_id: ""
    checkpoint_id: ""
    type: "workflow_pause"
    node_id: ""
    reason: ""
    status: "pending"
    pending_questions: []
    created_at: ""

resume_events:
  - event_id: ""
    interrupt_id: ""
    source: "user"
    input_summary: {}
    extracted_updates:
      intent_patch: {}
      context_patch: {}
      approval_patch: {}
      constraint_patch: {}
    validation:
      accepted: true
      reason: ""
    created_at: ""
```

状态建议：

- `running`：正常执行中。
- `waiting_for_user`：等待用户补充信息。
- `waiting_for_approval`：等待人工审批。
- `interrupted_by_user`：用户主动暂停，可选择恢复或修改需求。
- `cancelled_by_user`：用户主动取消，本次运行结束。
- `blocked`：规则或权限阻断，不能自动恢复。
- `completed`：运行完成。

审核点：

- 是否可以从任意一次输出追溯到具体版本。
- 是否避免保存不必要的原始敏感内容。
- 是否能证明工作流执行前已经完成上下文读取与意图确认。
- 是否能证明中断、补充、验证和恢复过程没有丢失审计链路。
- 是否能支持后续评估系统异步读取。

## 8. 第五阶段：评估旁路服务预留

目标：先定义接口和数据契约，后续再实现完整服务。

最小接口：

```http
POST /evaluation/run
GET /evaluation/reports/{run_id}
POST /evaluation/batch
```

输入对象：`run_snapshot`

输出对象：`evaluation_report`

第一批评估维度：

- 引用准确率
- 约束合规率
- 格式合规率
- 风险识别率
- 人工修改率
- 输出采纳率
- 高风险漏检率
- 成本与延迟

审核点：

- 评估服务是否只读输入。
- 评估结果是否只作为建议输出。
- 是否禁止自动修改生产 prompt、约束或工作流。

## 9. 第六阶段：Git 版本治理与回滚

目标：让平台能力可以安全升级，也可以精确回退。

交付物：

- `config/active-release.yaml`
- Git tag 规范
- 变更记录模板
- 回滚操作说明

`active-release.yaml` 示例：

```yaml
active_release:
  id: "release_2026_05_05_001"
  git_commit: ""
  workflow_version: "0.1.0"
  constraint_pack_version: "0.1.0"
  prompt_version: "0.1.0"
  evaluator_version: "0.1.0"
  knowledge_base_version: "kb_0.1.0"
```

建议版本策略：

- 工作流变化：更新 `workflow_version`
- 约束规则变化：更新 `constraint_pack_version`
- Prompt 变化：更新 `prompt_version`
- 评估逻辑变化：更新 `evaluator_version`
- 参考资料变化：更新 `knowledge_base_version`

审核点：

- 是否能按组件单独回退。
- 是否能定位一次质量下降由哪个版本引入。
- 是否每次发布都有 Manifest。

## 10. 第七阶段：动态评估与进化

目标：在真实使用后逐步形成动态评估集，并用受控流程改进平台。

进化流程：

1. 从日志、反馈、失败案例中发现问题。
2. 聚类高频问题和高风险问题。
3. 自动生成候选改进建议。
4. 用动态评估集做回归测试。
5. 人工审批。
6. 灰度发布。
7. 监控指标。
8. 必要时回滚。

可进化对象：

- prompts
- workflow_steps
- constraint_rules
- retrieval_strategy
- knowledge_base_metadata
- output_templates
- tool_permissions
- model_routing

审核点：

- 是否避免“模型自己改自己并自动上线”。
- 是否所有改进都经过测试和人工审批。
- 是否能区分 prompt 问题、检索问题、资料问题、约束问题和模型路由问题。

## 11. Codex 能力与工程集成计划

目标：把当前 Codex 能力、MCP 工具层、规则系统和高星开源项目经验整合为可落地的工程路线。

当前 Codex 适合作为开发期协作者，承担：

- 读取和整理当前工作区文件、目录、Schema、配置和规划文档。
- 根据用户目标修改平台资产，例如文档、workflow、prompt、constraint、schema 和测试样本。
- 运行本地校验脚本、检查 Git 状态、生成变更摘要。
- 在需要时检索官方文档或 GitHub 参考项目，并将可借鉴模式转化为本项目的约束与工程计划。
- 帮助维护“先读项目现状、再确认意图、再执行”的工作习惯。

当前 Codex 不应直接承担：

- 直接处理真实客户敏感内容并写入 Git。
- 未经确认修改生产工作流、prompt、约束包或发布 Manifest。
- 自动发布高风险变更。
- 在没有上下文加载计划的情况下拼接大量资料进入模型上下文。

建议参考的工程分工：

- LangGraph 类框架：参考其状态机、长流程、持久化执行和 human-in-the-loop 设计，用于未来工作流运行器。
- LlamaIndex 类框架：参考其文档解析、索引、检索和资料元数据管理，用于未来 RAG 层。
- Guardrails / JSON Schema 类机制：参考其结构化输出、校验、失败重试和拒绝策略，用于输出约束层。
- Promptfoo / Ragas / OpenAI Evals 类工具：参考其测试集、回归测试、RAG 评估和红队测试，用于评估旁路。
- Langfuse 类平台：参考其 trace、prompt 版本、dataset、人工标注和质量反馈闭环，用于观测与持续改进。
- MCP 官方参考服务器：参考 Filesystem、Git、Memory、Fetch、Time 等工具边界，用于标准化外部工具接入。

参考项目链接：

- LangGraph: `https://github.com/langchain-ai/langgraph`
- LlamaIndex: `https://github.com/run-llama/llama_index`
- Guardrails AI: `https://github.com/guardrails-ai/guardrails`
- Promptfoo: `https://github.com/promptfoo/promptfoo`
- Ragas: `https://github.com/explodinggradients/ragas`
- OpenAI Evals: `https://github.com/openai/evals`
- Langfuse: `https://github.com/langfuse/langfuse`
- MCP Servers: `https://github.com/modelcontextprotocol/servers`

第一批建议的 MCP 工具配置：

```yaml
mcp_tools:
  filesystem:
    purpose: "读取项目结构、配置、workflow、prompt、schema 和规则包"
    default_permission: "read_only"
    write_requires_confirmation: true

  git:
    purpose: "读取版本历史、diff、tag 和回滚点"
    default_permission: "read_only"
    write_requires_confirmation: true

  github:
    purpose: "同步平台能力资产、创建 PR、管理 issue 和审查变更"
    default_permission: "read_only"
    write_requires_confirmation: true

  fetch:
    purpose: "读取公开标准、官方文档和参考项目资料"
    default_permission: "read_only"
    citation_required: true

  memory:
    purpose: "保存非敏感的平台偏好、架构决策和行业包演进记录"
    default_permission: "restricted"
    prohibited_content:
      - "真实客户内容"
      - "密钥"
      - "未脱敏业务数据"

  database:
    purpose: "后续读取审计日志、运行快照和评估报告"
    default_permission: "read_only"
    write_requires_confirmation: true
```

MCP 接入原则：

- 所有 MCP 工具先在 `config/mcp-tools.yaml` 中登记用途、权限、输入输出摘要和审批要求。
- 工作流只能调用已登记且符合当前场景权限的工具。
- 可写工具默认需要用户确认或人工审批。
- 工具调用前必须完成上下文读取、意图确认和权限判断。
- 工具调用结果只进入当前运行快照的摘要字段，敏感原文不得自动进入 Git。

## 12. 分步加载能力设计

目标：根据实际业务需要加载相关 prompt、上下文、商业约束、行业约束和工具权限，尽量保持上下文长度可控。

推荐将每次工作流运行拆成以下加载层：

```text
L0：全局安全与治理基线
L1：当前项目状态与 Active Release
L2：用户意图与工作流选择
L3：行业、地区、组织和任务约束
L4：当前工作流 prompt 与输出模板
L5：参考资料元数据与候选检索结果
L6：必要原文片段、案例和示例
L7：工具权限、审批节点和执行计划
L8：评估规则与运行快照字段
```

每一层的加载目标：

- L0 加载隐私、安全、引用、人审、工具权限和 Git 边界等全局硬规则。
- L1 加载 `active-release.yaml`、相关版本号、当前目录状态和可用资产清单。
- L2 根据用户输入判断行业、地区、任务类型、风险等级、目标产物和缺失信息。
- L3 只加载命中的行业、地区、组织和任务规则，不加载无关规则包。
- L4 只加载被选中工作流的 system prompt、步骤 prompt 和输出模板。
- L5 先加载资料元数据、摘要、权威等级、有效期和引用许可。
- L6 只有当 L5 证明相关且权限允许时，才加载必要原文片段。
- L7 根据任务动作决定是否启用文件、Git、GitHub、Fetch、数据库等工具。
- L8 根据工作流风险选择评估规则，并确定本次 `run_snapshot` 必须记录的字段。

建议新增 `context_load_plan` 对象：

```yaml
context_load_plan:
  run_id: ""
  workflow_id: ""
  intent_summary: ""
  selected_industry: ""
  selected_jurisdiction: ""
  risk_level: ""
  loaded_layers:
    - "L0"
    - "L1"
    - "L2"
  loaded_assets:
    configs: []
    workflows: []
    constraints: []
    prompts: []
    schemas: []
    source_metadata: []
    source_excerpts: []
    tools: []
  excluded_assets:
    - asset: ""
      reason: ""
  context_budget:
    max_tokens: 0
    reserved_for_user_input: 0
    reserved_for_output: 0
  confirmation:
    required: true
    status: "pending"
```

上下文裁剪规则：

- 优先保留用户目标、强制约束、当前工作流步骤、引用来源和输出 Schema。
- 对长资料先保留标题、来源、版本、摘要、适用范围和关键片段。
- 对历史对话只保留与当前目标、决策、约束或未完成事项直接相关的摘要。
- 对冲突规则按优先级处理：法律法规与安全规则高于行业建议，组织政策高于示例模板，当前用户确认高于旧上下文偏好。
- 当上下文预算不足时，必须记录被排除资产及原因，不能静默丢弃关键约束。

开发交付物：

- `config/context-loading.yaml`
- `schemas/context_load_plan.schema.json`
- `constraints/baseline/context_intent_gate.yaml`
- `constraints/baseline/tool_permissions.yaml`
- `scripts/validate_context_loading.sh`
- 在 `schemas/run_snapshot.schema.json` 中加入上下文读取、意图确认、加载计划和门禁结果字段。

## 13. 中断与恢复机制设计

目标：让用户补充、人工审批、工具授权和主动停止都能进入同一个可审计、可恢复的运行模型。

正式业务中断由工作流或规则触发，典型场景包括：

- 用户输入缺少必要字段。
- 风险等级较高，需要人工确认。
- 即将调用写入类工具。
- 即将修改 Git、GitHub、数据库、文件或平台资产。
- 检索资料不足，无法支撑结论。
- 输出前需要用户选择格式、范围或审批意见。

用户主动中断由界面触发：

- 停止按钮：将当前生成或工具调用标记为 `interrupted_by_user` 或 `cancelled_by_user`。
- 快捷键：作为停止按钮的快速入口，建议映射到同一套运行控制逻辑。
- 继续按钮：在用户补充或确认后，触发恢复验证。
- 修改需求：将补充内容作为新的 `intent_patch`，必要时回到意图确认门禁。
- 放弃本次运行：将状态置为 `cancelled_by_user`，不得继续调用工具或生成最终输出。

中断后的用户输入处理流程：

```text
当前 run 暂停
  ↓
生成 interrupt_id 和 checkpoint_id
  ↓
记录暂停原因、待确认问题、当前节点和恢复节点
  ↓
用户补充信息或确认/拒绝
  ↓
写入 append-only resume event
  ↓
提取 intent/context/approval/constraint patch
  ↓
验证补丁是否完整、合规、可恢复
  ↓
更新 workflow_state、run_snapshot 和 context_load_plan
  ↓
从 checkpoint 恢复，或退回前置门禁重新判断
```

补丁合并规则：

- `intent_patch` 用于更新用户目标、范围、行业、地区、风险等级、目标产物或成功标准。
- `context_patch` 用于更新需要加载的资料、prompt、规则、示例或上下文摘要。
- `approval_patch` 用于更新人工审批、工具授权、继续/取消等决策。
- `constraint_patch` 用于更新本次运行的额外限制、禁止动作或输出要求。
- 冲突时保留原始事件和新补丁，按规则优先级重新决策，不得静默覆盖关键约束。

恢复验证规则：

- 如果只是补充缺失字段，可以从原 checkpoint 恢复。
- 如果改变了用户意图、行业、地区或风险等级，必须回到上下文读取与意图确认门禁。
- 如果新增了资料范围或工具需求，必须重新生成 `context_load_plan`。
- 如果拒绝审批或触发禁止动作，运行状态应变为 `blocked` 或 `cancelled_by_user`。
- 如果用户只是点击停止按钮但未说明是否继续，运行状态应保持 `interrupted_by_user`，等待用户选择继续、修改需求或放弃。

开发交付物：

- `config/interruption-policy.yaml`
- `schemas/interruption_event.schema.json`
- 在 `schemas/run_snapshot.schema.json` 中加入 `workflow_state`、`interruptions` 和 `resume_events`。
- 在 `schemas/workflow.schema.json` 中要求每个中断节点定义 `pause_reason`、`resume_condition`、`cancel_condition` 和 `audit_fields`。
- 在 `constraints/baseline/human_review.yaml` 中定义哪些风险和动作必须触发正式业务中断。

## 14. 建议实施顺序

```text
阶段 1：工作区骨架与 Git 边界
阶段 2：核心平台配置与行业工作流
阶段 3：约束包与资料元数据
阶段 4：运行快照、审计日志与 Schema
阶段 5：评估旁路接口预留
阶段 6：版本治理、发布 Manifest 与回滚
阶段 7：动态评估集、灰度发布与受控进化
阶段 8：MCP 工具接入、分步加载与运行器实现
阶段 9：中断、补充、恢复与用户运行控制
```

最小可审核版本建议先完成阶段 1 到阶段 4，并补齐分步加载 Schema、上下文门禁规则和中断事件 Schema。阶段 5 到阶段 9 先保留接口、目录和配置契约，不急于实现完整系统。

## 15. 当前优先级清单

P0，立即创建：

- `.gitignore`
- `.env.example`
- `README.md`
- `docs/`
- `config/active-release.yaml`
- `config/context-loading.yaml`
- `config/mcp-tools.yaml`
- `config/interruption-policy.yaml`
- `schemas/workflow.schema.json`
- `schemas/run_snapshot.schema.json`
- `schemas/eval_report.schema.json`
- `schemas/context_load_plan.schema.json`
- `schemas/interruption_event.schema.json`
- `constraints/baseline/context_intent_gate.yaml`

P1，第一轮平台骨架：

- `workflows/legal/contract_review.yaml`
- `workflows/business/business_model_design.yaml`
- `workflows/business/business_model_validation.yaml`
- `constraints/baseline/privacy.yaml`
- `constraints/baseline/citation.yaml`
- `constraints/baseline/human_review.yaml`
- `constraints/baseline/tool_permissions.yaml`
- `constraints/industries/business.yaml`
- `prompts/legal/contract_review.system.md`
- `prompts/business/business_model_design.system.md`
- `prompts/business/business_model_validation.system.md`
- `tests/eval_cases/synthetic/`
- `scripts/validate_context_loading.sh`
- `scripts/validate_interruption_flow.sh`

P2，第二轮扩展：

- 商业/战略扩展工作流
- 金融/投研工作流
- 企业运营工作流
- 批量评估入口
- 质量仪表盘设计
- A/B 测试和灰度发布机制
- MCP 工具运行沙箱
- 工作流运行器原型
- 中断恢复原型和用户停止/继续控制

## 16. 审核问题

建议在正式创建工程骨架前确认以下问题：

1. 当前仓库名称是否采用 `ai-work-platform`。
2. 现有三份文档是否迁入 `docs/`，还是继续保留在根目录。
3. 第一批行业包是否确认为法律/合规、商业/战略、金融/投研、企业运营。
4. 是否需要从第一版就引入真实数据库或对象存储，还是先用本地模拟目录。
5. 评估 Sidecar 第一版是否只做 Schema 和接口契约，不做完整服务实现。
6. 版本号是否从 `0.1.0` 开始。
7. GitHub 仓库是否公开、私有，或先只保留本地 Git。
8. 第一批 MCP 工具是否只启用只读 Filesystem、Git、Fetch。
9. 上下文预算是否先用固定上限，还是按模型与工作流动态配置。
10. 是否将 LangGraph、LlamaIndex、Promptfoo、Ragas、Langfuse 作为参考模式，而不是第一版硬依赖。
11. 用户停止按钮默认是取消本次运行，还是暂停并等待用户选择继续/修改/放弃。
12. 第一版是否只实现工作流设计暂停，不实现复杂 UI 快捷键。

## 17. 验收标准

工作环境创建完成后，应满足：

- Git 仓库中没有真实业务数据、密钥、日志、模型输出。
- 所有平台规则、工作流、prompt、schema、评估器都有明确目录。
- 每个工作流都能说明输入、检索范围、约束、步骤、输出和人工审批点。
- 商业/战略工作流能说明商业模式中的事实、假设、推断、证据等级、验证实验和失败阈值。
- 每个工作流都把用户输入后的上下文读取与意图确认作为强制前置门禁。
- 每个工作流都能生成 `context_load_plan`，说明实际加载了哪些 prompt、规则、资料和工具权限。
- 每个工作流都能定义正式业务中断点、用户主动停止状态、恢复条件和取消条件。
- 每次运行都能生成可评估的 `run_snapshot`。
- 每个 `run_snapshot` 都能记录上下文读取结果、意图确认结果和是否通过前置门禁。
- 每个 `run_snapshot` 都能记录上下文加载计划、实际加载结果、被排除资产及原因。
- 每个 `run_snapshot` 都能记录中断事件、用户补充事件、结构化补丁、checkpoint 和恢复结果。
- 评估系统可以通过标准接口读取快照并输出报告。
- 发布版本可以通过 `active-release.yaml` 追踪。
- 平台配置可以通过 Git commit 或 tag 回退。

## 18. 建议下一步

如果本计划审核通过，下一步应优先补齐 `workflow.schema.json`、`context_load_plan.schema.json`、`interruption_event.schema.json`、`context-loading.yaml`、`mcp-tools.yaml`、`interruption-policy.yaml` 和 `context_intent_gate.yaml`，再创建第一个最小法律/合规工作流 `contract_review.yaml`，并同步创建 `business_model_design.yaml` 与 `business_model_validation.yaml` 的最小版本，形成可验证的“输入、读上下文、确认意图、按需加载、中断补充、恢复执行、人审、快照、评估”闭环。
